import { Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Banner, Card, Stat, WarningList } from "../../components/ui";
import { fmtDate, fmtUkDateTime, int, mw, pct } from "../../lib/format";
import { METRIC_TIPS } from "../../lib/metricTips";
import type { BucketStats, CalibrationDetail } from "../../types/api";

const QUALITY_LABELS: Array<[string, string]> = [
  ["delivery_days_requested", "Delivery days in range"],
  ["expected_hours", "Expected hours"],
  ["matched_pairs", "Matched hourly pairs"],
  ["hours_missing_forecast", "Hours with no eligible forecast"],
  ["hours_missing_actual", "Hours with no complete actual"],
  ["hours_incomplete_actual", "…of which only one half-hour present"],
  ["days_using_fallback_vintage", "Days using an earlier complete vintage"],
  ["days_with_incomplete_forecast", "Days with an incomplete forecast"],
  ["vintages_in_pool", "Forecast vintages fetched"],
];

export function CalibrationDetailView({ cal }: { cal: CalibrationDetail }) {
  const m = cal.metrics;
  const api = (cal.quality?.api ?? {}) as Record<string, number>;
  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          Calibration v{cal.version}
          {cal.is_active && <Badge tone="ok">active</Badge>}
          <StatusBadge status={cal.status} />
        </span>
      }
      subtitle={
        <>
          {fmtDate(cal.start_date)} – {fmtDate(cal.end_date)} · cutoff {cal.cutoff_time} UK the day before · calculated {fmtUkDateTime(cal.completed_at)} UK · metrics {cal.metric_version}
        </>
      }
    >
      {cal.status === "failed" && (
        <Banner kind="error" title="This calculation failed">
          {cal.error_message}
        </Banner>
      )}
      {cal.status !== "completed" && cal.status !== "failed" && <Banner kind="info">Calculation in progress ({cal.progress}%): {cal.stage}</Banner>}
      {cal.status === "completed" && m && m.n > 0 && (
        <div className="space-y-5">
          {cal.sample_size_note && <Banner kind="warning">{cal.sample_size_note}</Banner>}
          <WarningList warnings={cal.warnings} />
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat label="Matched hours" value={int(m.n)} tip={METRIC_TIPS.pairs} hint={`${int(m.n_unmatched ?? 0)} unmatched`} />
            <Stat label="MAE" value={mw(m.mae_mw)} unit="MW" tip={METRIC_TIPS.mae} />
            <Stat label="RMSE" value={mw(m.rmse_mw)} unit="MW" tip={METRIC_TIPS.rmse} />
            <Stat label="Bias" value={mw(m.bias_mw, { signed: true })} unit="MW" tip={METRIC_TIPS.bias} />
            <Stat label="Over-forecast hours" value={pct(m.share_overforecast)} tip={METRIC_TIPS.share} />
            <Stat label="P90 absolute error" value={mw(m.p90_abs_error_mw)} unit="MW" tip={METRIC_TIPS.p90abs} />
            <Stat label="P95 absolute error" value={mw(m.p95_abs_error_mw)} unit="MW" tip={METRIC_TIPS.p95abs} />
            <Stat label="P90 positive error" value={mw(m.p90_positive_error_mw)} unit="MW" tip={METRIC_TIPS.p90pos} tone="risk" />
            <Stat label="P95 positive error" value={mw(m.p95_positive_error_mw)} unit="MW" tip={METRIC_TIPS.p95pos} tone="risk" />
            <Stat label="P95 signed error (all hours)" value={mw(m.p95_error_mw, { signed: true })} unit="MW" tip={METRIC_TIPS.shortfall} />
          </dl>

          {cal.breakdowns && cal.breakdowns.by_hour.length > 0 && (
            <div className="grid gap-5 xl:grid-cols-2">
              <BreakdownChart
                title="Error by UK hour of day"
                data={cal.breakdowns.by_hour.map((b) => ({ ...b, label: String(b.hour).padStart(2, "0") }))}
                xLabel="Hour of day (UK)"
                threshold={cal.breakdowns.low_sample_threshold}
              />
              <BreakdownChart
                title="Error by delivery day"
                data={cal.breakdowns.by_day.map((b) => ({ ...b, label: b.date.slice(5) }))}
                xLabel="Delivery day (MM-DD)"
                sparse
                threshold={12}
              />
            </div>
          )}

          <details className="text-sm">
            <summary className="cursor-pointer font-medium text-wind">Data quality and reproducibility</summary>
            <div className="mt-3 grid gap-6 md:grid-cols-2">
              <dl className="space-y-1">
                {QUALITY_LABELS.map(([k, label]) => (
                  <div key={k} className="flex justify-between gap-4 border-b border-line-soft py-1">
                    <dt className="text-ink-soft">{label}</dt>
                    <dd className="num font-medium">{int(Number(cal.quality?.[k] ?? 0))}</dd>
                  </div>
                ))}
                <div className="flex justify-between gap-4 border-b border-line-soft py-1">
                  <dt className="text-ink-soft">API requests / cache hits</dt>
                  <dd className="num font-medium">
                    {int(api.requests_made ?? 0)} / {int(api.cache_hits ?? 0)}
                  </dd>
                </div>
              </dl>
              <dl className="space-y-1">
                {(
                  [
                    ["Forecast dataset", "WINDFOR (hourly vintages)"],
                    ["Actual dataset", "FUELHH, fuel type WIND (half-hourly)"],
                    ["Alignment", "hourly mean of 2 half-hours, UK-local hours"],
                    ["Selection policy", String(cal.settings.forecast_selection_policy ?? "")],
                    ["Error convention", String(cal.settings.error_convention ?? "")],
                    ["Percentiles", String(cal.settings.percentile_method ?? "")],
                  ] as Array<[string, string]>
                ).map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4 border-b border-line-soft py-1">
                    <dt className="text-ink-soft">{k}</dt>
                    <dd className="text-right font-medium">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        </div>
      )}
      {cal.status === "completed" && (!m || m.n === 0) && <Banner kind="warning">Metrics unavailable: this calibration has no matched hours.</Banner>}
    </Card>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone = status === "completed" ? "ok" : status === "failed" ? "bad" : "info";
  return <Badge tone={tone}>{status}</Badge>;
}

type Row = BucketStats & { label: string };

function BreakdownChart({ title, data, xLabel, sparse, threshold }: { title: string; data: Row[]; xLabel: string; sparse?: boolean; threshold: number }) {
  const lowCount = data.filter((d) => d.low_sample).length;
  return (
    <figure className="m-0" aria-label={title}>
      <figcaption className="mb-1 text-sm font-semibold">{title}</figcaption>
      <div className="h-[240px]">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#e8edf2" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#46556b" }} interval={sparse ? "preserveStartEnd" : 1} tickLine={false} label={{ value: xLabel, position: "insideBottom", offset: -2, fontSize: 11, fill: "#7a8799" }} height={36} />
            <YAxis tick={{ fontSize: 11, fill: "#46556b" }} tickFormatter={(v: number) => v.toLocaleString("en-GB")} tickLine={false} axisLine={false} width={52} />
            <ReferenceLine y={0} stroke="#46556b" />
            <Tooltip
              formatter={(v, name, item) => [`${mw(Number(v), { signed: name === "bias_mw" })} MW`, `${name === "mae_mw" ? "MAE" : "Bias"}${item?.payload?.low_sample ? " (low sample)" : ""}`]}
              labelFormatter={(l, items) => `${String(l)} · n=${items?.[0]?.payload?.n ?? "?"}`}
              contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#dde3ea" }}
            />
            <Legend formatter={(v: string) => <span className="text-xs text-ink-soft">{v === "mae_mw" ? "MAE" : "Bias (forecast − actual)"}</span>} />
            <Bar dataKey="mae_mw" fill="#0f766e" isAnimationActive={false} radius={[2, 2, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill="#0f766e" fillOpacity={d.low_sample ? 0.3 : 0.85} />
              ))}
            </Bar>
            <Line dataKey="bias_mw" stroke="#b45309" strokeWidth={2} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {lowCount > 0 && (
        <p className="text-xs text-ink-soft">
          {lowCount} lighter bar{lowCount > 1 ? "s" : ""}: fewer than {threshold} matched hours; treat as unreliable.
        </p>
      )}
    </figure>
  );
}
