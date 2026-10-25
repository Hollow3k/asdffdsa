import { Badge, Card, InfoTip, Stat } from "../../components/ui";
import { fmtDate, fmtUkDateTime, int, mw, pct } from "../../lib/format";
import { METRIC_TIPS } from "../../lib/metricTips";
import type { CalibrationRef, DecisionResponse, ErrorMetrics, ForecastHour, ForecastInfo } from "../../types/api";

export function ForecastProvenance({ forecast, cutoffLocal }: { forecast: ForecastInfo; cutoffLocal: string }) {
  return (
    <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <Item label="Source">Elexon BMRS · {forecast.dataset}</Item>
      <Item label="Forecast published">
        <strong className="num">{fmtUkDateTime(forecast.vintage_publish_time_utc)}</strong> UK
      </Item>
      <Item label="Eligible at cutoff">
        {fmtUkDateTime(cutoffLocal)} UK{" "}
        <Badge tone="ok">latest at or before cutoff</Badge>
      </Item>
      <Item label="Coverage">
        <span className="num">
          {forecast.available_hours} / {forecast.expected_hours}
        </span>{" "}
        hours {forecast.is_complete ? <Badge tone="ok">complete</Badge> : <Badge tone="warn">incomplete</Badge>}
        {forecast.fallback_used && <Badge tone="warn">earlier vintage used</Badge>}
      </Item>
    </dl>
  );
}

function Item({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] font-medium uppercase tracking-wide text-ink-soft">{label}</dt>
      <dd className="mt-0.5 text-ink">{children}</dd>
    </div>
  );
}

export function ReliabilityPanel({ metrics, calibration }: { metrics: ErrorMetrics; calibration: CalibrationRef }) {
  const unavailable = metrics.n === 0;
  return (
    <Card
      title="Reliability of comparable past forecasts"
      subtitle={
        <>
          Calibration v{calibration.version} · {fmtDate(calibration.effective_start_date)} – {fmtDate(calibration.effective_end_date)} ·{" "}
          <span className="num">{int(metrics.n)}</span> matched hours
          <InfoTip text={METRIC_TIPS.pairs} />
        </>
      }
    >
      {unavailable ? (
        <p className="text-sm text-ink-soft">Metrics unavailable: no matched hours.</p>
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
            <Stat label="MAE" value={mw(metrics.mae_mw)} unit="MW" tip={METRIC_TIPS.mae} />
            <Stat label="RMSE" value={mw(metrics.rmse_mw)} unit="MW" tip={METRIC_TIPS.rmse} />
            <Stat
              label="Bias"
              value={mw(metrics.bias_mw, { signed: true })}
              unit="MW"
              tip={METRIC_TIPS.bias}
              hint={(metrics.bias_mw ?? 0) > 0 ? "forecasts too high on average" : "forecasts too low on average"}
            />
            <Stat label="P90 absolute error" value={mw(metrics.p90_abs_error_mw)} unit="MW" tip={METRIC_TIPS.p90abs} />
            <Stat label="P95 absolute error" value={mw(metrics.p95_abs_error_mw)} unit="MW" tip={METRIC_TIPS.p95abs} />
            <Stat label="Over-forecast hours" value={pct(metrics.share_overforecast)} tip={METRIC_TIPS.share} />
          </dl>
          <div className="mt-4 border-t border-line-soft pt-4">
            <p className="mb-2 text-[12px] font-medium uppercase tracking-wide text-ink-soft">Over-forecast tail (wind shortfall)</p>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3">
              <Stat label="P90 positive error" value={mw(metrics.p90_positive_error_mw)} unit="MW" tip={METRIC_TIPS.p90pos} tone="risk" />
              <Stat label="P95 positive error" value={mw(metrics.p95_positive_error_mw)} unit="MW" tip={METRIC_TIPS.p95pos} tone="risk" />
              <Stat label="Matched / excluded" value={`${int(calibration.pairs_used)}`} hint={calibration.pairs_excluded_not_yet_available ? `${int(calibration.pairs_excluded_not_yet_available)} excluded: not yet observed at cutoff` : "none excluded"} />
            </dl>
          </div>
        </>
      )}
    </Card>
  );
}

export function ForecastTable({ hours }: { hours: ForecastHour[] }) {
  return (
    <div className="max-h-[420px] overflow-auto rounded-md border border-line-soft">
      <table className="w-full min-w-[620px] border-collapse text-sm">
        <caption className="sr-only">Hourly forecast values in MW, UK local time</caption>
        <thead className="sticky top-0 bg-canvas text-left text-[12px] uppercase tracking-wide text-ink-soft">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Hour (UK)</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Forecast MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Bias-adjusted MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Conservative MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Range MW</th>
          </tr>
        </thead>
        <tbody>
          {hours.map((h) => (
            <tr key={h.start_utc} className="border-t border-line-soft odd:bg-white even:bg-[#fafbfc]">
              <th scope="row" className="num px-3 py-1.5 text-left font-medium">{h.local_label}</th>
              {h.missing ? (
                <td colSpan={4} className="px-3 py-1.5 text-right text-short">No forecast published for this hour</td>
              ) : (
                <>
                  <td className="num px-3 py-1.5 text-right">{mw(h.forecast_mw)}</td>
                  <td className="num px-3 py-1.5 text-right text-ink-soft">{mw(h.bias_adjusted_mw)}</td>
                  <td className="num px-3 py-1.5 text-right font-medium text-risk">{mw(h.conservative_mw)}</td>
                  <td className="num px-3 py-1.5 text-right text-ink-soft">
                    {mw(h.interval_low_mw)} – {mw(h.interval_high_mw)}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ExplanationPanel({ d }: { d: DecisionResponse }) {
  return (
    <Card title="Why this estimate" subtitle="How the result was derived, from which data, and what it does not cover">
      <p className="text-[15px] font-medium text-ink">{d.explanation.headline}</p>
      <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-relaxed text-ink-soft marker:text-ink-faint">
        {d.explanation.steps.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ol>
      <div className="mt-4 rounded-md border border-risk/30 bg-risk-soft px-4 py-3 text-sm text-[#7c3a06]">
        <p className="font-semibold">Decision support only</p>
        <p className="mt-0.5">{d.procurement_note}</p>
      </div>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer font-medium text-wind">Limitations</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-soft">
          {d.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      </details>
      <details className="mt-3 text-sm">
        <summary className="cursor-pointer font-medium text-wind">Metric definitions</summary>
        <dl className="mt-2 space-y-1.5 text-ink-soft">
          {Object.entries(d.explanation.definitions).map(([k, v]) => (
            <div key={k}>
              <dt className="inline font-mono text-xs text-ink">{k}</dt>
              <dd className="ml-2 inline">{v}</dd>
            </div>
          ))}
        </dl>
      </details>
    </Card>
  );
}
