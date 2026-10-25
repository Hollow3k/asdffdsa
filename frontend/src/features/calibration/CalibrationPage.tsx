import { useState } from "react";
import { useApp } from "../../AppContext";
import { Badge, Button, Card, LoadingBlock } from "../../components/ui";
import { EmptyState, RemoteError } from "../../components/states";
import { fmtDate, fmtUkDateTime, int } from "../../lib/format";
import { toApiError, useRemote } from "../../lib/useRemote";
import { api } from "../../services/api";
import type { ApiError } from "../../services/api";
import type { CalibrationSummary } from "../../types/api";
import { CalibrationDetailView, StatusBadge } from "./CalibrationDetailView";
import { RunCalibration } from "./RunCalibration";

export function CalibrationPage() {
  const { config, active, activeLoading, activeError, refreshActive } = useApp();
  const versions = useRemote(() => api.listCalibrations(), "versions");
  const [selected, setSelected] = useState<string | null>(null);

  const list: CalibrationSummary[] = "data" in versions && versions.data ? versions.data : [];
  const inspectId = selected ?? active?.id ?? list.find((v) => v.status === "completed")?.id ?? null;
  const detail = useRemote(inspectId ? () => api.getCalibration(inspectId) : null, `detail-${inspectId}`);

  const [activateError, setActivateError] = useState<ApiError | null>(null);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const activate = async (id: string) => {
    setActivatingId(id);
    setActivateError(null);
    try {
      await api.activateCalibration(id);
      refreshActive();
      versions.reload();
      detail.reload();
    } catch (e) {
      setActivateError(toApiError(e));
    } finally {
      setActivatingId(null);
    }
  };

  if (versions.status === "loading" && !list.length && activeLoading) return <LoadingBlock label="Loading calibrations…" height={200} />;

  return (
    <div className="space-y-5">
      {activeError && <RemoteError error={activeError} onRetry={refreshActive} title="Could not load the active calibration" />}
      {versions.status === "error" && <RemoteError error={versions.error} onRetry={versions.reload} title="Could not load calibration versions" />}

      {versions.status === "success" && list.length === 0 && !active && (
        <EmptyState title="No calibration exists yet">
          Start with the initial calibration below. It fetches historical Elexon forecasts and outturn once, saves the matched results, and reuses them whenever the
          dashboard is opened.
        </EmptyState>
      )}

      {(versions.status === "success" || list.length > 0) && (
        <RunCalibration
          config={config}
          active={active}
          versions={list}
          onFinished={() => {
            refreshActive();
            versions.reload();
            detail.reload();
          }}
        />
      )}

      {list.length > 0 && (
        <Card title="Calibration versions" subtitle="Every calculation is kept. Inspect any version or reactivate an earlier one.">
          {activateError && (
            <div className="mb-3">
              <RemoteError error={activateError} title="Could not activate that version" />
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <caption className="sr-only">Calibration versions</caption>
              <thead className="text-left text-[12px] uppercase tracking-wide text-ink-soft">
                <tr>
                  <th scope="col" className="py-2 pr-3 font-medium">Version</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Period</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Cutoff</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Status</th>
                  <th scope="col" className="py-2 pr-3 text-right font-medium">Hours</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Calculated (UK)</th>
                  <th scope="col" className="py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {list.map((v) => (
                  <tr key={v.id} className={`border-t border-line-soft ${v.id === inspectId ? "bg-wind-soft/40" : ""}`}>
                    <th scope="row" className="py-2 pr-3 text-left font-semibold">
                      v{v.version} {v.is_active && <Badge tone="ok">active</Badge>}
                    </th>
                    <td className="py-2 pr-3">{fmtDate(v.start_date)} – {fmtDate(v.end_date)}</td>
                    <td className="num py-2 pr-3">{v.cutoff_time}</td>
                    <td className="py-2 pr-3">
                      <StatusBadge status={v.status} />
                      {v.warning_count > 0 && <span className="ml-1.5 text-xs text-risk">{v.warning_count} warning{v.warning_count > 1 ? "s" : ""}</span>}
                    </td>
                    <td className="num py-2 pr-3 text-right">{int(v.n_matched)}</td>
                    <td className="num py-2 pr-3">{fmtUkDateTime(v.completed_at)}</td>
                    <td className="py-2 text-right">
                      <span className="inline-flex gap-1.5">
                        <Button variant="ghost" onClick={() => setSelected(v.id)} aria-label={`Inspect version ${v.version}`}>Inspect</Button>
                        {v.status === "completed" && !v.is_active && (
                          <Button onClick={() => void activate(v.id)} disabled={activatingId !== null} aria-label={`Activate version ${v.version}`}>
                            {activatingId === v.id ? "Activating…" : "Activate"}
                          </Button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {inspectId && detail.status === "loading" && !("data" in detail && detail.data) && <LoadingBlock label="Loading calibration details…" height={220} />}
      {detail.status === "error" && <RemoteError error={detail.error} onRetry={detail.reload} />}
      {"data" in detail && detail.data && <CalibrationDetailView cal={detail.data} />}
    </div>
  );
}
