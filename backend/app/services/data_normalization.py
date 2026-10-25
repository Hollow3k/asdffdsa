"""Normalisation of raw Elexon rows into analysis-ready frames. Pure functions, no I/O.

Conventions
-----------
* All timestamps are timezone-aware UTC.
* WINDFOR is hourly (verified against the live API; ``detect_granularity_minutes`` re-checks at
  runtime). FUELHH is half-hourly.
* Half-hourly MW observations are *averaged* into an hourly mean MW (never summed - they are
  power, not energy). An hour is only usable when both half-hours are present.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from app.services.elexon_client import ActualRow, ForecastRow

FORECAST_COLUMNS = ["publish_time", "start_time", "generation_mw"]
ACTUAL_COLUMNS = ["start_time", "settlement_date", "settlement_period", "publish_time", "generation_mw"]
HOURLY_ACTUAL_COLUMNS = ["hour_start", "actual_mw", "n_obs", "available_at"]
HALF_HOURS_PER_HOUR = 2


def _empty_forecasts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "publish_time": pd.Series([], dtype="datetime64[ns, UTC]"),
            "start_time": pd.Series([], dtype="datetime64[ns, UTC]"),
            "generation_mw": pd.Series([], dtype="float64"),
        }
    )


def forecasts_to_frame(rows: Iterable[ForecastRow]) -> pd.DataFrame:
    """Forecast vintages as a frame; duplicate (publish_time, start_time) pairs are collapsed."""
    data = [(r.publish_time, r.start_time, r.generation_mw) for r in rows]
    if not data:
        return _empty_forecasts()
    df = pd.DataFrame(data, columns=FORECAST_COLUMNS)
    df["publish_time"] = pd.to_datetime(df["publish_time"], utc=True)
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["generation_mw"] = df["generation_mw"].astype("float64")
    df = df.drop_duplicates(subset=["publish_time", "start_time"], keep="last")
    return df.sort_values(["publish_time", "start_time"]).reset_index(drop=True)


def actuals_to_frame(rows: Iterable[ActualRow]) -> pd.DataFrame:
    """Half-hourly actuals; duplicate ``start_time`` rows keep the most recently published."""
    data = [
        (r.start_time, r.settlement_date, r.settlement_period, r.publish_time, r.generation_mw) for r in rows
    ]
    if not data:
        return pd.DataFrame(
            {
                "start_time": pd.Series([], dtype="datetime64[ns, UTC]"),
                "settlement_date": pd.Series([], dtype="object"),
                "settlement_period": pd.Series([], dtype="int64"),
                "publish_time": pd.Series([], dtype="datetime64[ns, UTC]"),
                "generation_mw": pd.Series([], dtype="float64"),
            }
        )
    df = pd.DataFrame(data, columns=ACTUAL_COLUMNS)
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["publish_time"] = pd.to_datetime(df["publish_time"], utc=True)
    df["generation_mw"] = df["generation_mw"].astype("float64")
    df = df.sort_values(["start_time", "publish_time"], na_position="first")
    df = df.drop_duplicates(subset=["start_time"], keep="last")
    return df.reset_index(drop=True)


@dataclass
class HourlyActuals:
    complete: pd.DataFrame  # columns HOURLY_ACTUAL_COLUMNS, only hours with both half-hours
    incomplete_hours: list[datetime] = field(default_factory=list)  # hours seen but not complete


def aggregate_actuals_hourly(half_hourly: pd.DataFrame) -> HourlyActuals:
    """Aggregate half-hourly MW into hourly *mean* MW on UTC hour boundaries.

    UK offsets from UTC are whole hours, so UTC hour boundaries coincide with UK-local hour
    boundaries, including on DST transition days.

    ``available_at`` is the conservative moment the hourly value could have been known: the later
    of the interval end and the latest publication time of its constituent half-hours.
    """
    if half_hourly.empty:
        return HourlyActuals(
            complete=pd.DataFrame(
                {
                    "hour_start": pd.Series([], dtype="datetime64[ns, UTC]"),
                    "actual_mw": pd.Series([], dtype="float64"),
                    "n_obs": pd.Series([], dtype="int64"),
                    "available_at": pd.Series([], dtype="datetime64[ns, UTC]"),
                }
            )
        )
    df = half_hourly.copy()
    df["hour_start"] = df["start_time"].dt.floor("h")
    df["interval_end"] = df["start_time"] + pd.Timedelta(minutes=30)
    # Publication time may be missing; fall back to the end of the half-hour.
    df["known_at"] = df["publish_time"].where(df["publish_time"].notna(), df["interval_end"])
    df["known_at"] = df[["known_at", "interval_end"]].max(axis=1)
    grouped = df.groupby("hour_start", sort=True).agg(
        actual_mw=("generation_mw", "mean"),
        n_obs=("generation_mw", "count"),
        available_at=("known_at", "max"),
    )
    grouped = grouped.reset_index()
    full = grouped["n_obs"] == HALF_HOURS_PER_HOUR
    incomplete = [ts.to_pydatetime() for ts in grouped.loc[~full, "hour_start"]]
    complete = grouped.loc[full].reset_index(drop=True)
    return HourlyActuals(complete=complete[HOURLY_ACTUAL_COLUMNS], incomplete_hours=incomplete)


def detect_granularity_minutes(timestamps: pd.Series) -> float | None:
    """Median spacing between distinct consecutive timestamps, in minutes (None if < 2)."""
    uniq = pd.Series(pd.to_datetime(timestamps, utc=True).unique()).sort_values()
    if len(uniq) < 2:
        return None
    diffs = uniq.diff().dropna().dt.total_seconds() / 60.0
    return float(diffs.median())


def vintage_summary(forecasts: pd.DataFrame) -> dict:
    """Coverage statistics for data-quality reporting."""
    if forecasts.empty:
        return {"vintages": 0, "rows": 0, "first_publish": None, "last_publish": None, "max_gap_hours": None}
    publish = pd.Series(forecasts["publish_time"].unique()).sort_values()
    gaps = publish.diff().dropna().dt.total_seconds() / 3600.0
    return {
        "vintages": int(len(publish)),
        "rows": int(len(forecasts)),
        "first_publish": publish.iloc[0].to_pydatetime(),
        "last_publish": publish.iloc[-1].to_pydatetime(),
        "max_gap_hours": float(gaps.max()) if len(gaps) else None,
    }
