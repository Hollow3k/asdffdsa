"""Historical calibration: reconstruct what the forecast looked like at each historical decision
cutoff, align it with outturn, and compute error statistics.

For every UK delivery date ``d`` in the calibration range:

* decision cutoff = ``cutoff_time`` (UK time) on day ``d-1``;
* forecast = the vintage selected by :func:`forecast_selection.select_forecast` at that cutoff
  (never a later revision);
* actual = hourly mean of the two half-hourly FUELHH WIND observations in each UK-local hour;
* pairs are matched on delivery timestamp (not row order) and only complete pairs are used.

This module is pure (no I/O) so it can be tested deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from app.core.errors import ValidationFailed
from app.core.timeutils import (
    local_day_hours_utc,
    previous_day_cutoff_utc,
    to_uk,
    utc_iso,
)
from app.services.data_normalization import HourlyActuals, detect_granularity_minutes, vintage_summary
from app.services.forecast_selection import POLICY_LATEST_COMPLETE, select_forecast
from app.services.metrics import compute_error_metrics

OBSERVATION_COLUMNS = [
    "delivery_start",
    "delivery_date",
    "hour_local",
    "forecast_mw",
    "actual_mw",
    "error_mw",
    "forecast_publish_time",
    "decision_cutoff",
    "actual_available_at",
]


def warning(code: str, severity: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, **extra}


@dataclass
class CalibrationDataset:
    observations: pd.DataFrame
    quality: dict[str, Any]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def validate_calibration_range(
    start: date, end: date, *, today: date, max_days: int, cutoff_time: time | None = None
) -> None:
    """Reject ranges that are inverted, too long, or not yet fully observable."""
    if end < start:
        raise ValidationFailed("Calibration end date must not be before the start date",
                               details={"field": "end_date"})
    span = (end - start).days + 1
    if span > max_days:
        raise ValidationFailed(
            f"Calibration range of {span} days exceeds the maximum of {max_days} days",
            details={"field": "end_date", "max_days": max_days},
        )
    # The last delivery day must be over, with margin for FUELHH publication.
    if end >= today:
        raise ValidationFailed(
            f"Calibration end date must be before today ({today.isoformat()}, UK) so that actual "
            "generation for the whole day has been published",
            details={"field": "end_date", "latest_allowed": (today - timedelta(days=1)).isoformat()},
        )


def build_calibration_dataset(
    vintages: pd.DataFrame,
    hourly_actuals: HourlyActuals,
    start: date,
    end: date,
    cutoff_time: time,
    *,
    policy: str = POLICY_LATEST_COMPLETE,
    low_sample_pairs: int = 500,
    fetch_stats: dict[str, Any] | None = None,
) -> CalibrationDataset:
    actual_lookup: dict[datetime, tuple[float, datetime]] = {
        ts.to_pydatetime(): (float(mw), av.to_pydatetime())
        for ts, mw, av in zip(
            hourly_actuals.complete["hour_start"],
            hourly_actuals.complete["actual_mw"],
            hourly_actuals.complete["available_at"],
            strict=True,
        )
    }
    incomplete_actual = set(hourly_actuals.incomplete_hours)

    rows: list[dict[str, Any]] = []
    expected_hours = 0
    missing_forecast = 0
    missing_actual = 0
    incomplete_actual_hours = 0
    unmatched_union = 0
    days_fallback: list[str] = []
    days_incomplete: list[str] = []
    days_no_forecast: list[str] = []
    days_with_pairs = 0

    day = start
    n_days = 0
    while day <= end:
        n_days += 1
        hours = local_day_hours_utc(day)
        cutoff = previous_day_cutoff_utc(day, cutoff_time)
        sel = select_forecast(vintages, hours, cutoff, policy=policy)
        expected_hours += len(hours)
        if not sel.has_forecast:
            days_no_forecast.append(day.isoformat())
        elif sel.missing_hours:
            days_incomplete.append(day.isoformat())
        if sel.fallback_used:
            days_fallback.append(day.isoformat())

        day_pairs = 0
        for h in hours:
            f = sel.hour_values.get(h)
            a = actual_lookup.get(h)
            no_f = f is None
            no_a = a is None
            if no_f:
                missing_forecast += 1
            if no_a:
                missing_actual += 1
                if h in incomplete_actual:
                    incomplete_actual_hours += 1
            if f is None or a is None or sel.vintage_publish_time is None:
                unmatched_union += 1
                continue
            actual_mw, available_at = a
            rows.append(
                {
                    "delivery_start": h,
                    "delivery_date": day,
                    "hour_local": to_uk(h).hour,
                    "forecast_mw": f,
                    "actual_mw": actual_mw,
                    "error_mw": f - actual_mw,
                    "forecast_publish_time": sel.vintage_publish_time,
                    "decision_cutoff": cutoff,
                    "actual_available_at": available_at,
                }
            )
            day_pairs += 1
        if day_pairs:
            days_with_pairs += 1
        day += timedelta(days=1)

    obs = pd.DataFrame(rows, columns=OBSERVATION_COLUMNS)
    matched = len(obs)

    vs = vintage_summary(vintages)
    forecast_gran = detect_granularity_minutes(vintages["start_time"]) if not vintages.empty else None

    quality: dict[str, Any] = {
        "delivery_days_requested": n_days,
        "delivery_days_with_pairs": days_with_pairs,
        "expected_hours": expected_hours,
        "matched_pairs": matched,
        "unmatched_hours": unmatched_union,
        "hours_missing_forecast": missing_forecast,
        "hours_missing_actual": missing_actual,
        "hours_incomplete_actual": incomplete_actual_hours,
        "days_using_fallback_vintage": len(days_fallback),
        "days_with_incomplete_forecast": len(days_incomplete),
        "days_without_forecast": len(days_no_forecast),
        "vintages_in_pool": vs["vintages"],
        "first_vintage_publish": utc_iso(vs["first_publish"]) if vs["first_publish"] else None,
        "last_vintage_publish": utc_iso(vs["last_publish"]) if vs["last_publish"] else None,
        "max_vintage_gap_hours": vs["max_gap_hours"],
        "forecast_granularity_minutes": forecast_gran,
        "actual_granularity_minutes": 30,
        "api": fetch_stats or {},
    }

    warnings: list[dict[str, Any]] = []
    if matched == 0:
        warnings.append(warning("NO_PAIRS", "error", "No matched forecast/actual hours were found."))
    elif matched < low_sample_pairs:
        warnings.append(
            warning(
                "LOW_SAMPLE",
                "warning",
                f"Only {matched} matched hourly pairs; error statistics (especially P95) are low-confidence.",
            )
        )
    if missing_forecast:
        warnings.append(
            warning(
                "MISSING_FORECAST_HOURS",
                "warning",
                f"{missing_forecast} of {expected_hours} delivery hours had no eligible forecast at their cutoff.",
                days=days_no_forecast + days_incomplete,
            )
        )
    if missing_actual:
        warnings.append(
            warning(
                "MISSING_ACTUAL_HOURS",
                "warning",
                f"{missing_actual} of {expected_hours} delivery hours had no complete hourly actual "
                f"({incomplete_actual_hours} had only one of two half-hours).",
            )
        )
    if days_fallback:
        warnings.append(
            warning(
                "FALLBACK_VINTAGE_USED",
                "info",
                f"{len(days_fallback)} delivery day(s) used an earlier complete vintage because the latest "
                "eligible vintage was incomplete.",
                days=days_fallback,
            )
        )
    if vs["max_gap_hours"] is not None and vs["max_gap_hours"] > 6:
        warnings.append(
            warning(
                "VINTAGE_GAPS",
                "warning",
                f"Largest gap between forecast publications was {vs['max_gap_hours']:.1f} h "
                "(typical cadence is 2-4 h).",
            )
        )
    if forecast_gran is not None and abs(forecast_gran - 60.0) > 1e-6:
        warnings.append(
            warning(
                "UNEXPECTED_FORECAST_GRANULARITY",
                "warning",
                f"WINDFOR spacing is {forecast_gran:g} minutes, not the expected 60. Hourly alignment "
                "assumptions may not hold.",
            )
        )
    api = fetch_stats or {}
    if api.get("rows_dropped_malformed"):
        warnings.append(
            warning(
                "MALFORMED_ROWS_DROPPED",
                "warning",
                f"{api['rows_dropped_malformed']} malformed API row(s) were discarded.",
            )
        )
    return CalibrationDataset(observations=obs, quality=quality, warnings=warnings)


def compute_breakdowns(obs: pd.DataFrame, *, low_sample_bucket: int = 30) -> dict[str, Any]:
    """Error breakdowns by UK hour-of-day and by UK delivery day. Buckets carry their sample size."""
    if obs.empty:
        return {"by_hour": [], "by_day": [], "low_sample_threshold": low_sample_bucket}

    def summarise(g: pd.DataFrame) -> dict[str, Any]:
        m = compute_error_metrics(g["forecast_mw"].to_numpy(), g["actual_mw"].to_numpy())
        return {
            "n": m.n,
            "mae_mw": m.mae_mw,
            "rmse_mw": m.rmse_mw,
            "bias_mw": m.bias_mw,
            "p95_abs_error_mw": m.p95_abs_error_mw,
            "low_sample": m.n < low_sample_bucket,
        }

    by_hour = [{"hour": int(h), **summarise(g)} for h, g in obs.groupby("hour_local", sort=True)]
    by_day = [
        {"date": d.isoformat(), **summarise(g)} for d, g in obs.groupby("delivery_date", sort=True)
    ]
    for item in by_day:
        item["low_sample"] = item["n"] < 12  # a delivery day with < half its hours is thin
    return {"by_hour": by_hour, "by_day": by_day, "low_sample_threshold": low_sample_bucket}
