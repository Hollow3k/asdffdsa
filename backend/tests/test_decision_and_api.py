from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.core.errors import FutureDataLeakageError
from app.services.decision_analysis import (
    assert_no_leakage,
    compute_risk_adjustments,
    filter_observations_available_at,
)
from tests.fakes import BIAS, base


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def run_calibration(api, start="2025-10-01", end="2025-12-31", cutoff="17:00"):
    r = api.post("/api/calibrations", json={"start_date": start, "end_date": end, "cutoff_time": cutoff})
    assert r.status_code == 202, r.text
    return r.json()


# ------------------------------------------------------------------ pure risk maths


def test_risk_adjustment_signs_and_no_double_counting():
    errors = np.array([-1000.0, 0.0, 500.0, 1000.0, 2000.0])  # forecast - actual
    forecast = [10000.0, 800.0, None]
    r = compute_risk_adjustments(forecast, errors, 90)
    assert r["bias"] == pytest.approx(500.0)
    # bias adjustment LOWERS the forecast when forecasts were too high
    assert r["adjusted"][0] == pytest.approx(9500.0)
    q = float(np.percentile(errors, 90))  # 1600
    assert r["buffer"] == pytest.approx(q)
    assert r["conservative"][0] == pytest.approx(10000.0 - q)  # F - Q, bias NOT subtracted again
    assert r["conservative"][1] == 0.0 and r["floored"] == 1  # floored at 0 MW
    assert r["conservative"][2] is None
    assert r["buffer"] - r["bias"] == pytest.approx(q - 500.0)  # residual margin beyond bias adjustment


def test_buffer_is_zero_when_forecasts_are_not_overforecast_at_that_confidence():
    errors = np.array([-500.0, -400.0, -300.0, -200.0, -100.0])
    r = compute_risk_adjustments([1000.0], errors, 95)
    assert r["buffer"] == 0.0 and r["conservative"][0] == 1000.0
    assert r["adjusted"][0] > 1000.0  # under-forecast -> bias adjustment raises estimate


def test_band_orders_low_below_high():
    errors = np.random.default_rng(0).normal(300, 800, 500)
    r = compute_risk_adjustments([5000.0], errors, 95)
    assert r["low"][0] <= r["conservative"][0] + 1e-9 and r["low"][0] < r["high"][0]


# ------------------------------------------------------------------ leakage guards (pure)


def obs_frame(avail_hours: list[datetime]) -> pd.DataFrame:
    n = len(avail_hours)
    return pd.DataFrame(
        {
            "actual_available_at": pd.to_datetime(avail_hours, utc=True),
            "forecast_publish_time": pd.to_datetime([h - timedelta(days=1) for h in avail_hours], utc=True),
            "error_mw": [1.0] * n,
        }
    )


def test_filter_drops_observations_not_yet_available_at_cutoff():
    cutoff = utc(2026, 1, 1, 17)
    obs = obs_frame([utc(2025, 12, 31, 23), utc(2026, 1, 1, 17), utc(2026, 1, 1, 17, 1), utc(2026, 1, 10, 0)])
    kept, excluded = filter_observations_available_at(obs, cutoff)
    assert len(kept) == 2 and excluded == 2  # available_at == cutoff is allowed


def test_assert_no_leakage_raises():
    with pytest.raises(FutureDataLeakageError):
        assert_no_leakage(obs_frame([utc(2026, 1, 2)]), utc(2026, 1, 1, 17))


# ------------------------------------------------------------------ API: calibration lifecycle


def test_initial_state_has_no_active_calibration(api):
    r = api.get("/api/calibrations/active")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NO_ACTIVE_CALIBRATION"
    assert api.get("/api/calibrations").json() == []
    d = api.get("/api/decisions/2026-01-15")
    assert d.status_code == 404 and d.json()["error"]["code"] == "NO_ACTIVE_CALIBRATION"


def test_api_calibration_lifecycle(api):
    created = run_calibration(api)
    assert created["version"] == 1
    got = api.get(f"/api/calibrations/{created['id']}").json()
    assert got["status"] == "completed" and got["is_active"] is True
    m = got["metrics"]
    for key in ("mae_mw", "rmse_mw", "bias_mw", "p90_abs_error_mw", "p95_abs_error_mw", "p90_positive_error_mw", "p95_positive_error_mw", "n"):
        assert m[key] is not None
    assert got["start_date"] == "2025-10-01" and got["end_date"] == "2025-12-31"
    assert len(got["breakdowns"]["by_hour"]) == 24 and len(got["breakdowns"]["by_day"]) == 92
    assert got["quality"]["matched_pairs"] == m["n"]
    assert api.get("/api/calibrations/active").json()["id"] == created["id"]
    page = api.get(f"/api/calibrations/{created['id']}/observations", params={"limit": 5}).json()
    assert page["total"] == m["n"] and len(page["items"]) == 5 and page["items"][0]["error_mw"] > 0

    v2 = run_calibration(api, "2025-11-01", "2025-11-30")
    assert v2["version"] == 2 and api.get("/api/calibrations/active").json()["id"] == created["id"]
    act = api.post(f"/api/calibrations/{v2['id']}/activate")
    assert act.status_code == 200 and act.json()["is_active"] is True
    assert [c["is_active"] for c in api.get("/api/calibrations").json()] == [True, False]


def test_api_validation_errors(api):
    bad = api.post("/api/calibrations", json={"start_date": "2025-12-31", "end_date": "2025-10-01"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert api.post("/api/calibrations", json={"start_date": "2025-10-01", "end_date": "2025-12-31", "cutoff_time": "25:99"}).status_code == 422
    future = api.post("/api/calibrations", json={"start_date": "2099-01-01", "end_date": "2099-02-01"})
    assert future.status_code == 422
    assert api.post("/api/calibrations", json={"start_date": "2020-01-01", "end_date": "2025-12-31"}).status_code == 422  # too long
    assert api.get("/api/calibrations/nope").status_code == 404
    assert api.post("/api/calibrations/nope/activate").status_code == 404


@pytest.mark.parametrize(
    "path,code",
    [
        ("/api/decisions/2025-12-31", "DELIVERY_DATE_OUT_OF_RANGE"),
        ("/api/decisions/2026-02-01", "DELIVERY_DATE_OUT_OF_RANGE"),
    ],
)
def test_decision_date_outside_january_2026_rejected(api, path, code):
    run_calibration(api)
    r = api.get(path)
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_invalid_decision_inputs(api):
    run_calibration(api)
    assert api.get("/api/decisions/2026-01-15", params={"cutoff": "7pm"}).status_code == 422
    assert api.get("/api/decisions/2026-01-15", params={"percentile": 10}).status_code == 422
    assert api.get("/api/decisions/2026-01-15", params={"percentile": 100}).status_code == 422
    assert api.get("/api/decisions/not-a-date").status_code == 422


# ------------------------------------------------------------------ API: decision correctness


def forecast_calls(fake):
    return [r for r in fake.requests if "WINDFOR" in r.url.path]


def test_decision_uses_latest_vintage_at_or_before_cutoff_and_never_loads_later_ones(api, fake):
    run_calibration(api)
    fake.requests.clear()
    r = api.get("/api/decisions/2026-01-15", params={"cutoff": "17:00", "percentile": 95})
    assert r.status_code == 200, r.text
    j = r.json()
    # fake publishes at 02:30, 05:30, 08:30, 11:30, 14:30, 17:30 ... -> 14:30 is latest <= 17:00 on the 14th
    assert j["forecast"]["vintage_publish_time_utc"] == "2026-01-14T14:30:00Z"
    assert j["cutoff"]["utc"] == "2026-01-14T17:00:00Z" and j["cutoff"]["local_iso"].startswith("2026-01-14T17:00:00")
    assert j["forecast"]["is_complete"] and len(j["hours"]) == 24
    # Hour values come from exactly that vintage
    h0 = j["hours"][0]
    expected = base(utc(2026, 1, 15, 0)) + BIAS + (utc(2026, 1, 15, 0) - utc(2026, 1, 14, 14, 30)).total_seconds() / 3600
    assert h0["forecast_mw"] == pytest.approx(expected, abs=1e-2)
    # No request ever asked for forecasts published after the cutoff, and no actuals for January.
    for req in forecast_calls(fake):
        to = datetime.fromisoformat(req.url.params["publishDateTimeTo"].replace("Z", "+00:00"))
        assert to <= utc(2026, 1, 14, 17), f"requested vintages up to {to}"
    for req in fake.requests:
        if "FUELHH" in req.url.path:
            assert req.url.params["settlementDateTo"] < "2026-01-01"


def test_cutoff_just_before_a_publication_excludes_it(api):
    run_calibration(api)
    a = api.get("/api/decisions/2026-01-15", params={"cutoff": "17:29"}).json()
    b = api.get("/api/decisions/2026-01-15", params={"cutoff": "17:30"}).json()
    assert a["forecast"]["vintage_publish_time_utc"] == "2026-01-14T14:30:00Z"
    assert b["forecast"]["vintage_publish_time_utc"] == "2026-01-14T17:30:00Z"  # published exactly at cutoff -> eligible


def test_decision_risk_numbers_follow_the_calibration(api):
    created = run_calibration(api)
    j = api.get("/api/decisions/2026-01-15", params={"percentile": 95}).json()
    r, m = j["risk"], j["metrics"]
    assert j["calibration"]["id"] == created["id"] and j["calibration"]["pairs_used"] == m["n"]
    assert r["bias_mw"] == pytest.approx(m["bias_mw"]) and r["bias_adjustment_mw"] == pytest.approx(-m["bias_mw"])
    assert r["shortfall_buffer_mw"] == pytest.approx(max(0, m["p95_error_mw"]))
    assert r["residual_buffer_mw"] == pytest.approx(r["shortfall_buffer_mw"] - r["bias_mw"])
    for h in j["hours"]:
        assert h["conservative_mw"] == pytest.approx(max(0.0, h["forecast_mw"] - r["shortfall_buffer_mw"]))
        assert h["bias_adjusted_mw"] == pytest.approx(max(0.0, h["forecast_mw"] - r["bias_mw"]))
    p90 = api.get("/api/decisions/2026-01-15", params={"percentile": 90}).json()["risk"]
    assert p90["shortfall_buffer_mw"] <= r["shortfall_buffer_mw"]
    assert "not applied twice" in " ".join(j["explanation"]["steps"])
    assert "purchase" in j["procurement_note"] and j["limitations"]


def test_calibration_through_december_is_trimmed_for_a_1_january_decision(api):
    run_calibration(api)  # ends 31 Dec; the 1 Jan 17:00-on-31-Dec cutoff predates the end of 31 Dec
    j = api.get("/api/decisions/2026-01-01").json()
    cal = j["calibration"]
    assert cal["pairs_excluded_not_yet_available"] > 0
    assert cal["pairs_used"] + cal["pairs_excluded_not_yet_available"] == cal["pairs_stored"]
    assert any(w["code"] == "CALIBRATION_TRIMMED_TO_CUTOFF" for w in j["warnings"])
    # The next day sees the whole of December
    j2 = api.get("/api/decisions/2026-01-02").json()
    assert j2["calibration"]["pairs_excluded_not_yet_available"] == 0


def test_calibration_extending_into_january_cannot_inform_earlier_decisions(api):
    run_calibration(api, "2025-12-01", "2026-01-20")
    j = api.get("/api/decisions/2026-01-10").json()
    cal = j["calibration"]
    assert cal["pairs_excluded_not_yet_available"] > 0
    # Cutoff is 9 Jan 17:00: only the first 17 hours of 9 Jan had been observed, nothing later.
    assert cal["effective_end_date"] == "2026-01-09"
    assert cal["pairs_used"] == 31 * 24 + 8 * 24 + 17  # all Dec, 1-8 Jan, and hours 00:00-16:00 of 9 Jan
    # Every used pair is knowable: stored obs available_at must be <= cutoff
    obs = api.get(f"/api/calibrations/{cal['id']}/observations", params={"limit": 2000}).json()["items"]
    cutoff = datetime.fromisoformat(j["cutoff"]["utc"].replace("Z", "+00:00"))
    usable = [o for o in obs if datetime.fromisoformat(o["actual_available_at"].replace("Z", "+00:00")) <= cutoff]
    assert len(usable) == cal["pairs_used"]


def test_calibration_that_starts_after_the_cutoff_is_rejected_with_explanation(api):
    run_calibration(api, "2026-01-12", "2026-01-25")
    r = api.get("/api/decisions/2026-01-10")
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "CALIBRATION_UNAVAILABLE_AT_CUTOFF"
    assert "already observed" in body["message"] and body["details"]["pairs_available_at_cutoff"] == 0


def test_decision_with_no_eligible_forecast(api, fake):
    run_calibration(api)
    fake.world_start = datetime(2026, 1, 14, 20, tzinfo=UTC)  # nothing published before the cutoff
    fake.drop_vintage = lambda p: True
    r = api.get("/api/decisions/2026-01-20")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NO_ELIGIBLE_FORECAST"


def test_incomplete_forecast_is_reported_not_filled(api, fake):
    run_calibration(api)
    fake.drop_forecast = lambda pub, start: start in (utc(2026, 1, 16, 5), utc(2026, 1, 16, 6))
    j = api.get("/api/decisions/2026-01-16").json()
    assert j["forecast"]["is_complete"] is False
    assert j["forecast"]["missing_hours"] == ["05:00", "06:00"]
    missing = [h for h in j["hours"] if h["missing"]]
    assert [h["local_label"] for h in missing] == ["05:00", "06:00"]
    assert all(h["forecast_mw"] is None and h["conservative_mw"] is None for h in missing)
    assert any(w["code"] == "INCOMPLETE_FORECAST" for w in j["warnings"])


def test_upstream_failure_surfaces_as_error_not_fake_data(api, fake):
    run_calibration(api)
    fake.fail_with = 503
    r = api.get("/api/decisions/2026-01-22")
    assert r.status_code == 502 and r.json()["error"]["code"] == "ELEXON_UNAVAILABLE"
    assert "Traceback" not in r.text


# ------------------------------------------------------------------ API: evaluation


def test_evaluation_scores_forecast_against_aligned_actuals(api):
    run_calibration(api)
    j = api.get("/api/decisions/2026-01-15/evaluation", params={"percentile": 95}).json()
    assert "Retrospective" in j["notice"]
    s = j["summary"]
    assert s["matched_pairs"] == 24 and s["actuals_available"] and s["hours_missing_actual"] == 0
    for h in j["hours"]:
        t = datetime.fromisoformat(h["start_utc"].replace("Z", "+00:00"))
        assert h["actual_mw"] == pytest.approx(base(t))
        assert h["error_mw"] == pytest.approx(h["forecast_mw"] - h["actual_mw"])
    assert s["metrics"]["bias_mw"] > BIAS
    assert s["share_actual_below_conservative"] is not None


def test_evaluation_flags_missing_actuals(api, fake):
    run_calibration(api)
    fake.drop_actual = lambda t: t.date() == date(2026, 1, 18) and t.hour == 3
    j = api.get("/api/decisions/2026-01-18/evaluation").json()
    assert j["summary"]["matched_pairs"] == 23 and j["summary"]["hours_missing_actual"] == 1
    gap = [h for h in j["hours"] if h["actual_mw"] is None]
    assert [h["local_label"] for h in gap] == ["03:00"] and gap[0]["error_mw"] is None


def test_evaluation_without_calibration_still_works_without_bands(api):
    j = api.get("/api/decisions/2026-01-15/evaluation").json()
    assert j["calibration"] is None and j["summary"]["percentile"] is None
    assert all(h["conservative_mw"] is None for h in j["hours"])
    assert any(w["code"] == "NO_ACTIVE_CALIBRATION" for w in j["warnings"])


# ------------------------------------------------------------------ misc endpoints


def test_health_config_and_coverage(api):
    h = api.get("/api/health").json()
    assert h["status"] == "ok" and h["database"]["ok"] is True
    cfg = api.get("/api/config").json()
    assert cfg["decision_window_start"] == "2026-01-01" and cfg["default_calibration_end"] == "2025-12-31"
    assert cfg["timezone"] == "Europe/London"
    empty = api.get("/api/data-coverage").json()
    assert empty["forecast"]["rows"] == 0 and empty["actual"]["first"] is None
    run_calibration(api, "2025-11-01", "2025-11-30")
    cov = api.get("/api/data-coverage").json()
    assert cov["forecast"]["rows"] > 0 and cov["actual"]["rows"] == 30 * 48 and cov["gaps"] == []
    assert api.get("/api/data-coverage", params={"start_date": "2025-11-01"}).status_code == 422


def test_coverage_reports_gaps(api, fake):
    fake.drop_actual = lambda t: t.date() == date(2025, 11, 10) and t.hour in (5, 6)
    run_calibration(api, "2025-11-01", "2025-11-30")
    cov = api.get("/api/data-coverage", params={"start_date": "2025-11-01", "end_date": "2025-11-30"}).json()
    gaps = [g for g in cov["gaps"] if g["kind"] == "actual_missing_half_hours"]
    assert len(gaps) == 1 and "4 half-hour" in gaps[0]["description"]


def test_cors_headers_for_configured_origin(api):
    r = api.options(
        "/api/calibrations",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = api.options("/api/calibrations", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_error_envelope_never_leaks_internals(api, container, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail /etc/passwd")

    monkeypatch.setattr(container.decisions, "analyze", boom)
    api.app.state.container = container
    r = api.get("/api/decisions/2026-01-15")
    assert r.status_code == 500 and r.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret" not in r.text and "passwd" not in r.text
