from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
import pytest

from app.core.timeutils import (
    local_day_bounds_utc,
    local_day_hours_utc,
    parse_hhmm,
    parse_utc,
    previous_day_cutoff_utc,
    uk_date_of,
    uk_label,
)
from app.services.data_normalization import (
    actuals_to_frame,
    aggregate_actuals_hourly,
    detect_granularity_minutes,
    forecasts_to_frame,
)
from app.services.elexon_client import ActualRow, ForecastRow


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def arow(start: datetime, mw: float, publish=None) -> ActualRow:
    return ActualRow(start, start.date(), 1, publish, mw)


# --------------------------------------------------------------------- aggregation


def test_two_half_hours_aggregate_to_hourly_mean_not_sum():
    df = actuals_to_frame([arow(utc(2026, 1, 15, 10, 0), 1000.0), arow(utc(2026, 1, 15, 10, 30), 2000.0)])
    hourly = aggregate_actuals_hourly(df)
    assert len(hourly.complete) == 1
    assert hourly.complete["actual_mw"].iloc[0] == pytest.approx(1500.0)  # mean, not 3000
    assert hourly.incomplete_hours == []


def test_hour_with_single_half_hour_is_incomplete_and_excluded():
    df = actuals_to_frame(
        [arow(utc(2026, 1, 15, 10, 0), 1000.0), arow(utc(2026, 1, 15, 11, 0), 1.0), arow(utc(2026, 1, 15, 11, 30), 3.0)]
    )
    hourly = aggregate_actuals_hourly(df)
    assert list(hourly.complete["hour_start"].dt.hour) == [11]
    assert hourly.incomplete_hours == [utc(2026, 1, 15, 10)]


def test_duplicate_half_hour_does_not_create_a_complete_hour():
    rows = [arow(utc(2026, 1, 15, 10, 0), 1.0, utc(2026, 1, 15, 10, 30)), arow(utc(2026, 1, 15, 10, 0), 5.0, utc(2026, 1, 15, 11, 5))]
    df = actuals_to_frame(rows)
    assert len(df) == 1 and df["generation_mw"].iloc[0] == 5.0  # latest publication wins
    assert aggregate_actuals_hourly(df).complete.empty


def test_actual_availability_is_not_before_interval_end():
    # publish_time earlier than the interval end would be implausible; availability must not precede it
    df = actuals_to_frame(
        [arow(utc(2026, 1, 15, 10, 0), 1.0, utc(2026, 1, 15, 9, 0)), arow(utc(2026, 1, 15, 10, 30), 1.0, utc(2026, 1, 15, 11, 0))]
    )
    avail = aggregate_actuals_hourly(df).complete["available_at"].iloc[0]
    assert avail == pd.Timestamp(utc(2026, 1, 15, 11, 0))
    df2 = actuals_to_frame([arow(utc(2026, 1, 15, 10, 0), 1.0), arow(utc(2026, 1, 15, 10, 30), 1.0)])  # no publish time
    assert aggregate_actuals_hourly(df2).complete["available_at"].iloc[0] == pd.Timestamp(utc(2026, 1, 15, 11, 0))


def test_empty_actuals():
    h = aggregate_actuals_hourly(actuals_to_frame([]))
    assert h.complete.empty and h.incomplete_hours == []


def test_forecast_frame_dedupes_and_sorts():
    rows = [
        ForecastRow(utc(2026, 1, 14, 15, 30), utc(2026, 1, 15, 1), 2.0),
        ForecastRow(utc(2026, 1, 14, 15, 30), utc(2026, 1, 15, 0), 1.0),
        ForecastRow(utc(2026, 1, 14, 15, 30), utc(2026, 1, 15, 0), 1.5),  # duplicate key
    ]
    df = forecasts_to_frame(rows)
    assert len(df) == 2
    assert df["start_time"].is_monotonic_increasing


def test_granularity_detection():
    s = pd.Series(pd.date_range("2026-01-01", periods=5, freq="60min", tz="UTC"))
    assert detect_granularity_minutes(s) == 60.0
    s2 = pd.Series(pd.date_range("2026-01-01", periods=5, freq="30min", tz="UTC"))
    assert detect_granularity_minutes(s2) == 30.0
    assert detect_granularity_minutes(pd.Series(pd.date_range("2026-01-01", periods=1, tz="UTC"))) is None


# --------------------------------------------------------------------- UK-local time


def test_uk_winter_day_equals_utc_day():
    start, end = local_day_bounds_utc(date(2026, 1, 15))
    assert start == utc(2026, 1, 15, 0) and end == utc(2026, 1, 16, 0)
    assert len(local_day_hours_utc(date(2026, 1, 15))) == 24


def test_uk_summer_delivery_day_starts_in_previous_utc_day():
    hours = local_day_hours_utc(date(2025, 7, 1))
    assert hours[0] == utc(2025, 6, 30, 23)  # 00:00 BST
    assert hours[-1] == utc(2025, 7, 1, 22)
    assert uk_date_of(hours[0]) == date(2025, 7, 1)
    assert uk_label(hours[0]) == "00:00"


def test_dst_transition_days_have_23_and_25_hours():
    assert len(local_day_hours_utc(date(2025, 3, 30))) == 23
    assert len(local_day_hours_utc(date(2025, 10, 26))) == 25


def test_local_hours_are_hour_aligned_utc_instants():
    for d in (date(2025, 3, 30), date(2025, 10, 26), date(2026, 1, 15)):
        for h in local_day_hours_utc(d):
            assert h.minute == 0 and h.second == 0


def test_cutoff_is_previous_uk_day_at_local_time():
    # Winter: 17:00 GMT == 17:00 UTC
    assert previous_day_cutoff_utc(date(2026, 1, 15), time(17, 0)) == utc(2026, 1, 14, 17)
    # Summer: 17:00 BST == 16:00 UTC
    assert previous_day_cutoff_utc(date(2025, 7, 2), time(17, 0)) == utc(2025, 7, 1, 16)


def test_utc_date_differs_from_uk_date_around_midnight_in_bst():
    ts = utc(2025, 7, 1, 23, 30)  # 00:30 BST on 2 July
    assert ts.date() == date(2025, 7, 1)
    assert uk_date_of(ts) == date(2025, 7, 2)


def test_parse_helpers():
    assert parse_utc("2026-01-14T15:30:00Z") == utc(2026, 1, 14, 15, 30)
    assert parse_utc("2026-01-14T16:30:00+01:00") == utc(2026, 1, 14, 15, 30)
    assert parse_utc("2026-01-14T15:30:00") == utc(2026, 1, 14, 15, 30)
    assert parse_hhmm("07:05") == time(7, 5)
    for bad in ("7:05", "24:00", "12:60", "noon"):
        with pytest.raises(ValueError):
            parse_hhmm(bad)


def test_naive_datetime_rejected_for_storage_conversion():
    from app.core.timeutils import ensure_utc

    with pytest.raises(ValueError):
        ensure_utc(datetime(2026, 1, 1))
    assert ensure_utc(datetime(2026, 1, 1, 12, tzinfo=UTC) + timedelta(0)).tzinfo is not None
