export const UK_TZ = "Europe/London";

/** Whole-number MW with thousands separators, or an em dash when unavailable. */
export function mw(value: number | null | undefined, opts: { signed?: boolean; decimals?: number } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const d = opts.decimals ?? 0;
  const s = Math.abs(value).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
  if (opts.signed) return `${value < 0 ? "−" : value > 0 ? "+" : ""}${s}`;
  return `${value < 0 ? "−" : ""}${s}`;
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function int(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-GB");
}

/** "14 Jan 2026" for a YYYY-MM-DD business date (no timezone shift: it is already a UK date). */
export function fmtDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function fmtWeekdayDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** UTC instant -> "14 Jan 2026, 15:30" in UK local time. */
export function fmtUkDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: UK_TZ,
  });
}

/** Add days to a YYYY-MM-DD date string without touching timezones. */
export function addDays(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + days));
  return dt.toISOString().slice(0, 10);
}

export function daysInclusive(start: string, end: string): number {
  const [y1, m1, d1] = start.split("-").map(Number);
  const [y2, m2, d2] = end.split("-").map(Number);
  return Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000) + 1;
}

export const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;
export const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
