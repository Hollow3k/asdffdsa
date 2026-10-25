from datetime import UTC, date, datetime

import httpx
import pytest

from app.core.errors import (
    ElexonBadRequestError,
    ElexonDataError,
    ElexonRateLimitError,
    ElexonUnavailableError,
)
from app.services.elexon_client import ElexonClient


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def make(handler, retries=2, sleeps=None) -> ElexonClient:
    return ElexonClient(
        "https://elexon.test/api/v1",
        timeout=1,
        max_retries=retries,
        backoff_base=1.0,
        backoff_max=10.0,
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        jitter=lambda _d: 0.0,
    )


GOOD_F = {"dataset": "WINDFOR", "publishTime": "2026-01-14T15:30:00Z", "startTime": "2026-01-15T00:00:00Z", "generation": 12000}
GOOD_A = {
    "dataset": "FUELHH",
    "publishTime": "2026-01-15T00:30:00Z",
    "startTime": "2026-01-15T00:00:00Z",
    "settlementDate": "2026-01-15",
    "settlementPeriod": 1,
    "fuelType": "WIND",
    "generation": 9000,
}


def fetch_f(c):
    return c.fetch_wind_forecasts(utc(2026, 1, 14, 0), utc(2026, 1, 14, 17))


def test_parses_documented_shapes_and_sends_documented_params():
    seen = {}

    def handler(req):
        seen[req.url.path] = dict(req.url.params)
        return httpx.Response(200, json=[GOOD_F] if "WINDFOR" in req.url.path else [GOOD_A])

    c = make(handler)
    f = fetch_f(c)
    a = c.fetch_wind_actuals(date(2026, 1, 15), date(2026, 1, 15))
    assert f.rows[0].generation_mw == 12000.0 and f.rows[0].publish_time == utc(2026, 1, 14, 15, 30)
    assert f.rows[0].start_time == utc(2026, 1, 15, 0)
    assert a.rows[0].settlement_period == 1 and a.rows[0].settlement_date == date(2026, 1, 15)
    wind = seen["/api/v1/datasets/WINDFOR/stream"]
    assert wind["publishDateTimeFrom"] == "2026-01-14T00:00:00Z" and wind["publishDateTimeTo"] == "2026-01-14T17:00:00Z"
    assert "settlementDateFrom" not in wind
    fuel = seen["/api/v1/datasets/FUELHH/stream"]
    assert fuel["fuelType"] == "WIND" and fuel["settlementDateFrom"] == "2026-01-15"
    assert "publishDateTimeFrom" not in fuel  # settlement and publish filters must not be combined


def test_response_dominated_by_other_fuels_is_refused():
    ccgt = {**GOOD_A, "fuelType": "CCGT", "generation": 99999}
    c = make(lambda r: httpx.Response(200, json=[GOOD_A] + [ccgt] * 100))
    # A response dominated by other fuels is refused rather than silently filtered.
    with pytest.raises(ElexonDataError):
        c.fetch_wind_actuals(date(2026, 1, 15), date(2026, 1, 15))


def test_few_non_wind_rows_are_dropped_and_counted():
    ok = [{**GOOD_A, "settlementPeriod": i, "startTime": f"2026-01-15T{i // 2:02d}:{30 * (i % 2):02d}:00Z"} for i in range(40)]
    other = {**GOOD_A, "fuelType": "CCGT", "generation": 99999}
    c = make(lambda r: httpx.Response(200, json=ok + [other]))
    res = c.fetch_wind_actuals(date(2026, 1, 15), date(2026, 1, 15))
    assert len(res.rows) == 40 and res.dropped_other_fuel == 1
    assert all(r.generation_mw != 99999 for r in res.rows)


def test_timeout_is_retried_with_backoff_then_raises():
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(ElexonUnavailableError) as ei:
        fetch_f(make(handler, retries=3, sleeps=sleeps))
    assert calls["n"] == 4  # 1 + 3 retries: bounded
    assert sleeps == [1.0, 2.0, 4.0]  # exponential backoff
    assert "timed out" in ei.value.message


def test_transient_5xx_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 3 else httpx.Response(200, json=[GOOD_F])

    res = fetch_f(make(handler, retries=3))
    assert len(res.rows) == 1 and calls["n"] == 3


def test_rate_limit_honours_retry_after_and_raises_when_persistent():
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    with pytest.raises(ElexonRateLimitError) as ei:
        fetch_f(make(handler, retries=2, sleeps=sleeps))
    assert calls["n"] == 3
    assert sleeps[0] == 7.0  # Retry-After longer than the base backoff is respected (capped at max)
    assert ei.value.code == "ELEXON_RATE_LIMITED"


def test_rate_limit_then_success():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429) if calls["n"] == 1 else httpx.Response(200, json=[GOOD_F])

    assert len(fetch_f(make(handler)).rows) == 1


def test_client_error_is_not_retried():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"errors": {"": ["The Settlement Date fields cannot be set when a Publish Date field is set."]}})

    with pytest.raises(ElexonBadRequestError) as ei:
        fetch_f(make(handler, retries=3))
    assert calls["n"] == 1
    assert "Settlement Date fields cannot be set" in ei.value.message


def test_empty_response_is_returned_as_empty_not_fabricated():
    res = fetch_f(make(lambda r: httpx.Response(200, json=[])))
    assert res.empty and res.rows == []


def test_invalid_json_body_raises_data_error():
    with pytest.raises(ElexonDataError):
        fetch_f(make(lambda r: httpx.Response(200, content=b"<html>oops</html>"), retries=1))


def test_unexpected_shape_raises_data_error():
    with pytest.raises(ElexonDataError):
        fetch_f(make(lambda r: httpx.Response(200, json={"data": []})))


def test_mostly_malformed_rows_rejected_but_isolated_bad_rows_dropped():
    bad = {"dataset": "WINDFOR", "publishTime": "garbage", "startTime": "2026-01-15T00:00:00Z", "generation": 1}
    with pytest.raises(ElexonDataError):
        fetch_f(make(lambda r: httpx.Response(200, json=[bad, bad, GOOD_F])))
    many_good = [{**GOOD_F, "startTime": f"2026-01-15T{h:02d}:00:00Z"} for h in range(24)]
    nulls = [{**GOOD_F, "generation": None}]
    res2 = fetch_f(make(lambda r: httpx.Response(200, json=many_good * 5 + nulls)))
    assert res2.dropped_malformed == 1 and len(res2.rows) == 120


def test_non_finite_and_string_generation_are_malformed():
    rows = [{**GOOD_F, "startTime": f"2026-01-15T{h:02d}:00:00Z"} for h in range(24)] * 3
    rows.append({**GOOD_F, "generation": "12000"})
    res = fetch_f(make(lambda r: httpx.Response(200, json=rows)))
    assert res.dropped_malformed == 1


def test_connection_error_maps_to_unavailable():
    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ElexonUnavailableError):
        fetch_f(make(handler, retries=1))
