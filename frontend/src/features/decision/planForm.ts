import type { ProcurementRequest } from "../../types/api";

/** Raw form state (strings, so partially typed numbers are never lost). */
export interface PlanForm {
  demand: string; // flat MW
  hourly: string[] | null; // per-hour MW when "set by hour" is on
  contracted: string; // flat MW
  share: string; // % of national wind output
}

export const HOURS = 24;
export const DEFAULT_FORM: PlanForm = { demand: "", hourly: null, contracted: "", share: "100" };

/** A fully-validated analysis request, assembled only when the user hits "Load analysis". */
export interface AnalysisRequest {
  date: string;
  cutoff: string;
  percentile: number;
  /** null when no demand was entered: the wind outlook is loaded, but no purchase volume. */
  plan: Pick<ProcurementRequest, "demand_mw" | "demand_by_hour_mw" | "contracted_mw" | "wind_share_pct"> | null;
}

const STORAGE_KEY = "windplan.inputs.v1";

/** UI convenience only: the server never relies on this. Failures (private mode, quota) are ignored. */
export function loadForm(): PlanForm {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FORM;
    const p = JSON.parse(raw) as Partial<PlanForm>;
    const hourly = Array.isArray(p.hourly) && p.hourly.length === HOURS ? p.hourly.map(String) : null;
    return {
      demand: typeof p.demand === "string" ? p.demand : "",
      hourly,
      contracted: typeof p.contracted === "string" ? p.contracted : "",
      share: typeof p.share === "string" ? p.share : "100",
    };
  } catch {
    return DEFAULT_FORM;
  }
}

export function saveForm(f: PlanForm): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(f));
  } catch {
    /* ignore */
  }
}

export interface PlanErrors {
  demand?: string;
  hourly?: string;
  contracted?: string;
  share?: string;
}

const MAX_MW = 1_000_000;

const GROUPED = /^\d{1,3}(,\d{3})+(\.\d+)?$/; // 15,000 or 1,250,000.5
const PLAIN = /^(\d+\.?\d*|\.\d+)$/; // 15000, 0.5, .5, 12.

/** Non-negative decimal; thousands separators are accepted only in valid positions. */
function parseMw(s: string): number | null {
  const t = s.trim();
  if (t === "") return null;
  if (GROUPED.test(t)) return Number(t.replace(/,/g, ""));
  if (!PLAIN.test(t)) return null;
  const v = Number(t);
  return Number.isFinite(v) ? v : null;
}

export interface ParsedPlan {
  /** True when demand has been entered (flat or hourly); otherwise nothing should be calculated. */
  hasDemand: boolean;
  errors: PlanErrors;
  valid: boolean;
  request: Pick<ProcurementRequest, "demand_mw" | "demand_by_hour_mw" | "contracted_mw" | "wind_share_pct"> | null;
}

export function parsePlan(f: PlanForm): ParsedPlan {
  const errors: PlanErrors = {};
  let demand: number | undefined;
  let hourly: number[] | undefined;

  if (f.hourly) {
    const values = f.hourly.map(parseMw);
    const blank = f.hourly.filter((v) => v.trim() === "").length;
    if (blank === HOURS) {
      // nothing entered yet
    } else if (values.some((v) => v === null)) {
      errors.hourly = "Enter a number (MW) for every hour.";
    } else if (values.some((v) => (v as number) > MAX_MW)) {
      errors.hourly = `Each hour must be at most ${MAX_MW.toLocaleString("en-GB")} MW.`;
    } else {
      hourly = values as number[];
    }
  } else if (f.demand.trim() !== "") {
    const v = parseMw(f.demand);
    if (v === null) errors.demand = "Enter demand as a positive number of MW.";
    else if (v > MAX_MW) errors.demand = `Demand must be at most ${MAX_MW.toLocaleString("en-GB")} MW.`;
    else demand = v;
  }

  let contracted = 0;
  if (f.contracted.trim() !== "") {
    const v = parseMw(f.contracted);
    if (v === null) errors.contracted = "Enter a number of MW, or leave blank for none.";
    else if (v > MAX_MW) errors.contracted = `Must be at most ${MAX_MW.toLocaleString("en-GB")} MW.`;
    else contracted = v;
  }

  let share = 100;
  const sv = parseMw(f.share);
  if (f.share.trim() === "" || sv === null) errors.share = "Enter a percentage from 0 to 100.";
  else if (sv > 100) errors.share = "Cannot be more than 100%.";
  else share = sv;

  const hasDemand = demand !== undefined || hourly !== undefined;
  const valid = Object.keys(errors).length === 0;
  const request =
    valid && hasDemand
      ? { ...(hourly ? { demand_by_hour_mw: hourly } : { demand_mw: demand }), contracted_mw: contracted, wind_share_pct: share }
      : null;
  return { hasDemand, errors, valid, request };
}
