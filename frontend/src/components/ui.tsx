import { useId, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { QualityWarning } from "../types/api";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  as: Tag = "section",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  as?: "section" | "div";
}) {
  return (
    <Tag className={cx("rounded-2xl border border-line bg-surface shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line-soft px-5 py-3.5">
          <div>
            {title && <h2 className="text-[15px] font-semibold tracking-tight text-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-[13px] text-ink-soft">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </Tag>
  );
}

/** Small definition tooltip that works with hover, keyboard focus and screen readers. */
export function InfoTip({ text, label = "Definition" }: { text: string; label?: string }) {
  const id = useId();
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`${label}: ${text}`}
        aria-describedby={id}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-line text-[10px] font-semibold leading-none text-ink-faint hover:border-wind hover:text-wind"
      >
        i
      </button>
      <span
        role="tooltip"
        id={id}
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-30 mb-2 w-64 -translate-x-1/2 rounded-md bg-ink px-3 py-2 text-left text-xs font-normal normal-case leading-snug text-white opacity-0 shadow-lg transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

export function Stat({
  label,
  value,
  unit,
  hint,
  tip,
  tone = "default",
  size = "md",
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  tip?: string;
  tone?: "default" | "risk" | "short" | "wind";
  size?: "md" | "lg";
}) {
  const toneCls = { default: "text-ink", risk: "text-risk", short: "text-short", wind: "text-wind" }[tone];
  return (
    <div>
      <dt className="text-[12px] font-medium uppercase tracking-wide text-ink-soft">
        {label}
        {tip && <InfoTip text={tip} />}
      </dt>
      <dd className="mt-1">
        <span className={cx("num font-semibold tracking-tight", size === "lg" ? "text-4xl" : "text-2xl", toneCls)}>{value}</span>
        {unit && <span className="ml-1 text-sm text-ink-soft">{unit}</span>}
        {hint && <div className="mt-0.5 text-xs text-ink-soft">{hint}</div>}
      </dd>
    </div>
  );
}

const BANNER_STYLES = {
  info: "border-info/25 bg-info-soft text-[#1e3a8a]",
  warning: "border-risk/30 bg-risk-soft text-[#7c3a06]",
  error: "border-short/30 bg-short-soft text-[#7a1a12]",
  success: "border-ok/30 bg-ok-soft text-[#14532d]",
  neutral: "border-line bg-canvas text-ink-soft",
} as const;

export function Banner({
  kind = "info",
  title,
  children,
  action,
}: {
  kind?: keyof typeof BANNER_STYLES;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={cx("flex flex-wrap items-start justify-between gap-3 rounded-md border px-4 py-3 text-sm", BANNER_STYLES[kind])}>
      <div className="min-w-0 flex-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={cx(title ? "mt-0.5" : undefined, "leading-snug")}>{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function WarningList({ warnings }: { warnings: QualityWarning[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="space-y-2" aria-label="Data quality warnings">
      {warnings.map((w, i) => (
        <li key={`${w.code}-${i}`}>
          <Banner kind={w.severity === "error" ? "error" : w.severity === "info" ? "info" : "warning"}>{w.message}</Banner>
        </li>
      ))}
    </ul>
  );
}

export function Button({
  variant = "secondary",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-wind text-white hover:bg-[#0b5f58] disabled:bg-[#7fb5b0]",
    secondary: "border border-line bg-white text-ink hover:border-wind hover:text-wind disabled:text-ink-faint disabled:hover:border-line",
    ghost: "text-wind hover:bg-wind-soft disabled:text-ink-faint",
    danger: "bg-short text-white hover:bg-[#8f1a11]",
  }[variant];
  return (
    <button
      type="button"
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed",
        styles,
        className,
      )}
    />
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ink-soft">
      <svg className="h-4 w-4 animate-spin text-wind" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.2" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label}
    </span>
  );
}

export function LoadingBlock({ label, height = 240 }: { label: string; height?: number }) {
  return (
    <div className="flex items-center justify-center rounded-md bg-canvas" style={{ height }} aria-busy="true">
      <Spinner label={label} />
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "bad" | "info"; children: ReactNode }) {
  const t = {
    neutral: "bg-canvas text-ink-soft border-line",
    ok: "bg-ok-soft text-ok border-ok/20",
    warn: "bg-risk-soft text-risk border-risk/25",
    bad: "bg-short-soft text-short border-short/25",
    info: "bg-info-soft text-info border-info/20",
  }[tone];
  return <span className={cx("inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(100, value));
  return (
    <div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={v}
        className="h-2 w-full overflow-hidden rounded-full bg-line-soft"
      >
        <div className="h-full rounded-full bg-wind transition-[width] duration-500" style={{ width: `${v}%` }} />
      </div>
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1 block text-[12px] font-medium uppercase tracking-wide text-ink-soft">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${htmlFor}-error`} role="alert" className="mt-1 text-xs text-short">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-xs text-ink-faint">{hint}</p>
      )}
    </div>
  );
}

export const inputCls =
  "num w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink shadow-none focus:border-wind aria-[invalid=true]:border-short";
