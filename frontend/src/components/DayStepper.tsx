import { addDays } from "../lib/format";

/** Previous / next day buttons that stay inside [min, max]. */
export function DayStepper({ date, min, max, onStep }: { date: string; min: string; max: string; onStep: (d: string) => void }) {
  const valid = /^\d{4}-\d{2}-\d{2}$/.test(date);
  const prev = valid ? addDays(date, -1) : null;
  const next = valid ? addDays(date, 1) : null;
  const cls =
    "inline-flex h-[38px] w-9 items-center justify-center rounded-md border border-line bg-white text-ink hover:border-wind hover:text-wind disabled:cursor-not-allowed disabled:text-ink-faint disabled:hover:border-line";
  return (
    <>
      <button type="button" className={cls} aria-label="Previous day" disabled={!prev || prev < min} onClick={() => prev && onStep(prev)}>
        <span aria-hidden="true">‹</span>
      </button>
      <button type="button" className={cls} aria-label="Next day" disabled={!next || next > max} onClick={() => next && onStep(next)}>
        <span aria-hidden="true">›</span>
      </button>
    </>
  );
}
