from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.core.errors import FutureDataLeakageError
from app.services.forecast_selection import (
    POLICY_LATEST_ONLY,
    ForecastSelection,
    _assert_no_future_vintage,
    select_forecast,
)


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def vintage(publish, start_hours: list[datetime], value: float) -> list[dict]:
    return [{"publish_time": publish, "start_time": h, "generation_mw": value} for h in start_hours]


def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["publish_time"] = pd.to_datetime(df["publish_time"], utc=True)
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    return df


DAY = [utc(2026, 1, 15, h) for h in range(24)]
CUTOFF = utc(2026, 1, 14, 17, 0)


def test_selects_latest_eligible_vintage_at_or_before_cutoff():
    df = frame(
        vintage(utc(2026, 1, 14, 11, 30), DAY, 100.0)
        + vintage(utc(2026, 1, 14, 15, 30), DAY, 200.0)
        + vintage(utc(2026, 1, 14, 18, 30), DAY, 300.0)  # after cutoff
    )
    sel = select_forecast(df, DAY, CUTOFF)
    assert sel.vintage_publish_time == utc(2026, 1, 14, 15, 30)
    assert set(sel.hour_values.values()) == {200.0}
    assert sel.is_complete and not sel.fallback_used


def test_forecast_published_exactly_at_cutoff_is_eligible():
    df = frame(vintage(CUTOFF, DAY, 111.0) + vintage(CUTOFF + timedelta(seconds=1), DAY, 222.0))
    sel = select_forecast(df, DAY, CUTOFF)
    assert sel.vintage_publish_time == CUTOFF
    assert set(sel.hour_values.values()) == {111.0}


def test_forecasts_after_cutoff_are_excluded_entirely():
    df = frame(vintage(utc(2026, 1, 14, 17, 30), DAY, 300.0) + vintage(utc(2026, 1, 15, 2, 30), DAY, 400.0))
    sel = select_forecast(df, DAY, CUTOFF)
    assert not sel.has_forecast
    assert sel.hour_values == {}
    assert sel.missing_hours == DAY  # nothing is invented
    assert sel.excluded_future_vintage_count == 2


def test_missing_hours_reported_and_never_filled_from_later_forecast():
    present = DAY[:20]  # 20:00-23:00 missing
    df = frame(vintage(utc(2026, 1, 14, 15, 30), present, 200.0) + vintage(utc(2026, 1, 14, 22, 30), DAY, 999.0))
    sel = select_forecast(df, DAY, CUTOFF)
    # No eligible vintage is complete -> use the partial one and report the gap
    assert sel.vintage_publish_time == utc(2026, 1, 14, 15, 30)
    assert sel.missing_hours == DAY[20:]
    assert 999.0 not in sel.hour_values.values()
    assert not sel.is_complete


def test_falls_back_to_earlier_complete_vintage_with_audit_flag():
    df = frame(vintage(utc(2026, 1, 14, 11, 30), DAY, 100.0) + vintage(utc(2026, 1, 14, 15, 30), DAY[:10], 200.0))
    sel = select_forecast(df, DAY, CUTOFF)
    assert sel.vintage_publish_time == utc(2026, 1, 14, 11, 30)
    assert sel.fallback_used and "missing" in (sel.fallback_reason or "")
    assert sel.latest_eligible_publish_time == utc(2026, 1, 14, 15, 30)
    # Single vintage only: never a per-hour mix of 100 and 200
    assert set(sel.hour_values.values()) == {100.0}


def test_latest_only_policy_does_not_fall_back():
    df = frame(vintage(utc(2026, 1, 14, 11, 30), DAY, 100.0) + vintage(utc(2026, 1, 14, 15, 30), DAY[:10], 200.0))
    sel = select_forecast(df, DAY, CUTOFF, policy=POLICY_LATEST_ONLY)
    assert sel.vintage_publish_time == utc(2026, 1, 14, 15, 30)
    assert len(sel.missing_hours) == 14 and not sel.fallback_used


def test_matching_is_by_delivery_time_not_row_order():
    rows = vintage(utc(2026, 1, 14, 15, 30), DAY, 0.0)
    for r in rows:
        r["generation_mw"] = float(r["start_time"].hour)  # value encodes the hour
    rows.reverse()  # scramble row order
    sel = select_forecast(frame(rows), DAY, CUTOFF)
    for h, v in sel.hour_values.items():
        assert v == float(h.hour)


def test_stale_vintages_beyond_max_age_ignored():
    df = frame(vintage(utc(2026, 1, 10, 11, 30), DAY, 5.0))
    sel = select_forecast(df, DAY, CUTOFF)
    assert not sel.has_forecast


def test_empty_frame():
    df = frame(vintage(utc(2026, 1, 14, 11, 30), DAY, 1.0)).iloc[0:0]
    sel = select_forecast(df, DAY, CUTOFF)
    assert not sel.has_forecast and sel.missing_hours == DAY


def test_naive_cutoff_rejected():
    with pytest.raises(ValueError):
        select_forecast(frame(vintage(utc(2026, 1, 14, 11, 30), DAY, 1.0)), DAY, datetime(2026, 1, 14, 17))


def test_leakage_guard_raises_if_future_vintage_somehow_selected():
    sel = ForecastSelection(cutoff_utc=CUTOFF, required_hours=DAY, policy="x", vintage_publish_time=CUTOFF + timedelta(hours=1))
    with pytest.raises(FutureDataLeakageError):
        _assert_no_future_vintage(sel)
