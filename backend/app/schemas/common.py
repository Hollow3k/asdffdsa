from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class QualityWarning(ApiModel):
    code: str
    severity: str  # info | warning | error
    message: str
    days: list[str] | None = None


class ErrorMetricsOut(ApiModel):
    """Forecast error statistics. ``error = forecast_mw - actual_mw``; positive = over-forecast."""

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
    p05_error_mw: float | None = None
    p10_error_mw: float | None = None
    p50_error_mw: float | None = None
    p90_error_mw: float | None = None
    p95_error_mw: float | None = None
    mean_forecast_mw: float | None = None
    mean_actual_mw: float | None = None
    n_matched: int | None = None
    n_unmatched: int | None = None


class ErrorDetail(ApiModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorEnvelope(ApiModel):
    error: ErrorDetail
