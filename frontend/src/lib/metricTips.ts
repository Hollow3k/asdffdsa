/** Metric definitions shown in tooltips. Mirrors backend METRIC_DEFINITIONS. error = forecast − actual. */
export const METRIC_TIPS = {
  error: "error = forecast MW − actual MW. Positive = over-forecast (wind fell short of the forecast). Negative = under-forecast.",
  mae: "Mean absolute error: the average size of the miss in MW, ignoring direction.",
  rmse: "Root mean squared error in MW. Penalises large misses more than MAE.",
  bias: "Mean signed error. Positive means forecasts were on average too high (wind over-forecast).",
  p90abs: "90th percentile of the absolute error: 90% of hours missed by no more than this, in either direction.",
  p95abs: "95th percentile of the absolute error: 95% of hours missed by no more than this, in either direction.",
  p90pos: "90th percentile of the error among over-forecast hours only (error > 0): the size of a bad over-forecast miss.",
  p95pos: "95th percentile of the error among over-forecast hours only (error > 0): the size of a severe over-forecast miss.",
  shortfall:
    "Percentile of the signed error over ALL hours. In that share of historical hours, forecast − actual was no larger than this. Floored at 0 to give the shortfall buffer.",
  share: "Share of matched hours in which the forecast was higher than the actual (error > 0).",
  pairs: "Hours where both a forecast available at the cutoff and a complete hourly actual exist.",
} as const;
