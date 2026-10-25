import { createContext, useContext, useMemo, type ReactNode } from "react";
import { api } from "./services/api";
import { useRemote } from "./lib/useRemote";
import type { ApiError } from "./services/api";
import type { AppConfig, CalibrationDetail } from "./types/api";

export type Page = "decision" | "calibration";

interface AppContextValue {
  config: AppConfig;
  active: CalibrationDetail | null;
  activeLoading: boolean;
  activeError: ApiError | null;
  refreshActive: () => void;
  /** Sensible default delivery day for the Plan page (mid-January, inside the window). */
  defaultDeliveryDate: string;
  page: Page;
  navigate: (p: Page) => void;
}

const Ctx = createContext<AppContextValue | null>(null);

export function useApp(): AppContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used inside <AppProvider>");
  return v;
}

export function AppProvider({
  config,
  page,
  navigate,
  children,
}: {
  config: AppConfig;
  page: Page;
  navigate: (p: Page) => void;
  children: ReactNode;
}) {
  const active = useRemote(() => api.activeCalibration(), "active");
  const defaultDeliveryDate = clampDate("2026-01-15", config);

  const activeData: CalibrationDetail | null = "data" in active ? (active.data ?? null) : null;
  const activeLoading = active.status === "loading" && activeData === null;
  const activeError = active.status === "error" ? active.error : null;
  const refreshActive = active.reload;
  const value = useMemo<AppContextValue>(
    () => ({
      config,
      active: activeData,
      activeLoading,
      activeError,
      refreshActive,
      defaultDeliveryDate,
      page,
      navigate,
    }),
    [config, activeData, activeLoading, activeError, refreshActive, defaultDeliveryDate, page, navigate],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

function clampDate(d: string, c: AppConfig): string {
  if (d < c.decision_window_start) return c.decision_window_start;
  if (d > c.decision_window_end) return c.decision_window_end;
  return d;
}
