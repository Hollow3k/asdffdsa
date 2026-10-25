"""Forecast error metrics. Deterministic, dependency-light, independently testable.

Sign convention (used everywhere in the application)::

    error = forecast_mw - actual_mw

* error > 0  -> wind was OVER-forecast  (actual generation lower than predicted: shortfall risk)
* error < 0  -> wind was UNDER-forecast (actual generation higher than predicted)

Percentiles use linear interpolation between order statistics (numpy's default, "type 7").
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

METRIC_VERSION = "v1"

METRIC_DEFINITIONS: dict[str, str] = {
    "error": "error = forecast MW - actual MW. Positive = over-forecast (wind fell short); negative = under-forecast.",
    "mae_mw": "Mean absolute error: average of |error| in MW.",
    "rmse_mw": "Root mean squared error in MW; penalises large misses more than MAE.",
    "bias_mw": "Mean signed error in MW. Positive = forecasts are on average too high.",
    "p90_abs_error_mw": "90th percentile of |error|: 90% of hours missed by no more than this, in either direction.",
    "p95_abs_error_mw": "95th percentile of |error|: 95% of hours missed by no more than this, in either direction.",
    "p90_positive_error_mw": "90th percentile of error among over-forecast hours only (error > 0). Size of a bad over-forecast miss.",
    "p95_positive_error_mw": "95th percentile of error among over-forecast hours only (error > 0). Size of a severe over-forecast miss.",
    "p90_shortfall_mw": "90th percentile of signed error over ALL hours: in 90% of hours, forecast minus actual was at most this (floored at 0 for risk use).",
    "p95_shortfall_mw": "95th percentile of signed error over ALL hours: in 95% of hours, forecast minus actual was at most this (floored at 0 for risk use).",
    "share_overforecast": "Share of matched hours with error > 0.",
}


@dataclass(frozen=True)
class ErrorMetrics:
    n: int
    mae_mw: float | None = None
    rmse_mw: float | None = None
    bias_mw: float | None = None
    p90_abs_error_mw: float | None = None
    p95_abs_error_mw: float | None = None
    n_overforecast: int = 0
    share_overforecast: float | None = None
    p90_positive_error_mw: float | None = None
    p95_positive_error_mw: float | None = None
    # Quantiles of the signed error over all hours (used for the shortfall buffer and bands).
    p05_error_mw: float | None = None
    p10_error_mw: float | None = None
    p50_error_mw: float | None = None
    p90_error_mw: float | None = None
    p95_error_mw: float | None = None
    mean_forecast_mw: float | None = None
    mean_actual_mw: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def available(self) -> bool:
        return self.n > 0


def forecast_error(forecast_mw: float | np.ndarray, actual_mw: float | np.ndarray):
    """Signed forecast error. Positive means wind was over-forecast."""
    return np.asarray(forecast_mw, dtype=float) - np.asarray(actual_mw, dtype=float)


def percentile(values: Sequence[float] | np.ndarray, q: float) -> float | None:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return None
    return float(np.percentile(arr, q))


def signed_error_quantile(errors: Sequence[float] | np.ndarray, q: float) -> float | None:
    """q-th percentile (0-100) of the signed error over all hours."""
    return percentile(errors, q)


def compute_error_metrics(forecast_mw: Sequence[float], actual_mw: Sequence[float]) -> ErrorMetrics:
    """Metrics for aligned forecast/actual arrays.

    Pairs containing NaN/inf are excluded (they cannot be valid matched observations). Returns
    ``n=0`` with every statistic ``None`` when there is nothing to compute - callers must show an
    "unavailable" state rather than zeros.
    """
    f = np.asarray(forecast_mw, dtype=float)
    a = np.asarray(actual_mw, dtype=float)
    if f.shape != a.shape:
        raise ValueError("forecast and actual must have the same length (pairs are aligned by caller)")
    valid = np.isfinite(f) & np.isfinite(a)
    f, a = f[valid], a[valid]
    n = int(f.size)
    if n == 0:
        return ErrorMetrics(n=0)

    err = forecast_error(f, a)
    abs_err = np.abs(err)
    positive = err[err > 0]
    return ErrorMetrics(
        n=n,
        mae_mw=float(abs_err.mean()),
        rmse_mw=float(np.sqrt(np.mean(err**2))),
        bias_mw=float(err.mean()),
        p90_abs_error_mw=percentile(abs_err, 90),
        p95_abs_error_mw=percentile(abs_err, 95),
        n_overforecast=int(positive.size),
        share_overforecast=float(positive.size / n),
        p90_positive_error_mw=percentile(positive, 90),
        p95_positive_error_mw=percentile(positive, 95),
        p05_error_mw=percentile(err, 5),
        p10_error_mw=percentile(err, 10),
        p50_error_mw=percentile(err, 50),
        p90_error_mw=percentile(err, 90),
        p95_error_mw=percentile(err, 95),
        mean_forecast_mw=float(f.mean()),
        mean_actual_mw=float(a.mean()),
    )
