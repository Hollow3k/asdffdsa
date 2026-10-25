import { HHMM, ISO_DATE, fmtDate } from "../../lib/format";
import type { AppConfig } from "../../types/api";

/** Validates the day/cutoff portion of the plan inputs. Shared by the inputs panel. */
export function validateParams(p: { date: string; cutoff: string }, config: AppConfig): { date?: string; cutoff?: string } {
  const errors: { date?: string; cutoff?: string } = {};
  if (!ISO_DATE.test(p.date)) errors.date = "Enter a valid date.";
  else if (p.date < config.decision_window_start || p.date > config.decision_window_end)
    errors.date = `Choose a date between ${fmtDate(config.decision_window_start)} and ${fmtDate(config.decision_window_end)}.`;
  if (!HHMM.test(p.cutoff)) errors.cutoff = "Enter a time as HH:MM (24 hour).";
  return errors;
}
