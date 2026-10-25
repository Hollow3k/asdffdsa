// Mirrors the backend Pydantic schemas. error = forecast_mw - actual_mw (positive = over-forecast).

export interface AppConfig {
  timezone: string;
  default_calibration_start: string;
  default_calibration_end: string;
  decision_window_start: string;
  decision_window_end: string;
  default_cutoff_time: string;
  min_calibration_pairs: number;
  low_sample_pairs: number;
  max_calibration_days: number;
  latest_calibration_end_date: string;
}

export interface QualityWarning {
  code: string;
  severity: "info" | "warning" | "error" | string;
  message: string;
  days?: string[] | null;
}

export interface ErrorMetrics {
  n: number;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
  p90_abs_error_mw: number | null;
  p95_abs_error_mw: number | null;
  n_overforecast: number;
  share_overforecast: number | null;
  p90_positive_error_mw: number | null;
  p95_positive_error_mw: number | null;
  p05_error_mw: number | null;
  p10_error_mw: number | null;
  p50_error_mw: number | null;
  p90_error_mw: number | null;
  p95_error_mw: number | null;
  mean_forecast_mw: number | null;
  mean_actual_mw: number | null;
  n_matched?: number | null;
  n_unmatched?: number | null;
}

export type CalibrationStatus = "pending" | "running" | "completed" | "failed";

export interface CalibrationSummary {
  id: string;
  version: number;
  status: CalibrationStatus;
  is_active: boolean;
  start_date: string;
  end_date: string;
  cutoff_time: string;
  metric_version: string;
  progress: number;
  stage: string;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  activated_at: string | null;
  n_matched: number | null;
  n_unmatched: number | null;
  warning_count: number;
}

export interface BucketStats {
  n: number;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
  p95_abs_error_mw: number | null;
  low_sample: boolean;
}
export interface HourBreakdown extends BucketStats {
  hour: number;
}
export interface DayBreakdown extends BucketStats {
  date: string;
}

export interface CalibrationDetail extends CalibrationSummary {
  settings: Record<string, unknown>;
  metrics: ErrorMetrics | null;
  breakdowns: { by_hour: HourBreakdown[]; by_day: DayBreakdown[]; low_sample_threshold: number } | null;
  quality: Record<string, unknown> | null;
  warnings: QualityWarning[];
  sample_size_note: string | null;
}

export interface CalibrationCreate {
  start_date: string;
  end_date: string;
  cutoff_time: string;
}

export interface CutoffInfo {
  cutoff_time: string;
  local_iso: string;
  utc: string;
  rule: string;
}

export interface ForecastInfo {
  source: string;
  dataset: string;
  policy: string;
  vintage_publish_time_utc: string | null;
  vintage_publish_time_local: string | null;
  latest_eligible_publish_time_utc: string | null;
  eligible_vintages_considered: number;
  expected_hours: number;
  available_hours: number;
  missing_hours: string[];
  is_complete: boolean;
  fallback_used: boolean;
  fallback_reason: string | null;
}

export interface ForecastHour {
  start_utc: string;
  local_label: string;
  local_iso: string;
  hour_local: number;
  forecast_mw: number | null;
  missing: boolean;
  bias_adjusted_mw: number | null;
  conservative_mw: number | null;
  interval_low_mw: number | null;
  interval_high_mw: number | null;
}

export interface CalibrationRef {
  id: string;
  version: number;
  start_date: string;
  end_date: string;
  cutoff_time: string;
  calculated_at: string | null;
  pairs_stored: number;
  pairs_used: number;
  pairs_excluded_not_yet_available: number;
  effective_start_date: string | null;
  effective_end_date: string | null;
  cutoff_matches_calibration: boolean;
  is_active: boolean;
}

export interface RiskAssessment {
  percentile: number;
  shortfall_quantile_mw: number;
  shortfall_buffer_mw: number;
  bias_mw: number;
  bias_adjustment_mw: number;
  residual_buffer_mw: number;
  overforecast_share: number | null;
  interval_confidence_pct: number;
  mean_baseline_mw: number | null;
  mean_bias_adjusted_mw: number | null;
  mean_conservative_mw: number | null;
  min_conservative_mw: number | null;
  hours_floored_at_zero: number;
  p90_positive_error_mw: number | null;
  p95_positive_error_mw: number | null;
}

export interface DecisionResponse {
  delivery_date: string;
  timezone: string;
  cutoff: CutoffInfo;
  forecast: ForecastInfo;
  hours: ForecastHour[];
  calibration: CalibrationRef;
  metrics: ErrorMetrics;
  risk: RiskAssessment;
  explanation: { headline: string; steps: string[]; definitions: Record<string, string> };
  limitations: string[];
  warnings: QualityWarning[];
  procurement_note: string;
  generated_at: string;
}

export interface EvaluationHour {
  start_utc: string;
  local_label: string;
  local_iso: string;
  forecast_mw: number | null;
  actual_mw: number | null;
  error_mw: number | null;
  conservative_mw: number | null;
  actual_below_conservative: boolean | null;
}

export interface EvaluationResponse {
  delivery_date: string;
  timezone: string;
  cutoff: CutoffInfo;
  forecast: ForecastInfo;
  hours: EvaluationHour[];
  summary: {
    expected_hours: number;
    matched_pairs: number;
    hours_missing_forecast: number;
    hours_missing_actual: number;
    actuals_available: boolean;
    metrics: ErrorMetrics;
    percentile: number | null;
    hours_actual_below_conservative: number | null;
    share_actual_below_conservative: number | null;
    expected_share_below_conservative: number | null;
  };
  calibration: CalibrationRef | null;
  warnings: QualityWarning[];
  notice: string;
  generated_at: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

// ---- Purchase plan -------------------------------------------------------------------------------

export type PlanBasis = "forecast" | "expected" | "cautious";

export interface ProcurementRequest {
  cutoff: string;
  percentile: number;
  demand_mw?: number;
  demand_by_hour_mw?: number[];
  contracted_mw: number;
  wind_share_pct: number;
}

export interface PlanHour {
  start_utc: string;
  local_label: string;
  hour_local: number;
  demand_mw: number;
  contracted_mw: number;
  planned: boolean;
  wind_forecast_mw: number | null;
  wind_expected_mw: number | null;
  wind_cautious_mw: number | null;
  buy_forecast_mw: number | null;
  buy_expected_mw: number | null;
  buy_cautious_mw: number | null;
  surplus_forecast_mw: number | null;
  surplus_expected_mw: number | null;
  surplus_cautious_mw: number | null;
}

export interface PlanScenario {
  key: PlanBasis;
  label: string;
  description: string;
  buy_total_mwh: number;
  avg_buy_mw: number;
  peak_buy_mw: number;
  peak_buy_hour: string | null;
  hours_with_buy: number;
  wind_total_mwh: number;
  wind_used_mwh: number;
  wind_cover_pct: number | null;
  surplus_wind_mwh: number;
  hours_with_surplus: number;
}

export interface ProcurementResponse {
  delivery_date: string;
  cutoff: CutoffInfo;
  percentile: number;
  recommended_basis: PlanBasis;
  wind_share_pct: number;
  demand_total_mwh: number;
  contracted_total_mwh: number;
  hours_total: number;
  hours_planned: number;
  hours_unplanned: number;
  scenarios: PlanScenario[];
  risk_cover_mwh: number;
  hours: PlanHour[];
  forecast: ForecastInfo;
  calibration: CalibrationRef;
  assumptions: string[];
  warnings: QualityWarning[];
  generated_at: string;
}
