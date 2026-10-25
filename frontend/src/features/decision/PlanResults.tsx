import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Button, cx } from "../../components/ui";
import { fmtUkDateTime, fmtWeekdayDate, int, mw } from "../../lib/format";
import type { DecisionResponse, PlanBasis, PlanHour, PlanScenario, ProcurementResponse } from "../../types/api";

// ---------------------------------------------------------------------------------------------------
// helpers (exported for tests)
// ---------------------------------------------------------------------------------------------------

export function hourView(h: PlanHour, basis: PlanBasis): { wind: number | null; buy: number | null; surplus: number | null } {
  switch (basis) {
    case "forecast":
      return { wind: h.wind_forecast_mw, buy: h.buy_forecast_mw, surplus: h.surplus_forecast_mw };
    case "expected":
      return { wind: h.wind_expected_mw, buy: h.buy_expected_mw, surplus: h.surplus_expected_mw };
    case "cautious":
      return { wind: h.wind_cautious_mw, buy: h.buy_cautious_mw, surplus: h.surplus_cautious_mw };
  }
}

const BASIS_NAME: Record<PlanBasis, string> = {
  forecast: "wind as published",
  expected: "expected wind",
  cautious: "cautious wind",
};

export function scenarioLabel(s: PlanScenario, percentile: number): string {
  return s.key === "cautious" ? `Cautious (P${percentile})` : s.label;
}

export function planToCsv(plan: ProcurementResponse, basis: PlanBasis): string {
  const rows = [["hour_uk", "demand_mw", "existing_contracts_mw", `wind_mw_${basis}`, "to_buy_mw", "surplus_wind_mw"]];
  for (const h of plan.hours) {
    const v = hourView(h, basis);
    const f = (x: number | null) => (x === null ? "" : x.toFixed(1));
    rows.push([h.local_label, f(h.demand_mw), f(h.contracted_mw), f(v.wind), f(v.buy), f(v.surplus)]);
  }
  return rows.map((r) => r.join(",")).join("\n") + "\n";
}

export function planSummary(plan: ProcurementResponse, basis: PlanBasis, decision: DecisionResponse | null): string {
  const s = plan.scenarios.find((x) => x.key === basis)!;
  const lines = [
    `Wind-backed purchase plan for ${fmtWeekdayDate(plan.delivery_date)} (UK)`,
    `Case: ${scenarioLabel(s, plan.percentile)}. ${s.description}`,
    `BUY ${mw(s.buy_total_mwh)} MWh (average ${mw(s.avg_buy_mw)} MW, peak ${mw(s.peak_buy_mw)} MW${s.peak_buy_hour ? ` at ${s.peak_buy_hour}` : ""}), buying in ${s.hours_with_buy} of ${plan.hours_planned} hours.`,
    `Demand ${mw(plan.demand_total_mwh)} MWh; existing contracts ${mw(plan.contracted_total_mwh)} MWh; wind counted ${mw(s.wind_used_mwh)} MWh at ${plan.wind_share_pct}% of GB wind.`,
    `Forecast: Elexon WINDFOR published ${fmtUkDateTime(plan.forecast.vintage_publish_time_utc)} UK (cutoff ${plan.cutoff.cutoff_time} UK the day before).`,
    `Calibration v${plan.calibration.version}: ${plan.calibration.pairs_used} hourly pairs.`,
  ];
  if (plan.hours_unplanned > 0) lines.push(`${plan.hours_unplanned} hour(s) had no forecast and are excluded.`);
  if (decision) lines.push(`National wind shortfall buffer at P${plan.percentile}: ${mw(decision.risk.shortfall_buffer_mw)} MW.`);
  lines.push("Decision support only: excludes prices, imbalance costs, losses and demand uncertainty.");
  return lines.join("\n");
}

function download(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------------------------------
// Hero: the number to buy
// ---------------------------------------------------------------------------------------------------

export function PlanHero({
  plan,
  basis,
  onBasis,
  decision,
  embedded = false,
}: {
  plan: ProcurementResponse;
  basis: PlanBasis;
  onBasis: (b: PlanBasis) => void;
  decision: DecisionResponse | null;
  /** When true, render without the outer card chrome (it sits inside the result header band). */
  embedded?: boolean;
}) {
  const s = plan.scenarios.find((x) => x.key === basis)!;
  const recommended = basis === plan.recommended_basis;
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(planSummary(plan, basis, decision));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const Wrapper = embedded ? "div" : "section";
  return (
    <Wrapper aria-label="Recommended purchase" className={embedded ? "border-t border-line-soft" : "overflow-hidden rounded-xl border border-line bg-surface"}>
      <div className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-center">
        <div>
          <p className="text-[12px] font-medium uppercase tracking-wide text-ink-soft">
            {recommended ? "Recommended purchase" : `Purchase if ${BASIS_NAME[basis]}`}
            {!embedded && <> · {fmtWeekdayDate(plan.delivery_date)}</>}
          </p>
          <p className="mt-1.5 flex items-baseline gap-2">
            <span className="num text-6xl font-semibold leading-none tracking-tight text-risk" data-testid="buy-total">
              {mw(s.buy_total_mwh)}
            </span>
            <span className="text-xl text-ink-soft">MWh</span>
          </p>
          {s.buy_total_mwh > 0 ? (
            <p className="mt-2 text-sm text-ink-soft">
              <strong className="num font-semibold text-ink">{mw(s.avg_buy_mw)} MW</strong> on average, peaking at{" "}
              <strong className="num font-semibold text-ink">{mw(s.peak_buy_mw)} MW</strong>
              {s.peak_buy_hour && <> at {s.peak_buy_hour}</>}. Buying in {s.hours_with_buy} of {plan.hours_planned} hours.
            </p>
          ) : (
            <p className="mt-2 text-sm text-ink-soft">No purchase is needed in this case: wind plus your existing contracts covers your demand in every planned hour.</p>
          )}
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-ink-soft">
            {basis === "cautious" ? (
              <>
                On top of wind and your existing contracts, this covers your demand even if wind falls short by the P{plan.percentile} historical amount.
              </>
            ) : basis === "expected" ? (
              <>This assumes wind lands at the bias-corrected forecast. It gives no protection if wind comes in lower.</>
            ) : (
              <>This trusts the published forecast as is, with no correction for its historical error. Compare with the cautious case.</>
            )}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => download(`wind-plan-${plan.delivery_date}-${basis}.csv`, planToCsv(plan, basis))}>Download CSV</Button>
            <Button onClick={() => void copy()} aria-live="polite">
              {copied ? "Copied ✓" : "Copy summary"}
            </Button>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-5">
          <Mini label="Your demand" value={`${mw(plan.demand_total_mwh)} MWh`} />
          <Mini label="Existing contracts" value={`${mw(plan.contracted_total_mwh)} MWh`} />
          <Mini
            label="Covered by wind"
            value={s.wind_cover_pct === null ? "—" : `${s.wind_cover_pct.toFixed(0)}%`}
            hint={`${mw(s.wind_used_mwh)} MWh at ${plan.wind_share_pct}% of GB wind`}
          />
          <Mini label="Surplus wind" value={`${mw(s.surplus_wind_mwh)} MWh`} hint={s.hours_with_surplus ? `in ${s.hours_with_surplus} hour(s), not carried over` : "none"} />
        </dl>
      </div>

      <div className="border-t border-line-soft bg-canvas/60 px-6 py-4">
        <div role="radiogroup" aria-label="Wind assumption" className="grid gap-2.5 sm:grid-cols-3">
          {plan.scenarios.map((sc) => {
            const selected = sc.key === basis;
            return (
              <button
                key={sc.key}
                type="button"
                role="radio"
                aria-checked={selected}
                onClick={() => onBasis(sc.key)}
                className={cx(
                  "rounded-lg border bg-white px-4 py-3 text-left transition-colors",
                  selected ? "border-wind ring-1 ring-wind" : "border-line hover:border-wind/60",
                )}
              >
                <span className="flex items-center justify-between gap-2 text-sm font-semibold text-ink">
                  {scenarioLabel(sc, plan.percentile)}
                  {sc.key === plan.recommended_basis && <Badge tone="ok">recommended</Badge>}
                </span>
                <span className="num mt-0.5 block text-xl font-semibold text-ink">{mw(sc.buy_total_mwh)} MWh</span>
                <span className="mt-0.5 block text-xs leading-snug text-ink-soft">{sc.description}</span>
              </button>
            );
          })}
        </div>
        <p className="mt-2.5 text-xs text-ink-soft">
          Planning for the cautious case buys <strong className="num text-ink">{mw(plan.risk_cover_mwh)} MWh</strong> more than the expected case. That is the price of protection against a wind shortfall.
        </p>
      </div>
    </Wrapper>
  );
}

function Mini({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <dt className="text-[12px] font-medium uppercase tracking-wide text-ink-soft">{label}</dt>
      <dd className="mt-0.5">
        <span className="num text-xl font-semibold text-ink">{value}</span>
        {hint && <span className="mt-0.5 block text-xs text-ink-soft">{hint}</span>}
      </dd>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------
// Chart + table
// ---------------------------------------------------------------------------------------------------

export function buildPlanSeries(hours: PlanHour[], basis: PlanBasis) {
  return hours.map((h) => {
    const v = hourView(h, basis);
    if (!h.planned || v.wind === null || v.buy === null) {
      return { label: h.local_label, contracts: null, windUsed: null, buy: null, demand: h.demand_mw, wind: null };
    }
    const contractsUsed = Math.min(h.contracted_mw, h.demand_mw);
    const windUsed = Math.min(v.wind, Math.max(0, h.demand_mw - contractsUsed));
    return { label: h.local_label, contracts: contractsUsed, windUsed, buy: v.buy, demand: h.demand_mw, wind: v.wind };
  });
}

const SERIES_LABEL: Record<string, string> = {
  contracts: "Existing contracts",
  windUsed: "Wind (counted)",
  buy: "To buy",
  demand: "Your demand",
  wind: "Wind available",
};

export function PlanChart({ plan, basis }: { plan: ProcurementResponse; basis: PlanBasis }) {
  const data = buildPlanSeries(plan.hours, basis);
  const hasContracts = plan.contracted_total_mwh > 0;
  return (
    <figure className="m-0" aria-label="How each hour of demand is covered: contracts, wind and purchase">
      <div className="h-[340px] w-full">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={data} margin={{ top: 8, right: 16, left: 4, bottom: 4 }}>
            <CartesianGrid stroke="#e8edf2" vertical={false} />
            <XAxis dataKey="label" interval="preserveStartEnd" minTickGap={28} tick={{ fontSize: 12, fill: "#46556b" }} tickLine={false} height={44} label={{ value: "Hour starting (UK local time)", position: "insideBottom", offset: -2, fontSize: 12, fill: "#7a8799" }} />
            <YAxis tick={{ fontSize: 12, fill: "#46556b" }} tickFormatter={(v: number) => v.toLocaleString("en-GB")} tickLine={false} axisLine={false} width={64} label={{ value: "MW", angle: -90, position: "insideLeft", fontSize: 12, fill: "#7a8799" }} />
            <Tooltip
              formatter={(v, n) => [`${mw(Number(v))} MW`, SERIES_LABEL[String(n)] ?? String(n)]}
              labelFormatter={(l) => `${String(l)} UK`}
              contentStyle={{ fontSize: 12, borderRadius: 6, borderColor: "#dde3ea" }}
            />
            <Legend formatter={(v: string) => <span className="text-xs text-ink-soft">{SERIES_LABEL[v] ?? v}</span>} />
            {hasContracts && <Bar dataKey="contracts" stackId="cover" fill="#94a3b8" isAnimationActive={false} />}
            <Bar dataKey="windUsed" stackId="cover" fill="#0f766e" fillOpacity={0.85} isAnimationActive={false} />
            <Bar dataKey="buy" stackId="cover" fill="#b45309" isAnimationActive={false} />
            <Line dataKey="demand" stroke="#0f1b2d" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="wind" stroke="#0f766e" strokeWidth={1.5} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-1 text-xs text-ink-soft">
        Each bar is one hour of your demand, split into what existing contracts, wind ({BASIS_NAME[basis]}) and a new purchase cover. Dashed line: wind available; where it rises above the demand line, the extra is surplus.
      </figcaption>
    </figure>
  );
}

export function PlanTable({ plan, basis }: { plan: ProcurementResponse; basis: PlanBasis }) {
  const s = plan.scenarios.find((x) => x.key === basis)!;
  return (
    <div className="max-h-[460px] overflow-auto rounded-lg border border-line-soft">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">Hourly purchase plan in MW, UK local time</caption>
        <thead className="sticky top-0 bg-canvas text-left text-[12px] uppercase tracking-wide text-ink-soft">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Hour (UK)</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Demand MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Contracts MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Wind MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">To buy MW</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Surplus wind MW</th>
          </tr>
        </thead>
        <tbody>
          {plan.hours.map((h) => {
            const v = hourView(h, basis);
            return (
              <tr key={h.start_utc} className="border-t border-line-soft odd:bg-white even:bg-[#fafbfc]">
                <th scope="row" className="num px-3 py-1.5 text-left font-medium">{h.local_label}</th>
                <td className="num px-3 py-1.5 text-right">{mw(h.demand_mw)}</td>
                <td className="num px-3 py-1.5 text-right text-ink-soft">{mw(Math.min(h.contracted_mw, h.demand_mw))}</td>
                {h.planned ? (
                  <>
                    <td className="num px-3 py-1.5 text-right text-wind">{mw(v.wind)}</td>
                    <td className={cx("num px-3 py-1.5 text-right font-semibold", (v.buy ?? 0) > 0 ? "text-risk" : "text-ink-faint")}>{mw(v.buy)}</td>
                    <td className="num px-3 py-1.5 text-right text-ink-soft">{(v.surplus ?? 0) > 0 ? mw(v.surplus) : "—"}</td>
                  </>
                ) : (
                  <td colSpan={3} className="px-3 py-1.5 text-right text-short">No forecast for this hour: not planned</td>
                )}
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-line bg-canvas font-semibold">
            <th scope="row" className="px-3 py-2 text-left">Total MWh</th>
            <td className="num px-3 py-2 text-right">{mw(plan.demand_total_mwh)}</td>
            <td className="num px-3 py-2 text-right">{mw(plan.contracted_total_mwh)}</td>
            <td className="num px-3 py-2 text-right">{mw(s.wind_total_mwh)}</td>
            <td className="num px-3 py-2 text-right text-risk">{mw(s.buy_total_mwh)}</td>
            <td className="num px-3 py-2 text-right">{int(Math.round(s.surplus_wind_mwh))}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
