import { useMemo, useState, type ReactNode } from "react";
import { DayStepper } from "../../components/DayStepper";
import { Button, Field, cx, inputCls } from "../../components/ui";
import { HHMM, ISO_DATE, addDays, fmtWeekdayDate } from "../../lib/format";
import type { AppConfig } from "../../types/api";
import { validateParams } from "./DecisionControls";
import { HOURS, parsePlan, type AnalysisRequest, type PlanForm } from "./planForm";

function Step({ n, title, hint, children }: { n: number; title: string; hint?: string; children: ReactNode }) {
  return (
    <fieldset className="border-0 p-0">
      <legend className="mb-3 flex items-center gap-2.5 p-0">
        <span aria-hidden="true" className="flex h-6 w-6 items-center justify-center rounded-full bg-wind text-[12px] font-bold text-white">
          {n}
        </span>
        <span className="text-sm font-semibold text-ink">{title}</span>
      </legend>
      {hint && <p className="-mt-1.5 mb-3 pl-[34px] text-xs text-ink-faint">{hint}</p>}
      <div className="space-y-3.5">{children}</div>
    </fieldset>
  );
}

function Unit({ children }: { children: ReactNode }) {
  return <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs font-medium text-ink-faint">{children}</span>;
}

/**
 * All inputs are local draft state. Nothing is fetched while the user types: the parent only
 * receives a complete {@link AnalysisRequest} when "Load analysis" is pressed (or a day-step button
 * is used). `dirty` highlights the button when the draft differs from what is currently loaded.
 */
export function PlanInputs({
  config,
  defaultDate,
  form,
  loaded,
  busy,
  onForm,
  onSubmit,
}: {
  config: AppConfig;
  defaultDate: string;
  form: PlanForm;
  /** The request currently showing results, for the dirty indicator. null before the first load. */
  loaded: AnalysisRequest | null;
  busy: boolean;
  onForm: (f: PlanForm) => void;
  onSubmit: (req: AnalysisRequest) => void;
}) {
  const [date, setDate] = useState(loaded?.date ?? defaultDate);
  const [cutoff, setCutoff] = useState(loaded?.cutoff ?? config.default_cutoff_time);
  const [percentile, setPercentile] = useState<number>(loaded?.percentile ?? 95);

  const dayErrors = validateParams({ date, cutoff }, config);
  const parsed = useMemo(() => parsePlan(form), [form]);
  const dayValid = !dayErrors.date && !dayErrors.cutoff;
  const canSubmit = dayValid && parsed.valid;
  const previousDay = ISO_DATE.test(date) ? addDays(date, -1) : null;

  const draft: AnalysisRequest = { date, cutoff, percentile, plan: parsed.request };
  const dirty =
    !loaded ||
    loaded.date !== date ||
    loaded.cutoff !== cutoff ||
    loaded.percentile !== percentile ||
    JSON.stringify(loaded.plan) !== JSON.stringify(parsed.request);

  const set = (patch: Partial<PlanForm>) => onForm({ ...form, ...patch });
  const toHourly = () => set({ hourly: Array.from({ length: HOURS }, () => form.demand.trim()) });
  const toFlat = () => set({ hourly: null, demand: form.hourly?.find((v) => v.trim() !== "") ?? form.demand });

  const submit = () => {
    if (canSubmit) onSubmit(draft);
  };

  return (
    <form
      aria-label="Plan inputs"
      className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div className="space-y-6 px-5 py-5">
        <Step n={1} title="Delivery day" hint="January 2026 only (simulation window)">
          <Field label="Delivery date" htmlFor="delivery-date" error={dayErrors.date}>
            <div className="flex gap-1.5">
              <input
                id="delivery-date"
                type="date"
                className={inputCls}
                value={date}
                min={config.decision_window_start}
                max={config.decision_window_end}
                onChange={(e) => setDate(e.target.value)}
                aria-invalid={!!dayErrors.date}
                aria-describedby={dayErrors.date ? "delivery-date-error" : undefined}
              />
              <DayStepper
                date={date}
                min={config.decision_window_start}
                max={config.decision_window_end}
                onStep={(d) => {
                  setDate(d);
                  if (HHMM.test(cutoff) && parsed.valid) onSubmit({ date: d, cutoff, percentile, plan: parsed.request });
                }}
              />
            </div>
          </Field>
          <Field
            label="Forecast cutoff (UK time)"
            htmlFor="cutoff-time"
            error={dayErrors.cutoff}
            hint={previousDay ? `Uses the latest forecast published by this time on ${fmtWeekdayDate(previousDay)}` : "Applies to the day before delivery"}
          >
            <input
              id="cutoff-time"
              type="time"
              step={60}
              className={inputCls}
              value={cutoff}
              onChange={(e) => setCutoff(e.target.value)}
              aria-invalid={!!dayErrors.cutoff}
              aria-describedby={dayErrors.cutoff ? "cutoff-time-error" : undefined}
            />
          </Field>
        </Step>

        <Step n={2} title="Your demand" hint="Leave blank to see the wind outlook only, with no purchase volume">
          {form.hourly === null ? (
            <Field label="Expected demand" htmlFor="demand" error={parsed.errors.demand} hint="Average MW you need in every hour of the day">
              <div className="relative">
                <input
                  id="demand"
                  inputMode="decimal"
                  autoComplete="off"
                  placeholder="e.g. 15000"
                  className={cx(inputCls, "pr-12")}
                  value={form.demand}
                  onChange={(e) => set({ demand: e.target.value })}
                  aria-invalid={!!parsed.errors.demand}
                  aria-describedby={parsed.errors.demand ? "demand-error" : undefined}
                />
                <Unit>MW</Unit>
              </div>
            </Field>
          ) : (
            <div>
              <span className="mb-1.5 block text-[12px] font-medium uppercase tracking-wide text-ink-soft">Demand by hour (MW)</span>
              <div className="grid grid-cols-4 gap-1.5" role="group" aria-label="Expected demand for each hour, in MW">
                {form.hourly.map((v, i) => {
                  const hh = String(i).padStart(2, "0");
                  return (
                    <label key={i} className="block">
                      <span className="mb-0.5 block text-[10px] font-medium text-ink-faint">{hh}:00</span>
                      <input
                        inputMode="decimal"
                        aria-label={`Demand at ${hh}:00 (MW)`}
                        className={cx(inputCls, "px-2 py-1.5 text-xs")}
                        value={v}
                        onChange={(e) => set({ hourly: form.hourly!.map((x, j) => (j === i ? e.target.value : x)) })}
                      />
                    </label>
                  );
                })}
              </div>
              {parsed.errors.hourly && (
                <p role="alert" className="mt-1 text-xs text-short">
                  {parsed.errors.hourly}
                </p>
              )}
            </div>
          )}
          <button type="button" onClick={form.hourly === null ? toHourly : toFlat} className="text-xs font-medium text-wind underline-offset-2 hover:underline">
            {form.hourly === null ? "Set demand hour by hour instead" : "Use one value for every hour"}
          </button>

          <Field label="Existing contracted supply" htmlFor="contracted" error={parsed.errors.contracted} hint="Optional. Already bought for this day; reduces what you still need">
            <div className="relative">
              <input
                id="contracted"
                inputMode="decimal"
                autoComplete="off"
                placeholder="0"
                className={cx(inputCls, "pr-12")}
                value={form.contracted}
                onChange={(e) => set({ contracted: e.target.value })}
                aria-invalid={!!parsed.errors.contracted}
                aria-describedby={parsed.errors.contracted ? "contracted-error" : undefined}
              />
              <Unit>MW</Unit>
            </div>
          </Field>

          <Field
            label="Share of GB wind you can count on"
            htmlFor="wind-share"
            error={parsed.errors.share}
            hint="Elexon wind is the whole GB total. 100% plans against all of it; enter your own share (e.g. 0.5) if you only access part."
          >
            <div className="relative">
              <input
                id="wind-share"
                inputMode="decimal"
                autoComplete="off"
                className={cx(inputCls, "pr-9")}
                value={form.share}
                onChange={(e) => set({ share: e.target.value })}
                aria-invalid={!!parsed.errors.share}
                aria-describedby={parsed.errors.share ? "wind-share-error" : undefined}
              />
              <Unit>%</Unit>
            </div>
          </Field>
        </Step>

        <Step n={3} title="How cautious to be">
          <div role="radiogroup" aria-label="Risk percentile" className="grid grid-cols-2 gap-1.5 rounded-xl bg-canvas p-1">
            {[90, 95].map((p) => (
              <button
                key={p}
                type="button"
                role="radio"
                aria-checked={percentile === p}
                onClick={() => setPercentile(p)}
                className={cx(
                  "rounded-lg px-3 py-2 text-sm font-semibold transition-colors",
                  percentile === p ? "bg-wind text-white shadow-sm" : "text-ink-soft hover:text-ink",
                )}
              >
                P{p}
              </button>
            ))}
          </div>
          <p className="text-xs text-ink-faint">
            P{percentile}: plan for wind falling short by an amount only exceeded in about {100 - percentile}% of comparable past hours. Higher is safer but buys more.
          </p>
        </Step>
      </div>

      <div className="border-t border-line-soft bg-canvas/50 px-5 py-4">
        <Button variant="primary" type="submit" disabled={!canSubmit || busy} className="w-full py-2.5">
          {busy ? "Loading…" : dirty ? "Load analysis" : "Reload analysis"}
        </Button>
        {!parsed.valid && dayValid && <p className="mt-2 text-center text-xs text-short">Fix the highlighted inputs to continue.</p>}
        {dirty && !busy && loaded && canSubmit && <p className="mt-2 text-center text-xs text-ink-faint">Inputs changed — load to update the results.</p>}
      </div>
    </form>
  );
}
