import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { mw } from "../../lib/format";
import type { ForecastHour } from "../../types/api";

interface Point {
  label: string;
  forecast: number | null;
  adjusted: number | null;
  conservative: number | null;
  band: [number, number] | null;
  missing: number | null;
}

export function buildForecastSeries(hours: ForecastHour[]): { points: Point[]; yMax: number } {
  const finite = hours.flatMap((h) => [h.forecast_mw, h.interval_high_mw]).filter((v): v is number => v !== null);
  const yMax = Math.max(1000, Math.ceil((Math.max(0, ...finite) * 1.08) / 1000) * 1000);
  const points = hours.map<Point>((h) => ({
    label: h.local_label,
    forecast: h.forecast_mw,
    adjusted: h.bias_adjusted_mw,
    conservative: h.conservative_mw,
    band: h.interval_low_mw !== null && h.interval_high_mw !== null ? [h.interval_low_mw, h.interval_high_mw] : null,
    missing: h.missing ? yMax : null,
  }));
  return { points, yMax };
}

const LABELS: Record<string, string> = {
  forecast: "Baseline forecast",
  adjusted: "Bias-adjusted",
  conservative: "Conservative (baseline − buffer)",
  band: "Uncertainty range",
  missing: "No forecast published",
};

export function ForecastChart({ hours, confidencePct }: { hours: ForecastHour[]; confidencePct: number }) {
  const { points, yMax } = buildForecastSeries(hours);
  const hasMissing = points.some((p) => p.missing !== null);
  return (
    <figure aria-label="Hourly wind generation forecast with uncertainty range, UK local time" className="m-0">
      <div className="h-[340px] w-full">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={points} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid stroke="#e8edf2" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#46556b" }} interval="preserveStartEnd" minTickGap={28} tickLine={false} axisLine={{ stroke: "#cfd7e0" }} label={{ value: "Hour starting (UK local time)", position: "insideBottom", offset: -2, fontSize: 12, fill: "#7a8799" }} height={44} />
            <YAxis domain={[0, yMax]} tick={{ fontSize: 12, fill: "#46556b" }} tickFormatter={(v: number) => v.toLocaleString("en-GB")} tickLine={false} axisLine={false} width={64} label={{ value: "MW", angle: -90, position: "insideLeft", fontSize: 12, fill: "#7a8799" }} />
            <Tooltip
              formatter={(value, name) => {
                const key = String(name);
                if (Array.isArray(value)) return [`${mw(Number(value[0]))} – ${mw(Number(value[1]))} MW`, LABELS[key] ?? key];
                return [`${mw(Number(value))} MW`, LABELS[key] ?? key];
              }}
              labelFormatter={(l) => `${String(l)} UK`}
              contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#dde3ea" }}
              itemSorter={() => 0}
            />
            <Legend formatter={(v: string) => <span className="text-xs text-ink-soft">{v === "band" ? `${LABELS.band} (${confidencePct.toFixed(0)}%)` : (LABELS[v] ?? v)}</span>} wrapperStyle={{ paddingTop: 4 }} />
            {hasMissing && <Bar dataKey="missing" fill="#e3e8ee" barSize={22} isAnimationActive={false} legendType="rect" />}
            <Area dataKey="band" stroke="none" fill="#0f766e" fillOpacity={0.14} isAnimationActive={false} connectNulls={false} legendType="rect" />
            <Line dataKey="forecast" stroke="#0f766e" strokeWidth={2.6} dot={false} isAnimationActive={false} connectNulls={false} />
            <Line dataKey="adjusted" stroke="#1d4ed8" strokeWidth={1.4} strokeDasharray="2 3" dot={false} isAnimationActive={false} connectNulls={false} />
            <Line dataKey="conservative" stroke="#b45309" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
