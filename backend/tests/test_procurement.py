from datetime import UTC, datetime

import pytest

from app.schemas.decision import ForecastHour
from app.services.procurement import build_plan, hour_position
from tests.fakes import BIAS, base


def fh(label: str, forecast: float | None, adjusted: float | None = None, cautious: float | None = None) -> ForecastHour:
    h = int(label[:2])
    return ForecastHour(
        start_utc=datetime(2026, 1, 15, h, tzinfo=UTC),
        local_label=label,
        local_iso=f"2026-01-15T{label}:00+00:00",
        hour_local=h,
        forecast_mw=forecast,
        missing=forecast is None,
        bias_adjusted_mw=adjusted,
        conservative_mw=cautious,
        interval_low_mw=cautious,
        interval_high_mw=forecast,
    )


# ------------------------------------------------------------------ pure maths


def test_hour_position_covers_shortfall_surplus_and_contracts():
    assert hour_position(10000, 0, 6000) == (4000, 6000, 0)  # buy the gap
    assert hour_position(10000, 1000, 6000) == (3000, 6000, 0)  # contracts reduce the gap
    assert hour_position(10000, 0, 12000) == (0, 10000, 2000)  # surplus wind never counts as negative purchase
    assert hour_position(5000, 8000, 3000) == (0, 0, 3000)  # over-contracted: nothing to buy, wind all surplus
    assert hour_position(0, 0, 3000) == (0, 0, 3000)


def test_build_plan_applies_wind_share_to_all_three_cases():
    hours = [fh("00:00", 12000, adjusted=10000, cautious=8000)]
    plan, scenarios = build_plan(hours, [10000], [1000], wind_share_pct=50, percentile=95)
    h = plan[0]
    # wind = 50% of national; residual demand = 10000 - 1000 = 9000
    assert (h.wind_forecast_mw, h.wind_expected_mw, h.wind_cautious_mw) == (6000, 5000, 4000)
    assert (h.buy_forecast_mw, h.buy_expected_mw, h.buy_cautious_mw) == (3000, 4000, 5000)
    s = {x.key: x for x in scenarios}
    assert s["cautious"].buy_total_mwh == 5000 and s["expected"].buy_total_mwh == 4000 and s["forecast"].buy_total_mwh == 3000
    # cautious is always >= expected when the buffer is >= bias: buying more is the safer plan
    assert s["cautious"].buy_total_mwh >= s["forecast"].buy_total_mwh
    assert s["cautious"].wind_used_mwh == 4000 and s["cautious"].wind_cover_pct == pytest.approx(100 * 4000 / 9000)


def test_totals_peak_and_surplus_over_several_hours():
    hours = [
        fh("00:00", 8000, 7000, 5000),
        fh("01:00", 4000, 3500, 1000),
        fh("02:00", 20000, 19000, 15000),
    ]
    plan, scenarios = build_plan(hours, [10000, 10000, 10000], [0, 0, 0], 100, 95)
    c = {s.key: s for s in scenarios}["cautious"]
    # buys: 5000, 9000, 0 ; surplus: 0, 0, 5000
    assert [h.buy_cautious_mw for h in plan] == [5000, 9000, 0]
    assert c.buy_total_mwh == 14000
    assert c.avg_buy_mw == pytest.approx(14000 / 3)
    assert (c.peak_buy_mw, c.peak_buy_hour) == (9000, "01:00")
    assert c.hours_with_buy == 2 and c.hours_with_surplus == 1 and c.surplus_wind_mwh == 5000
    # surplus in hour 02:00 must not reduce the purchases in the other hours
    assert c.buy_total_mwh == 5000 + 9000


def test_hours_without_forecast_are_unplanned_not_guessed():
    hours = [fh("00:00", 8000, 7000, 5000), fh("01:00", None)]
    plan, scenarios = build_plan(hours, [10000, 10000], [0, 0], 100, 95)
    assert plan[1].planned is False
    assert plan[1].buy_cautious_mw is None and plan[1].wind_cautious_mw is None
    c = {s.key: s for s in scenarios}["cautious"]
    assert c.buy_total_mwh == 5000  # the unplanned hour contributes nothing - it is reported separately
    assert c.avg_buy_mw == 5000  # averaged over planned hours only


def test_zero_wind_share_means_buy_everything_not_contracted():
    plan, scenarios = build_plan([fh("00:00", 12000, 10000, 8000)], [7000], [2000], 0, 95)
    assert plan[0].buy_cautious_mw == 5000
    assert {s.key: s for s in scenarios}["cautious"].wind_total_mwh == 0


def test_zero_demand_means_no_purchase_and_undefined_cover():
    _, scenarios = build_plan([fh("00:00", 12000, 10000, 8000)], [0], [0], 100, 95)
    c = {s.key: s for s in scenarios}["cautious"]
    assert c.buy_total_mwh == 0 and c.wind_cover_pct is None


def test_length_mismatch_rejected():
    with pytest.raises(ValueError):
        build_plan([fh("00:00", 1, 1, 1)], [1, 2], [0], 100, 95)


# ------------------------------------------------------------------ API


def calibrate(api):
    r = api.post("/api/calibrations", json={"start_date": "2025-10-01", "end_date": "2025-12-31"})
    assert r.status_code == 202, r.text


def plan(api, **body):
    payload = {"cutoff": "17:00", "percentile": 95, **body}
    return api.post("/api/decisions/2026-01-15/procurement", json=payload)


def test_api_requires_demand_and_never_invents_it(api):
    calibrate(api)
    assert plan(api).status_code == 422  # no demand given -> nothing is calculated
    both = plan(api, demand_mw=100, demand_by_hour_mw=[100] * 24)
    assert both.status_code == 422
    assert both.json()["error"]["code"] == "VALIDATION_ERROR"


def test_api_flat_demand_matches_decision_numbers(api):
    calibrate(api)
    dec = api.get("/api/decisions/2026-01-15", params={"percentile": 95}).json()
    r = plan(api, demand_mw=15000)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["recommended_basis"] == "cautious" and p["hours_planned"] == 24 and p["hours_unplanned"] == 0
    assert p["demand_total_mwh"] == 15000 * 24
    for hp, hd in zip(p["hours"], dec["hours"], strict=True):
        assert hp["wind_forecast_mw"] == pytest.approx(hd["forecast_mw"])
        assert hp["wind_cautious_mw"] == pytest.approx(hd["conservative_mw"])
        assert hp["buy_cautious_mw"] == pytest.approx(max(0.0, 15000 - hd["conservative_mw"]))
        assert hp["buy_expected_mw"] == pytest.approx(max(0.0, 15000 - hd["bias_adjusted_mw"]))
    by = {s["key"]: s for s in p["scenarios"]}
    assert by["cautious"]["buy_total_mwh"] == pytest.approx(sum(h["buy_cautious_mw"] for h in p["hours"]))
    assert p["risk_cover_mwh"] == pytest.approx(by["cautious"]["buy_total_mwh"] - by["expected"]["buy_total_mwh"])
    # the forecast is over-forecasting in the fake world (BIAS > 0), so the safer plans buy more
    assert by["cautious"]["buy_total_mwh"] >= by["expected"]["buy_total_mwh"] >= by["forecast"]["buy_total_mwh"]
    assert BIAS > 0
    assert any("max(0, demand" in a for a in p["assumptions"])


def test_api_wind_share_and_contracts_scale_the_purchase(api):
    calibrate(api)
    full = plan(api, demand_mw=20000).json()
    half = plan(api, demand_mw=20000, wind_share_pct=50).json()
    contracted = plan(api, demand_mw=20000, contracted_mw=3000).json()
    cb = lambda p: next(s for s in p["scenarios"] if s["key"] == "cautious")["buy_total_mwh"]  # noqa: E731
    assert cb(half) > cb(full)  # less wind access -> buy more
    assert cb(contracted) < cb(full)  # existing contracts -> buy less
    # exact: per hour, buy = max(0, demand - contracted - wind), never negative
    expected = sum(max(0.0, 20000 - 3000 - h["wind_cautious_mw"]) for h in full["hours"])
    assert cb(contracted) == pytest.approx(expected)
    assert all(h["buy_cautious_mw"] >= 0 for h in contracted["hours"])
    assert half["wind_share_pct"] == 50
    first = half["hours"][0]
    base_wind = full["hours"][0]["wind_forecast_mw"]
    assert first["wind_forecast_mw"] == pytest.approx(base_wind * 0.5)


def test_api_hourly_demand_profile(api):
    calibrate(api)
    profile = [10000.0] * 12 + [18000.0] * 12
    p = plan(api, demand_by_hour_mw=profile).json()
    assert [h["demand_mw"] for h in p["hours"]] == profile
    assert p["demand_total_mwh"] == sum(profile)
    wrong = plan(api, demand_by_hour_mw=[1.0] * 23)
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "INVALID_PROFILE_LENGTH"


@pytest.mark.parametrize(
    "body",
    [
        {"demand_mw": -5},
        {"demand_mw": 1e12},
        {"demand_mw": 100, "wind_share_pct": 120},
        {"demand_mw": 100, "wind_share_pct": -1},
        {"demand_mw": 100, "contracted_mw": -1},
        {"demand_by_hour_mw": [100.0] * 23 + [-1.0]},
    ],
)
def test_api_rejects_invalid_numbers(api, body):
    calibrate(api)
    assert plan(api, **body).status_code == 422


def test_api_flags_no_purchase_needed_and_suggests_wind_share(api):
    calibrate(api)
    p = plan(api, demand_mw=500).json()  # tiny demand next to national wind
    assert all(h["buy_cautious_mw"] == 0 for h in p["hours"])
    w = [x for x in p["warnings"] if x["code"] == "NO_PURCHASE_NEEDED"]
    assert w and "wind share" in w[0]["message"]


def test_api_reports_unplanned_hours_when_forecast_incomplete(api, fake):
    calibrate(api)
    fake.drop_forecast = lambda pub, start: start == datetime(2026, 1, 15, 5, tzinfo=UTC)
    p = plan(api, demand_mw=15000).json()
    assert p["hours_unplanned"] == 1 and p["hours_planned"] == 23
    gap = next(h for h in p["hours"] if h["local_label"] == "05:00")
    assert gap["planned"] is False and gap["buy_cautious_mw"] is None
    assert p["demand_total_mwh"] == 15000 * 23  # only planned hours are totalled
    assert any(w["code"] == "HOURS_NOT_PLANNED" for w in p["warnings"])


def test_api_needs_active_calibration_and_respects_window(api):
    r = plan(api, demand_mw=100)
    assert r.status_code == 404 and r.json()["error"]["code"] == "NO_ACTIVE_CALIBRATION"
    calibrate(api)
    out = api.post("/api/decisions/2026-02-02/procurement", json={"demand_mw": 100})
    assert out.status_code == 422 and out.json()["error"]["code"] == "DELIVERY_DATE_OUT_OF_RANGE"


def test_api_plan_uses_forecast_available_at_cutoff_only(api, fake):
    calibrate(api)
    fake.requests.clear()
    p = plan(api, demand_mw=15000, cutoff="17:00").json()
    assert p["forecast"]["vintage_publish_time_utc"] == "2026-01-14T14:30:00Z"
    for req in fake.requests:
        if "WINDFOR" in req.url.path:
            to = datetime.fromisoformat(req.url.params["publishDateTimeTo"].replace("Z", "+00:00"))
            assert to <= datetime(2026, 1, 14, 17, tzinfo=UTC)
    assert base(datetime(2026, 1, 15, tzinfo=UTC)) > 0
