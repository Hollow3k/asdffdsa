import type {
  ApiErrorBody,
  AppConfig,
  CalibrationCreate,
  CalibrationDetail,
  CalibrationSummary,
  DecisionResponse,
  EvaluationResponse,
  ProcurementRequest,
  ProcurementResponse,
} from "../types/api";

/** Base URL of the backend. Empty = same origin (Vite dev proxy / nginx reverse proxy). */
export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  constructor(message: string, code: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(init?.body ? { "Content-Type": "application/json" } : {}), ...init?.headers },
    });
  } catch {
    throw new ApiError("Cannot reach the application server. Check that the backend is running.", "NETWORK_ERROR", 0);
  }
  if (res.ok) {
    return (await res.json()) as T;
  }
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await res.json()) as Partial<ApiErrorBody>;
  } catch {
    /* non-JSON error body (e.g. proxy error page) */
  }
  const e = body?.error;
  throw new ApiError(e?.message ?? `Request failed with HTTP ${res.status}`, e?.code ?? `HTTP_${res.status}`, res.status, e?.details ?? {});
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  health: () => request<{ status: string; elexon: { reachable: boolean } }>("/api/health"),

  listCalibrations: () => request<CalibrationSummary[]>("/api/calibrations"),
  /** Resolves to null when no calibration has been activated yet (404 NO_ACTIVE_CALIBRATION). */
  activeCalibration: async (): Promise<CalibrationDetail | null> => {
    try {
      return await request<CalibrationDetail>("/api/calibrations/active");
    } catch (e) {
      if (e instanceof ApiError && e.code === "NO_ACTIVE_CALIBRATION") return null;
      throw e;
    }
  },
  getCalibration: (id: string) => request<CalibrationDetail>(`/api/calibrations/${id}`),
  createCalibration: (body: CalibrationCreate) =>
    request<CalibrationSummary>("/api/calibrations", { method: "POST", body: JSON.stringify(body) }),
  activateCalibration: (id: string) => request<CalibrationDetail>(`/api/calibrations/${id}/activate`, { method: "POST" }),

  decision: (date: string, cutoff: string, percentile: number) =>
    request<DecisionResponse>(`/api/decisions/${date}${qs({ cutoff, percentile })}`),
  plan: (date: string, body: ProcurementRequest) =>
    request<ProcurementResponse>(`/api/decisions/${date}/procurement`, { method: "POST", body: JSON.stringify(body) }),
  evaluation: (date: string, cutoff: string, percentile: number) =>
    request<EvaluationResponse>(`/api/decisions/${date}/evaluation${qs({ cutoff, percentile })}`),
};
