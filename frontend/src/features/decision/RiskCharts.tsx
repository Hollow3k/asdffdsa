import { Bar, BarChart, Cell, CartesianGrid, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { mw } from "../../lib/format";
import type { ErrorMetrics, RiskAssessment } from "../../types/api";

/** Historical distribution of forecast − actual, as quantiles. Positive = wind over-forecast (shortfall). */
export function ErrorQuantileChart({ metrics, percentile }: { metrics: ErrorMetrics; percentile: number }) {
  const rows = [
    { name: "P5", value: metrics.p05_error_mw },
    { name: "P10", value: metrics.p10_error_mw },
    { name: "P50", value: metrics.p50_error_mw },
    { name: "P90", value: metrics.p90_error_mw },
    { name: "P95", value: metrics.p95_error_mw },
  ].filter((r): r is { name: string; value: number } => r.value !== null);
  const selected = `P${percentile}`;
  return (
    <figure aria-label="Historical forecast error quantiles" className="m-0">
      <div className="h-[220px] w-full">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <BarChart data={rows} margin={{ top: 18, right: 12, left: 4, bottom: 18 }}>
            <CartesianGrid stroke="#e8edf2" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#46556b" }} tickLine={false} axisLine={false} tickMargin={18} />
            <YAxis tick={{ fontSize: 12, fill: "#46556b" }} tickFormatter={(v: number) => v.toLocaleString("en-GB")} tickLine={false} axisLine={false} width={60} />
            <ReferenceLine y={0} stroke="#46556b" />
            <Tooltip formatter={(v) => [`${mw(Number(v), { signed: true })} MW`, "forecast − actual"]} contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#dde3ea" }} />
            <Bar dataKey="value" isAnimationActive={false} radius={[3, 3, 3, 3]}>
              {rows.map((r) => (
                <Cell key={r.name} fill={r.value >= 0 ? "#b45309" : "#0f766e"} fillOpacity={r.name === selected ? 1 : 0.55} />
              ))}
              <LabelList dataKey="value" position="top" formatter={(v) => mw(Number(v), { signed: true })} style={{ fontSize: 11, fill: "#46556b" }} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-xs text-ink-soft">
        Quantiles of historical error = forecast − actual over all matched hours. Above zero (amber): wind came in below the forecast. Below zero
        (teal): wind exceeded the forecast.
      </figcaption>
    </figure>
  );
}

/** Day-average build-up from baseline to the conservative estimate. Bias is inside the buffer, not added to it. */
export function BufferBuildUp({ risk }: { risk: RiskAssessment }) {
  const base = risk.mean_baseline_mw ?? 0;
  const adj = risk.mean_bias_adjusted_mw ?? base;
  const cons = risk.mean_conservative_mw ?? base;
  const max = Math.max(base, adj, cons, 1);
  const w = (v: number) => `${Math.max(0, Math.min(100, (v / max) * 100))}%`;
  const rows = [
    { label: "Baseline forecast", value: base, bar: "bg-wind", note: "WINDFOR vintage at the cutoff" },
    { label: "Bias-adjusted", value: adj, bar: "bg-info", note: `${mw(risk.bias_adjustment_mw, { signed: true })} MW (removes the average historical error)` },
    {
      label: `Conservative (P${risk.percentile})`,
      value: cons,
      bar: "bg-risk",
      note: `${mw(-risk.shortfall_buffer_mw, { signed: true })} MW vs baseline (= bias ${mw(-risk.bias_mw, { signed: true })} + extra margin ${mw(-risk.residual_buffer_mw, { signed: true })})`,
    },
  ];
  return (
    <div className="space-y-3" aria-label="Baseline to conservative build-up, day average in MW">
      {rows.map((r) => (
        <div key={r.label}>
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium text-ink">{r.label}</span>
            <span className="num font-semibold text-ink">{mw(r.value)} MW</span>
          </div>
          <div className="mt-1 h-3 w-full rounded-sm bg-line-soft">
            <div className={`h-full rounded-sm ${r.bar}`} style={{ width: w(r.value) }} />
          </div>
          <p className="mt-0.5 text-xs text-ink-soft">{r.note}</p>
        </div>
      ))}
      <p className="text-xs text-ink-faint">Day averages across the available delivery hours. Hourly values are in the table below.</p>
    </div>
  );
}
