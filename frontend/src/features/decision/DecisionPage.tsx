import { useEffect, useState } from "react";
import { useApp } from "../../AppContext";
import { Tabs, type TabDef } from "../../components/Tabs";
import { Badge, Banner, Button, Card, LoadingBlock, Stat, WarningList } from "../../components/ui";
import { EmptyState, RemoteError } from "../../components/states";
import { fmtDate, fmtWeekdayDate, mw } from "../../lib/format";
import { METRIC_TIPS } from "../../lib/metricTips";
import { useRemote } from "../../lib/useRemote";
import { api } from "../../services/api";
import type { DecisionResponse, PlanBasis, ProcurementResponse } from "../../types/api";
import { ForecastChart } from "./ForecastChart";
import { ExplanationPanel, ForecastProvenance, ForecastTable, ReliabilityPanel } from "./panels";
import { PlanChart, PlanHero, PlanTable } from "./PlanResults";
import { PlanInputs } from "./PlanInputs";
import { loadForm, saveForm, type AnalysisRequest, type PlanForm } from "./planForm";
import { BufferBuildUp, ErrorQuantileChart } from "./RiskCharts";

type TabId = "plan" | "wind" | "method";

export function DecisionPage() {
  const { config, active, activeLoading, activeError, refreshActive, navigate, defaultDeliveryDate } = useApp();
  const [form, setForm] = useState<PlanForm>(loadForm);
  // The single source of truth for fetching. Set ONLY when the user submits the inputs panel.
  const [loaded, setLoaded] = useState<AnalysisRequest | null>(null);
  const [basis, setBasis] = useState<PlanBasis>("cautious");
  const [tab, setTab] = useState<TabId | null>(null);

  useEffect(() => saveForm(form), [form]);

  const canLoad = !!active && !!loaded;
  const key = loaded && active ? `${loaded.date}|${loaded.cutoff}|${loaded.percentile}|${active.id}` : "none";
  const decision = useRemote<DecisionResponse>(
    canLoad ? () => api.decision(loaded!.date, loaded!.cutoff, loaded!.percentile) : null,
    key,
  );
  const plan = useRemote<ProcurementResponse>(
    canLoad && loaded!.plan ? () => api.plan(loaded!.date, { cutoff: loaded!.cutoff, percentile: loaded!.percentile, ...loaded!.plan! }) : null,
    `${key}|${JSON.stringify(loaded?.plan)}`,
  );

  if (activeLoading) return <LoadingBlock label="Loading active calibration…" height={200} />;
  if (activeError) return <RemoteError error={activeError} onRetry={refreshActive} title="Could not load the active calibration" />;
  if (!active)
    return (
      <EmptyState
        title="Set up your calibration first"
        action={<Button variant="primary" onClick={() => navigate("calibration")}>Run initial calibration</Button>}
      >
        Purchase volumes need to know how far off past day-ahead wind forecasts were. Run the initial calibration (1 Oct – 31 Dec 2025 by default). It takes a few seconds,
        is saved, and is reused every time you open the dashboard.
      </EmptyState>
    );

  const decisionData = "data" in decision ? (decision.data ?? null) : null;
  const planData = "data" in plan ? (plan.data ?? null) : null;
  const loading = decision.status === "loading";

  return (
    <div className="grid gap-6 lg:grid-cols-[360px_minmax(0,1fr)] lg:items-start">
      <aside className="lg:sticky lg:top-4 lg:self-start">
        <PlanInputs config={config} defaultDate={defaultDeliveryDate} form={form} loaded={loaded} busy={loading} onForm={setForm} onSubmit={setLoaded} />
        <p className="mt-3 px-1 text-xs text-ink-faint">
          Calibration <strong className="font-semibold text-ink-soft">v{active.version}</strong>, {fmtDate(active.start_date)} – {fmtDate(active.end_date)}. Your numbers are kept in this browser only.
        </p>
      </aside>

      <div className="min-w-0 space-y-5">
        {!loaded && <StartState decisionActive />}
        {loaded && loading && !decisionData && <LoadingBlock label="Selecting the eligible forecast and computing risk…" height={420} />}
        {loaded && decision.status === "error" && <RemoteError error={decision.error} onRetry={decision.reload} />}

        {decisionData && (
          <>
            <ResultHeader decision={decisionData} plan={plan} planData={planData} basis={basis} onBasis={setBasis} requestedPlan={!!loaded?.plan} />
            <div aria-busy={loading} className={loading ? "opacity-60 transition-opacity" : undefined}>
              <WarningList warnings={planData ? planData.warnings : decisionData.warnings} />
              <div className="mt-5">
                <ResultTabs decision={decisionData} plan={planData} planStatus={plan.status} basis={basis} requestedPlan={!!loaded?.plan} tab={tab} onTab={setTab} />
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------

function StartState({ decisionActive }: { decisionActive: boolean }) {
  if (!decisionActive) return null;
  return (
    <section className="rounded-2xl border border-dashed border-wind/40 bg-wind-soft/30 px-8 py-14 text-center" aria-label="Getting started">
      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-wind/10 text-wind">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 15c5-9 9 4 14-5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </div>
      <h2 className="mt-4 text-lg font-semibold tracking-tight text-ink">Set your inputs, then load the analysis</h2>
      <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-ink-soft">
        Choose a delivery day and cutoff, optionally enter your expected demand, and press <strong className="text-ink">Load analysis</strong>. Nothing is fetched until you do.
      </p>
    </section>
  );
}

/** Hero band in the reference style: a dark gradient header carrying the key result. */
function ResultHeader({
  decision,
  plan,
  planData,
  basis,
  onBasis,
  requestedPlan,
}: {
  decision: DecisionResponse;
  plan: ReturnType<typeof useRemote<ProcurementResponse>>;
  planData: ProcurementResponse | null;
  basis: PlanBasis;
  onBasis: (b: PlanBasis) => void;
  requestedPlan: boolean;
}) {
  const r = decision.risk;
  return (
    <section aria-label="Result summary" className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm">
      <div className="relative bg-gradient-to-br from-[#0f3d39] via-[#0f766e] to-[#15b8a6] px-6 py-5 text-white">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-white/70">Delivery day · GB national wind</p>
            <h2 className="mt-0.5 text-2xl font-semibold tracking-tight">{fmtWeekdayDate(decision.delivery_date)}</h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="rounded-full bg-white/15 px-3 py-1 font-medium">Cutoff {decision.cutoff.cutoff_time} UK</span>
            <span className="rounded-full bg-white/15 px-3 py-1 font-medium">P{r.percentile}</span>
            {decision.forecast.is_complete ? (
              <span className="rounded-full bg-white/20 px-3 py-1 font-medium">24/24 hours</span>
            ) : (
              <span className="rounded-full bg-amber-300/30 px-3 py-1 font-medium text-amber-50">{decision.forecast.available_hours}/{decision.forecast.expected_hours} hours</span>
            )}
          </div>
        </div>
        <dl className="mt-5 grid gap-5 sm:grid-cols-3">
          <HeroStat label="Avg wind forecast" value={mw(r.mean_baseline_mw)} unit="MW" sub="as published" />
          <HeroStat label="Avg cautious wind" value={mw(r.mean_conservative_mw)} unit="MW" sub={`P${r.percentile} case`} />
          <HeroStat label="Shortfall buffer" value={mw(r.shortfall_buffer_mw)} unit="MW" sub="per hour, GB total" testId="shortfall-buffer" />
        </dl>
      </div>

      {requestedPlan ? (
        <PlanBand plan={plan} planData={planData} basis={basis} onBasis={onBasis} decision={decision} />
      ) : (
        <div className="px-6 py-4">
          <p className="text-sm text-ink-soft">
            No demand entered, so no purchase volume was calculated. Add your expected demand on the left and reload to get a recommended buy.
          </p>
        </div>
      )}
    </section>
  );
}

function HeroStat({ label, value, unit, sub, testId }: { label: string; value: string; unit: string; sub: string; testId?: string }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wide text-white/65">{label}</dt>
      <dd className="mt-0.5">
        <span className="num text-3xl font-semibold tracking-tight" data-testid={testId}>{value}</span>
        <span className="ml-1 text-sm text-white/70">{unit}</span>
        <span className="mt-0.5 block text-xs text-white/60">{sub}</span>
      </dd>
    </div>
  );
}

function PlanBand({
  plan,
  planData,
  basis,
  onBasis,
  decision,
}: {
  plan: ReturnType<typeof useRemote<ProcurementResponse>>;
  planData: ProcurementResponse | null;
  basis: PlanBasis;
  onBasis: (b: PlanBasis) => void;
  decision: DecisionResponse;
}) {
  if (plan.status === "error") {
    return (
      <div className="px-6 py-4">
        <RemoteError error={plan.error} onRetry={plan.reload} title="Could not calculate the purchase volume" />
      </div>
    );
  }
  if (!planData) {
    return (
      <div className="px-6 py-6">
        <LoadingBlock label="Calculating your purchase volume…" height={120} />
      </div>
    );
  }
  return (
    <div aria-busy={plan.status === "loading"} className={plan.status === "loading" ? "opacity-60 transition-opacity" : undefined}>
      <PlanHero plan={planData} basis={basis} onBasis={onBasis} decision={decision} embedded />
    </div>
  );
}

function ResultTabs({
  decision,
  plan,
  planStatus,
  basis,
  requestedPlan,
  tab,
  onTab,
}: {
  decision: DecisionResponse;
  plan: ProcurementResponse | null;
  planStatus: string;
  basis: PlanBasis;
  requestedPlan: boolean;
  tab: TabId | null;
  onTab: (t: TabId) => void;
}) {
  const effectiveTab: TabId = tab ?? (requestedPlan ? "plan" : "wind");
  const tabs: TabDef<TabId>[] = [
    { id: "plan", label: "Hourly plan", badge: requestedPlan ? undefined : <Badge tone="neutral">needs demand</Badge> },
    { id: "wind", label: "Wind outlook & risk" },
    { id: "method", label: "How it's calculated" },
  ];
  return (
    <Tabs tabs={tabs} value={effectiveTab} onChange={onTab} label="Result sections">
      {effectiveTab === "plan" && <PlanTab plan={plan} basis={basis} requestedPlan={requestedPlan} loading={planStatus === "loading"} />}
      {effectiveTab === "wind" && <WindTab d={decision} />}
      {effectiveTab === "method" && <MethodTab d={decision} plan={plan} />}
    </Tabs>
  );
}

function PlanTab({ plan, basis, requestedPlan, loading }: { plan: ProcurementResponse | null; basis: PlanBasis; requestedPlan: boolean; loading: boolean }) {
  if (!requestedPlan)
    return <EmptyState title="No demand entered">Enter your expected demand on the left and reload to see how each hour is covered by contracts, wind and a new purchase.</EmptyState>;
  if (!plan) return <LoadingBlock label={loading ? "Calculating…" : "Loading…"} height={240} />;
  return (
    <div className="space-y-5">
      <Card title="How each hour is covered" subtitle="Existing contracts and wind first, then what you need to buy">
        <PlanChart plan={plan} basis={basis} />
        {plan.hours_unplanned > 0 && (
          <div className="mt-3">
            <Banner kind="warning" title={`${plan.hours_unplanned} hour(s) not planned`}>
              The forecast has no value for these hours, so no purchase can be worked out for them. Totals exclude them.
            </Banner>
          </div>
        )}
      </Card>
      <Card title="Hour by hour" subtitle="Exact values for the selected wind case">
        <PlanTable plan={plan} basis={basis} />
      </Card>
    </div>
  );
}

function WindTab({ d }: { d: DecisionResponse }) {
  const r = d.risk;
  const hasForecast = d.forecast.available_hours > 0;
  return (
    <div className="space-y-5">
      <Card
        title="Hourly wind forecast"
        subtitle={`Forecast available at the ${d.cutoff.cutoff_time} UK cutoff, GB national, hours in UK local time`}
      >
        <ForecastProvenance forecast={d.forecast} cutoffLocal={d.cutoff.utc} />
        <div className="mt-4">
          {hasForecast ? (
            <ForecastChart hours={d.hours} confidencePct={r.interval_confidence_pct} />
          ) : (
            <Banner kind="error" title="No forecast values">The selected vintage contains no hours for this delivery day.</Banner>
          )}
        </div>
        {!d.forecast.is_complete && (
          <div className="mt-3">
            <Banner kind="warning" title={`Missing hours: ${d.forecast.missing_hours.join(", ")} UK`}>
              These hours are shown as gaps. They are not filled from actuals, later forecasts or defaults.
            </Banner>
          </div>
        )}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <ReliabilityPanel metrics={d.metrics} calibration={d.calibration} />
        <Card title="Uncertainty and shortfall risk" subtitle={`${r.interval_confidence_pct.toFixed(0)}% range uses P${100 - r.percentile} to P${r.percentile} of historical error`}>
          <dl className="mb-4 grid grid-cols-2 gap-4">
            <Stat label={`P${r.percentile} signed error`} value={mw(r.shortfall_quantile_mw, { signed: true })} unit="MW" tip={METRIC_TIPS.shortfall} hint="forecast − actual, all hours" />
            <Stat label="Shortfall buffer" value={mw(r.shortfall_buffer_mw)} unit="MW" tone="risk" hint="max(0, P-error)" />
          </dl>
          <ErrorQuantileChart metrics={d.metrics} percentile={r.percentile} />
          <div className="mt-4 border-t border-line-soft pt-4">
            <BufferBuildUp risk={r} />
          </div>
        </Card>
      </div>

      <Card title="Forecast table" subtitle="Exact GB national values. Conservative = baseline − buffer, floored at 0 MW.">
        <ForecastTable hours={d.hours} />
      </Card>
    </div>
  );
}

function MethodTab({ d, plan }: { d: DecisionResponse; plan: ProcurementResponse | null }) {
  return (
    <div className="space-y-5">
      {plan && (
        <Card title="What the purchase volume assumes" subtitle="Based on exactly what you entered">
          <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed text-ink-soft marker:text-ink-faint">
            {plan.assumptions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ol>
        </Card>
      )}
      <ExplanationPanel d={d} />
    </div>
  );
}
