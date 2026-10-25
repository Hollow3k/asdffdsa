from __future__ import annotations

from datetime import date, datetime

from app.schemas.common import ApiModel, ErrorMetricsOut, QualityWarning


class CutoffInfo(ApiModel):
    cutoff_time: str  # HH:MM UK
    local_iso: str  # e.g. 2026-01-14T17:00:00+00:00
    utc: datetime
    rule: str


class ForecastInfo(ApiModel):
    source: str
    dataset: str
    policy: str
    vintage_publish_time_utc: datetime | None
    vintage_publish_time_local: str | None
    latest_eligible_publish_time_utc: datetime | None
    eligible_vintages_considered: int
    expected_hours: int
    available_hours: int
    missing_hours: list[str]  # UK local HH:MM labels
    is_complete: bool
    fallback_used: bool
    fallback_reason: str | None = None


class ForecastHour(ApiModel):
    start_utc: datetime
    local_label: str
    local_iso: str
    hour_local: int
    forecast_mw: float | None
    missing: bool
    # Present once a calibration is applied:
    bias_adjusted_mw: float | None = None
    conservative_mw: float | None = None
    interval_low_mw: float | None = None
    interval_high_mw: float | None = None


class CalibrationRef(ApiModel):
    id: str
    version: int
    start_date: date
    end_date: date
    cutoff_time: str
    calculated_at: datetime | None
    pairs_stored: int
    pairs_used: int
    pairs_excluded_not_yet_available: int
    effective_start_date: date | None
    effective_end_date: date | None
    cutoff_matches_calibration: bool
    is_active: bool


class RiskAssessment(ApiModel):
    percentile: float
    # Signed-error quantile over all hours at `percentile` (forecast - actual). May be <= 0.
    shortfall_quantile_mw: float
    # Conservative wind shortfall buffer = max(0, quantile): MW below baseline to plan for.
    shortfall_buffer_mw: float
    bias_mw: float
    bias_adjustment_mw: float  # = -bias; add to the baseline to get the bias-adjusted estimate
    residual_buffer_mw: float  # extra downside beyond bias adjustment = buffer - bias (not double counted)
    overforecast_share: float | None
    interval_confidence_pct: float
    mean_baseline_mw: float | None
    mean_bias_adjusted_mw: float | None
    mean_conservative_mw: float | None
    min_conservative_mw: float | None
    hours_floored_at_zero: int
    p90_positive_error_mw: float | None
    p95_positive_error_mw: float | None


class Explanation(ApiModel):
    headline: str
    steps: list[str]
    definitions: dict[str, str]


class DecisionResponse(ApiModel):
    delivery_date: date
    timezone: str
    cutoff: CutoffInfo
    forecast: ForecastInfo
    hours: list[ForecastHour]
    calibration: CalibrationRef
    metrics: ErrorMetricsOut
    risk: RiskAssessment
    explanation: Explanation
    limitations: list[str]
    warnings: list[QualityWarning]
    procurement_note: str
    generated_at: datetime


class EvaluationHour(ApiModel):
    start_utc: datetime
    local_label: str
    local_iso: str
    forecast_mw: float | None
    actual_mw: float | None
    error_mw: float | None  # forecast - actual
    conservative_mw: float | None = None
    actual_below_conservative: bool | None = None


class EvaluationSummary(ApiModel):
    expected_hours: int
    matched_pairs: int
    hours_missing_forecast: int
    hours_missing_actual: int
    actuals_available: bool
    metrics: ErrorMetricsOut
    percentile: float | None = None
    hours_actual_below_conservative: int | None = None
    share_actual_below_conservative: float | None = None
    expected_share_below_conservative: float | None = None


class EvaluationResponse(ApiModel):
    delivery_date: date
    timezone: str
    cutoff: CutoffInfo
    forecast: ForecastInfo
    hours: list[EvaluationHour]
    summary: EvaluationSummary
    calibration: CalibrationRef | None = None
    warnings: list[QualityWarning]
    notice: str
    generated_at: datetime


class CoverageDataset(ApiModel):
    dataset: str
    rows: int
    first: datetime | None
    last: datetime | None
    detail: dict


class CoverageGap(ApiModel):
    kind: str
    start_utc: datetime
    end_utc: datetime
    description: str


class DataCoverageResponse(ApiModel):
    note: str
    start_date: date | None
    end_date: date | None
    forecast: CoverageDataset
    actual: CoverageDataset
    gaps: list[CoverageGap]
    gaps_truncated: bool
    fetched_ranges: int
