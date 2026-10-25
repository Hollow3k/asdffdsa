import { useCallback, useEffect, useRef, useState } from "react";
import { Banner, Button, Card, Field, ProgressBar, WarningList, inputCls } from "../../components/ui";
import { RemoteError } from "../../components/states";
import { HHMM, ISO_DATE, daysInclusive, fmtDate, fmtUkDateTime, int, mw } from "../../lib/format";
import { ApiError, api } from "../../services/api";
import { toApiError } from "../../lib/useRemote";
import type { AppConfig, CalibrationDetail, CalibrationSummary } from "../../types/api";

type Phase = "edit" | "review" | "running" | "done";

export function validateRange(
  v: { start: string; end: string; cutoff: string },
  config: AppConfig,
): { start?: string; end?: string; cutoff?: string } {
  const e: { start?: string; end?: string; cutoff?: string } = {};
  if (!ISO_DATE.test(v.start)) e.start = "Enter a valid start date.";
  if (!ISO_DATE.test(v.end)) e.end = "Enter a valid end date.";
  if (!e.start && !e.end) {
    if (v.end < v.start) e.end = "End date must not be before the start date.";
    else if (daysInclusive(v.start, v.end) > config.max_calibration_days)
      e.end = `Range is longer than the maximum of ${config.max_calibration_days} days.`;
    else if (v.end > config.latest_calibration_end_date)
      e.end = `Latest allowed end date is ${fmtDate(config.latest_calibration_end_date)}: actual generation for the whole day must already be published.`;
  }
  if (!HHMM.test(v.cutoff)) e.cutoff = "Enter a time as HH:MM (24 hour).";
  return e;
}

const POLL_MS = 1500;
const MAX_POLL_FAILURES = 5;

export function RunCalibration({
  config,
  active,
  versions,
  onFinished,
  pollMs = POLL_MS,
}: {
  config: AppConfig;
  active: CalibrationDetail | null;
  versions: CalibrationSummary[];
  onFinished: (opts: { activated?: boolean }) => void;
  pollMs?: number;
}) {
  // "Initial" until some version has completed. Locked while a run is in flight/finished so labels don't flip.
  const derivedInitial = !versions.some((v) => v.status === "completed");
  const [lockedInitial, setLockedInitial] = useState<boolean | null>(null);
  const initialMode = lockedInitial ?? derivedInitial;
  const [phase, setPhase] = useState<Phase>("edit");
  const [start, setStart] = useState(config.default_calibration_start);
  const [end, setEnd] = useState(config.default_calibration_end);
  const [cutoff, setCutoff] = useState(config.default_cutoff_time);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<CalibrationSummary | CalibrationDetail | null>(null);
  const [submitError, setSubmitError] = useState<ApiError | null>(null);
  const [pollWarning, setPollWarning] = useState<string | null>(null);
  const [activating, setActivating] = useState(false);
  const [activateError, setActivateError] = useState<ApiError | null>(null);
  const [activated, setActivated] = useState(false);
  const resumed = useRef(false);

  const errors = validateRange({ start, end, cutoff }, config);
  const valid = !errors.start && !errors.end && !errors.cutoff;
  const nextVersion = Math.max(0, ...versions.map((v) => v.version)) + 1;

  // Resume tracking a job that is already running (e.g. after a page refresh).
  useEffect(() => {
    if (resumed.current) return;
    const running = versions.find((v) => v.status === "pending" || v.status === "running");
    if (running) {
      resumed.current = true;
      setLockedInitial(!versions.some((v) => v.status === "completed"));
      setJobId(running.id);
      setJob(running);
      setPhase("running");
    }
  }, [versions]);

  // Poll the running job until it reaches a terminal state.
  useEffect(() => {
    if (phase !== "running" || !jobId) return;
    let cancelled = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        const d = await api.getCalibration(jobId);
        if (cancelled) return;
        failures = 0;
        setPollWarning(null);
        setJob(d);
        if (d.status === "completed" || d.status === "failed") {
          setPhase("done");
          onFinished({});
          return;
        }
      } catch (e) {
        if (cancelled) return;
        failures += 1;
        setPollWarning(`Lost contact with the server while checking progress (${toApiError(e).message}). Retrying…`);
        if (failures >= MAX_POLL_FAILURES) {
          setPollWarning("Progress can no longer be checked. The calculation may still be running; reload the page to see its status.");
          return;
        }
      }
      timer = setTimeout(tick, pollMs);
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onFinished is intentionally not a trigger
  }, [phase, jobId, pollMs]);

  const startRun = useCallback(async () => {
    setSubmitError(null);
    try {
      const created = await api.createCalibration({ start_date: start, end_date: end, cutoff_time: cutoff });
      setLockedInitial(derivedInitial);
      setJobId(created.id);
      setJob(created);
      setActivated(false);
      setPhase("running");
    } catch (e) {
      setSubmitError(toApiError(e));
      setPhase("edit");
    }
  }, [start, end, cutoff, derivedInitial]);

  const activate = async () => {
    if (!jobId) return;
    setActivating(true);
    setActivateError(null);
    try {
      await api.activateCalibration(jobId);
      setActivated(true);
      onFinished({ activated: true });
    } catch (e) {
      setActivateError(toApiError(e));
    } finally {
      setActivating(false);
    }
  };

  const reset = () => {
    setLockedInitial(null);
    setPhase("edit");
    setJob(null);
    setJobId(null);
    setSubmitError(null);
    setActivated(false);
    setActivateError(null);
  };

  const title = initialMode ? "Run initial calibration" : "Recalculate calibration";
  return (
    <Card
      title={title}
      subtitle={
        initialMode
          ? "Measure how accurate day-ahead wind forecasts were, using the forecast available at each historical cutoff."
          : "Creates a new version. The active version stays in use until you review and activate the new one."
      }
    >
      {phase === "edit" && (
        <form
          className="space-y-4"
          aria-label={title}
          onSubmit={(e) => {
            e.preventDefault();
            if (!valid) return;
            if (initialMode) void startRun();
            else setPhase("review");
          }}
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Calibration start date" htmlFor="cal-start" error={errors.start}>
              <input id="cal-start" type="date" className={inputCls} value={start} max={config.latest_calibration_end_date} onChange={(e) => setStart(e.target.value)} aria-invalid={!!errors.start} />
            </Field>
            <Field label="Calibration end date" htmlFor="cal-end" error={errors.end} hint="Inclusive">
              <input id="cal-end" type="date" className={inputCls} value={end} max={config.latest_calibration_end_date} onChange={(e) => setEnd(e.target.value)} aria-invalid={!!errors.end} />
            </Field>
            <Field label="Forecast cutoff (UK time)" htmlFor="cal-cutoff" error={errors.cutoff} hint="On the day before each delivery day">
              <input id="cal-cutoff" type="time" step={60} className={inputCls} value={cutoff} onChange={(e) => setCutoff(e.target.value)} aria-invalid={!!errors.cutoff} />
            </Field>
          </div>
          {valid && end >= config.decision_window_start && (
            <Banner kind="info" title="Range reaches into the decision window">
              Decisions only ever use calibration hours that had been observed by their own cutoff, so hours after a given decision are excluded automatically.
            </Banner>
          )}
          {submitError && <RemoteError error={submitError} title="Could not start the calibration" />}
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" type="submit" disabled={!valid}>
              {initialMode ? "Run initial calibration" : "Review calculation"}
            </Button>
            {!initialMode && (
              <Button
                onClick={() => {
                  setStart(config.default_calibration_start);
                  setEnd(config.default_calibration_end);
                  setCutoff(config.default_cutoff_time);
                }}
              >
                Reset to defaults
              </Button>
            )}
          </div>
        </form>
      )}

      {phase === "review" && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold">Review before calculating</h3>
          <dl className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2">
            <Row label="Calibration period">
              {fmtDate(start)} – {fmtDate(end)} <span className="text-ink-soft">({daysInclusive(start, end)} delivery days)</span>
            </Row>
            <Row label="Forecast cutoff">{cutoff} UK on the previous day</Row>
            <Row label="New version">v{nextVersion}</Row>
            <Row label="Currently active">{active ? `v${active.version} (${fmtDate(active.start_date)} – ${fmtDate(active.end_date)}) stays active` : "none"}</Row>
          </dl>
          <p className="text-sm text-ink-soft">
            Elexon forecast vintages and outturn are fetched by the server, aligned by delivery hour, and saved. If the calculation fails, the active version is not touched.
          </p>
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => void startRun()}>Start calculation</Button>
            <Button onClick={() => setPhase("edit")}>Back</Button>
          </div>
        </div>
      )}

      {phase === "running" && (
        <div className="space-y-3" aria-live="polite">
          <div className="flex items-baseline justify-between text-sm">
            <span className="font-medium">Calculating version {job?.version ?? ""}…</span>
            <span className="num text-ink-soft">{job?.progress ?? 0}%</span>
          </div>
          <ProgressBar value={job?.progress ?? 0} label="Calibration progress" />
          <p className="text-sm text-ink-soft">{job?.stage ?? "Queued"}</p>
          {pollWarning && <Banner kind="warning">{pollWarning}</Banner>}
        </div>
      )}

      {phase === "done" && job && (
        <div className="space-y-4">
          {job.status === "failed" ? (
            <>
              <Banner kind="error" title={`Version ${job.version} failed`}>
                <p>{job.error_message ?? "The calibration did not complete."}</p>
                {job.error_code && <p className="mt-1 font-mono text-[11px] opacity-70">{job.error_code}</p>}
              </Banner>
              <Banner kind="success">
                {active ? `Active calibration v${active.version} is unchanged and still in use.` : "No calibration is active yet."}
              </Banner>
              <Button variant="primary" onClick={reset}>Try again</Button>
            </>
          ) : (
            <CompletedReview
              job={job as CalibrationDetail}
              active={active}
              activated={activated || (job as CalibrationDetail).is_active}
              activating={activating}
              activateError={activateError}
              onActivate={() => void activate()}
              onReset={reset}
            />
          )}
        </div>
      )}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] font-medium uppercase tracking-wide text-ink-soft">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}

function CompletedReview({
  job,
  active,
  activated,
  activating,
  activateError,
  onActivate,
  onReset,
}: {
  job: CalibrationDetail;
  active: CalibrationDetail | null;
  activated: boolean;
  activating: boolean;
  activateError: ApiError | null;
  onActivate: () => void;
  onReset: () => void;
}) {
  const m = job.metrics;
  const cmp = active && active.id !== job.id ? active.metrics : null;
  const rows: Array<[string, number | null | undefined, number | null | undefined, boolean?]> = m
    ? [
        ["Matched hours", m.n, cmp?.n, true],
        ["MAE (MW)", m.mae_mw, cmp?.mae_mw],
        ["RMSE (MW)", m.rmse_mw, cmp?.rmse_mw],
        ["Bias (MW)", m.bias_mw, cmp?.bias_mw],
        ["P95 absolute error (MW)", m.p95_abs_error_mw, cmp?.p95_abs_error_mw],
        ["P95 signed error, all hours (MW)", m.p95_error_mw, cmp?.p95_error_mw],
      ]
    : [];
  return (
    <>
      <Banner kind="success" title={`Version ${job.version} calculated`}>
        {fmtDate(job.start_date)} – {fmtDate(job.end_date)} · {int(m?.n ?? 0)} matched hours · finished {fmtUkDateTime(job.completed_at)} UK
        {activated && <strong> · now the active calibration</strong>}
      </Banner>
      {job.warnings?.length > 0 && <WarningList warnings={job.warnings} />}
      {m && (
        <table className="w-full max-w-xl text-sm">
          <caption className="sr-only">New calibration compared with the active calibration</caption>
          <thead className="text-left text-[12px] uppercase tracking-wide text-ink-soft">
            <tr>
              <th scope="col" className="py-1 font-medium">Metric</th>
              <th scope="col" className="py-1 text-right font-medium">New v{job.version}</th>
              {cmp && <th scope="col" className="py-1 text-right font-medium">Active v{active?.version}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, a, b, isCount]) => (
              <tr key={label} className="border-t border-line-soft">
                <th scope="row" className="py-1.5 text-left font-normal">{label}</th>
                <td className="num py-1.5 text-right font-medium">{isCount ? int(a) : mw(a, { signed: label.startsWith("Bias") })}</td>
                {cmp && <td className="num py-1.5 text-right text-ink-soft">{isCount ? int(b) : mw(b, { signed: label.startsWith("Bias") })}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {activateError && <RemoteError error={activateError} title="Could not activate this version" />}
      <div className="flex flex-wrap gap-2">
        {!activated && (
          <Button variant="primary" onClick={onActivate} disabled={activating}>
            {activating ? "Activating…" : `Activate version ${job.version}`}
          </Button>
        )}
        <Button onClick={onReset}>Run another calculation</Button>
      </div>
      {!activated && <p className="text-xs text-ink-soft">Until activated, the dashboard keeps using {active ? `v${active.version}` : "no calibration"}.</p>}
    </>
  );
}
