import type {
  AppConfig,
  CalibrationDetail,
  CalibrationSummary,
  DecisionResponse,
  ErrorMetrics,
  EvaluationResponse,
  ForecastHour,
  PlanBasis,
  PlanHour,
  PlanScenario,
  ProcurementResponse,
} from "../types/api";

export const config: AppConfig = {
  timezone: "Europe/London",
  default_calibration_start: "2025-10-01",
  default_calibration_end: "2025-12-31",
  decision_window_start: "2026-01-01",
  decision_window_end: "2026-01-31",
  default_cutoff_time: "17:00",
  min_calibration_pairs: 72,
  low_sample_pairs: 500,
  max_calibration_days: 400,
  latest_calibration_end_date: "2026-10-24",
};

export const metrics: ErrorMetrics = {
  n: 2209,
  mae_mw: 1994.6,
  rmse_mw: 2558.3,
  bias_mw: 1449.5,
  p90_abs_error_mw: 4285.1,
  p95_abs_error_mw: 5042.7,
  n_overforecast: 1611,
  share_overforecast: 0.729,
  p90_positive_error_mw: 4608,
  p95_positive_error_mw: 5345.5,
  p05_error_mw: -1719.2,
  p10_error_mw: -1051.7,
  p50_error_mw: 1221.5,
  p90_error_mw: 4274.2,
  p95_error_mw: 5042.7,
  mean_forecast_mw: 11784.8,
  mean_actual_mw: 10335.4,
  n_matched: 2209,
  n_unmatched: 0,
};

export function summary(over: Partial<CalibrationSummary> = {}): CalibrationSummary {
  return {
    id: "cal-1",
    version: 1,
    status: "completed",
    is_active: true,
    start_date: "2025-10-01",
    end_date: "2025-12-31",
    cutoff_time: "17:00",
    metric_version: "v1",
    progress: 100,
    stage: "Completed",
    error_code: null,
    error_message: null,
    created_at: "2026-10-25T00:00:00Z",
    started_at: "2026-10-25T00:00:01Z",
    completed_at: "2026-10-25T00:00:07Z",
    activated_at: "2026-10-25T00:00:07Z",
    n_matched: 2209,
    n_unmatched: 0,
    warning_count: 0,
    ...over,
  };
}

export function detail(over: Partial<CalibrationDetail> = {}): CalibrationDetail {
  return {
    ...summary(),
    settings: { forecast_selection_policy: "latest_complete_vintage", error_convention: "forecast_mw - actual_mw", percentile_method: "linear" },
    metrics,
    breakdowns: {
      by_hour: [{ hour: 0, n: 92, mae_mw: 1900, rmse_mw: 2400, bias_mw: 1400, p95_abs_error_mw: 4900, low_sample: false }],
      by_day: [{ date: "2025-10-01", n: 24, mae_mw: 2100, rmse_mw: 2500, bias_mw: 1500, p95_abs_error_mw: 4000, low_sample: false }],
      low_sample_threshold: 30,
    },
    quality: { delivery_days_requested: 92, expected_hours: 2209, matched_pairs: 2209, api: { requests_made: 7, cache_hits: 0 } },
    warnings: [],
    sample_size_note: null,
    ...over,
  };
}

function hours(missing: string[] = []): ForecastHour[] {
  return Array.from({ length: 24 }, (_, h) => {
    const label = `${String(h).padStart(2, "0")}:00`;
    const miss = missing.includes(label);
    const f = 12000 + h * 100;
    return {
      start_utc: `2026-01-15T${String(h).padStart(2, "0")}:00:00Z`,
      local_label: label,
      local_iso: `2026-01-15T${label}:00+00:00`,
      hour_local: h,
      forecast_mw: miss ? null : f,
      missing: miss,
      bias_adjusted_mw: miss ? null : f - 1449.5,
      conservative_mw: miss ? null : f - 5042.7,
      interval_low_mw: miss ? null : f - 5042.7,
      interval_high_mw: miss ? null : f + 1719.2,
    };
  });
}

export function decision(over: Partial<DecisionResponse> = {}, missing: string[] = []): DecisionResponse {
  const available = 24 - missing.length;
  return {
    delivery_date: "2026-01-15",
    timezone: "Europe/London",
    cutoff: { cutoff_time: "17:00", local_iso: "2026-01-14T17:00:00+00:00", utc: "2026-01-14T17:00:00Z", rule: "rule" },
    forecast: {
      source: "Elexon",
      dataset: "WINDFOR",
      policy: "latest_complete_vintage",
      vintage_publish_time_utc: "2026-01-14T15:30:00Z",
      vintage_publish_time_local: "2026-01-14T15:30:00+00:00",
      latest_eligible_publish_time_utc: "2026-01-14T15:30:00Z",
      eligible_vintages_considered: 6,
      expected_hours: 24,
      available_hours: available,
      missing_hours: missing,
      is_complete: missing.length === 0,
      fallback_used: false,
      fallback_reason: null,
    },
    hours: hours(missing),
    calibration: {
      id: "cal-1",
      version: 1,
      start_date: "2025-10-01",
      end_date: "2025-12-31",
      cutoff_time: "17:00",
      calculated_at: "2026-10-25T00:00:07Z",
      pairs_stored: 2209,
      pairs_used: 2209,
      pairs_excluded_not_yet_available: 0,
      effective_start_date: "2025-10-01",
      effective_end_date: "2025-12-31",
      cutoff_matches_calibration: true,
      is_active: true,
    },
    metrics,
    risk: {
      percentile: 95,
      shortfall_quantile_mw: 5042.7,
      shortfall_buffer_mw: 5042.7,
      bias_mw: 1449.5,
      bias_adjustment_mw: -1449.5,
      residual_buffer_mw: 3593.2,
      overforecast_share: 0.729,
      interval_confidence_pct: 90,
      mean_baseline_mw: 12115.2,
      mean_bias_adjusted_mw: 10665.8,
      mean_conservative_mw: 7072.5,
      min_conservative_mw: 3022.3,
      hours_floored_at_zero: 0,
      p90_positive_error_mw: 4608,
      p95_positive_error_mw: 5345.5,
    },
    explanation: {
      headline: "At P95, wind in any hour of 15 Jan 2026 could be up to 5,043 MW below the baseline forecast.",
      steps: ["Forecast: the WINDFOR vintage published 2026-01-14T15:30:00+00:00 (UK).", "Calibration: version 1."],
      definitions: { error: "error = forecast - actual" },
    },
    limitations: ["Elexon wind data alone cannot determine a purchase quantity."],
    warnings: [],
    procurement_note: "These figures are GB-wide wind forecast uncertainty. A purchase volume is only calculated from demand that you enter yourself.",
    generated_at: "2026-10-25T01:00:00Z",
    ...over,
  };
}

export function evaluation(over: Partial<EvaluationResponse> = {}): EvaluationResponse {
  const d = decision();
  return {
    delivery_date: "2026-01-15",
    timezone: "Europe/London",
    cutoff: d.cutoff,
    forecast: d.forecast,
    hours: d.hours.map((h) => ({
      start_utc: h.start_utc,
      local_label: h.local_label,
      local_iso: h.local_iso,
      forecast_mw: h.forecast_mw,
      actual_mw: (h.forecast_mw ?? 0) - 1500,
      error_mw: 1500,
      conservative_mw: h.conservative_mw,
      actual_below_conservative: false,
    })),
    summary: {
      expected_hours: 24,
      matched_pairs: 24,
      hours_missing_forecast: 0,
      hours_missing_actual: 0,
      actuals_available: true,
      metrics: { ...metrics, n: 24, bias_mw: 1500, mae_mw: 1500 },
      percentile: 95,
      hours_actual_below_conservative: 0,
      share_actual_below_conservative: 0,
      expected_share_below_conservative: 0.05,
    },
    calibration: d.calibration,
    warnings: [],
    notice: "Retrospective evaluation.",
    generated_at: "2026-10-25T01:00:00Z",
    ...over,
  };
}

/** Purchase plan built with the same per-hour formula as the backend: buy = max(0, demand - contracted - wind). */
export function plan(
  opts: { demand?: number | number[]; contracted?: number; share?: number; missing?: string[] } = {},
  over: Partial<ProcurementResponse> = {},
): ProcurementResponse {
  const d = decision({}, opts.missing ?? []);
  const share = (opts.share ?? 100) / 100;
  const contracted = opts.contracted ?? 0;
  const demandAt = (i: number) => (Array.isArray(opts.demand) ? opts.demand[i] : (opts.demand ?? 15000));

  const hours: PlanHour[] = d.hours.map((h, i) => {
    const demand = demandAt(i);
    const base: PlanHour = {
      start_utc: h.start_utc,
      local_label: h.local_label,
      hour_local: h.hour_local,
      demand_mw: demand,
      contracted_mw: contracted,
      planned: !h.missing,
      wind_forecast_mw: null,
      wind_expected_mw: null,
      wind_cautious_mw: null,
      buy_forecast_mw: null,
      buy_expected_mw: null,
      buy_cautious_mw: null,
      surplus_forecast_mw: null,
      surplus_expected_mw: null,
      surplus_cautious_mw: null,
    };
    if (h.missing) return base;
    const residual = Math.max(0, demand - contracted);
    const calc = (national: number) => {
      const wind = share * national;
      const used = Math.min(wind, residual);
      return { wind, buy: residual - used, surplus: wind - used };
    };
    const f = calc(h.forecast_mw!);
    const e = calc(h.bias_adjusted_mw!);
    const c = calc(h.conservative_mw!);
    return {
      ...base,
      wind_forecast_mw: f.wind,
      wind_expected_mw: e.wind,
      wind_cautious_mw: c.wind,
      buy_forecast_mw: f.buy,
      buy_expected_mw: e.buy,
      buy_cautious_mw: c.buy,
      surplus_forecast_mw: f.surplus,
      surplus_expected_mw: e.surplus,
      surplus_cautious_mw: c.surplus,
    };
  });

  const scenario = (key: PlanBasis, label: string, description: string): PlanScenario => {
    const planned = hours.filter((h) => h.planned);
    const buy = (h: PlanHour) => h[`buy_${key}_mw` as keyof PlanHour] as number;
    const wind = (h: PlanHour) => h[`wind_${key}_mw` as keyof PlanHour] as number;
    const surplus = (h: PlanHour) => h[`surplus_${key}_mw` as keyof PlanHour] as number;
    const total = planned.reduce((s, h) => s + buy(h), 0);
    const windTotal = planned.reduce((s, h) => s + wind(h), 0);
    const surplusTotal = planned.reduce((s, h) => s + surplus(h), 0);
    const residual = planned.reduce((s, h) => s + Math.max(0, h.demand_mw - h.contracted_mw), 0);
    const peak = planned.reduce((best, h) => (buy(h) > best.v ? { v: buy(h), l: h.local_label } : best), { v: 0, l: null as string | null });
    return {
      key,
      label,
      description,
      buy_total_mwh: total,
      avg_buy_mw: planned.length ? total / planned.length : 0,
      peak_buy_mw: peak.v,
      peak_buy_hour: peak.l,
      hours_with_buy: planned.filter((h) => buy(h) > 0).length,
      wind_total_mwh: windTotal,
      wind_used_mwh: windTotal - surplusTotal,
      wind_cover_pct: residual > 0 ? (100 * (windTotal - surplusTotal)) / residual : null,
      surplus_wind_mwh: surplusTotal,
      hours_with_surplus: planned.filter((h) => surplus(h) > 0).length,
    };
  };
  const scenarios = [
    scenario("forecast", "As published", "Wind arrives exactly as the forecast says."),
    scenario("expected", "Expected", "Forecast corrected for the average historical error (bias)."),
    scenario("cautious", "Cautious", "Wind falls short by the historical P95 shortfall buffer."),
  ];
  const planned = hours.filter((h) => h.planned);
  return {
    delivery_date: "2026-01-15",
    cutoff: d.cutoff,
    percentile: 95,
    recommended_basis: "cautious",
    wind_share_pct: opts.share ?? 100,
    demand_total_mwh: planned.reduce((s, h) => s + h.demand_mw, 0),
    contracted_total_mwh: planned.reduce((s, h) => s + Math.min(h.contracted_mw, h.demand_mw), 0),
    hours_total: 24,
    hours_planned: planned.length,
    hours_unplanned: 24 - planned.length,
    scenarios,
    risk_cover_mwh: scenarios[2].buy_total_mwh - scenarios[1].buy_total_mwh,
    hours,
    forecast: d.forecast,
    calibration: d.calibration,
    assumptions: ["Wind supply = 100% of GB national wind output.", "Purchase per hour = max(0, demand - existing contracted supply - wind)."],
    warnings: [],
    generated_at: "2026-10-25T01:00:00Z",
    ...over,
  };
}
