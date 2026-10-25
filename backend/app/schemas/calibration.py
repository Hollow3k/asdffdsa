from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.schemas.common import ApiModel, ErrorMetricsOut, QualityWarning


class CalibrationCreate(ApiModel):
    start_date: date = Field(description="First UK delivery date included in the calibration")
    end_date: date = Field(description="Last UK delivery date included (inclusive)")
    cutoff_time: str = Field(
        default="17:00",
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="UK wall-clock forecast publication cutoff on the day before each delivery day (HH:MM)",
    )
    forecast_selection_policy: str = Field(default="latest_complete_vintage")

    @field_validator("forecast_selection_policy")
    @classmethod
    def _policy(cls, v: str) -> str:
        if v not in ("latest_complete_vintage", "latest_vintage_only"):
            raise ValueError("must be 'latest_complete_vintage' or 'latest_vintage_only'")
        return v

    @model_validator(mode="after")
    def _order(self) -> CalibrationCreate:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        return self


class CalibrationSummary(ApiModel):
    id: str
    version: int
    status: str
    is_active: bool
    start_date: date
    end_date: date
    cutoff_time: str
    metric_version: str
    progress: int
    stage: str
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    activated_at: datetime | None = None
    n_matched: int | None = None
    n_unmatched: int | None = None
    warning_count: int = 0


class HourBreakdown(ApiModel):
    hour: int
    n: int
    mae_mw: float | None
    rmse_mw: float | None
    bias_mw: float | None
    p95_abs_error_mw: float | None
    low_sample: bool


class DayBreakdown(ApiModel):
    date: date
    n: int
    mae_mw: float | None
    rmse_mw: float | None
    bias_mw: float | None
    p95_abs_error_mw: float | None
    low_sample: bool


class Breakdowns(ApiModel):
    by_hour: list[HourBreakdown] = []
    by_day: list[DayBreakdown] = []
    low_sample_threshold: int = 30


class CalibrationDetail(CalibrationSummary):
    settings: dict[str, Any]
    metrics: ErrorMetricsOut | None = None
    breakdowns: Breakdowns | None = None
    quality: dict[str, Any] | None = None
    warnings: list[QualityWarning] = []
    sample_size_note: str | None = None


class ObservationOut(ApiModel):
    delivery_start: datetime
    delivery_date: date
    hour_local: int
    forecast_mw: float
    actual_mw: float
    error_mw: float
    forecast_publish_time: datetime
    decision_cutoff: datetime
    actual_available_at: datetime


class ObservationPage(ApiModel):
    total: int
    limit: int
    offset: int
    items: list[ObservationOut]


class AppConfig(ApiModel):
    timezone: str
    default_calibration_start: date
    default_calibration_end: date
    decision_window_start: date
    decision_window_end: date
    default_cutoff_time: str
    min_calibration_pairs: int
    low_sample_pairs: int
    max_calibration_days: int
    latest_calibration_end_date: date
