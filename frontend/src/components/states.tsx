import type { ReactNode } from "react";
import type { ApiError } from "../services/api";
import { Banner, Button } from "./ui";

const FRIENDLY: Record<string, string> = {
  NETWORK_ERROR: "The application server is unreachable.",
  ELEXON_UNAVAILABLE: "The Elexon data service is not responding right now.",
  ELEXON_RATE_LIMITED: "The Elexon data service is rate limiting requests.",
  ELEXON_MALFORMED_DATA: "The Elexon data service returned data that could not be used.",
  NO_ELIGIBLE_FORECAST: "No forecast had been published by that cutoff.",
  CALIBRATION_UNAVAILABLE_AT_CUTOFF: "The calibration cannot support this decision.",
  DELIVERY_DATE_OUT_OF_RANGE: "That delivery date is outside the simulation window.",
};

export function RemoteError({ error, onRetry, title }: { error: ApiError; onRetry?: () => void; title?: string }) {
  const canRetry = ["NETWORK_ERROR", "ELEXON_UNAVAILABLE", "ELEXON_RATE_LIMITED", "INTERNAL_ERROR", "CLIENT_ERROR"].includes(error.code) || error.status >= 500;
  return (
    <Banner
      kind="error"
      title={title ?? FRIENDLY[error.code] ?? "Something went wrong"}
      action={canRetry && onRetry ? <Button onClick={onRetry}>Try again</Button> : undefined}
    >
      <p>{error.message}</p>
      <p className="mt-1 font-mono text-[11px] opacity-70">{error.code}</p>
    </Banner>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-surface px-6 py-10 text-center">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      {children && <p className="mx-auto mt-1.5 max-w-xl text-sm text-ink-soft">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
