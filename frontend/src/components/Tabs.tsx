import { useId, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./ui";

export interface TabDef<T extends string> {
  id: T;
  label: string;
  badge?: ReactNode;
}

/** WAI-ARIA tabs: arrow keys move between tabs, Home/End jump, the panel is labelled by its tab. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  children,
}: {
  tabs: TabDef<T>[];
  value: T;
  onChange: (id: T) => void;
  label: string;
  children: ReactNode;
}) {
  const uid = useId();
  const idx = tabs.findIndex((t) => t.id === value);

  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const targets: Record<string, number> = {
      ArrowRight: (idx + 1) % tabs.length,
      ArrowLeft: (idx - 1 + tabs.length) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    };
    const next = targets[e.key];
    if (next === undefined) return;
    e.preventDefault();
    onChange(tabs[next].id);
    document.getElementById(`${uid}-tab-${tabs[next].id}`)?.focus();
  };

  return (
    <div>
      <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
        {tabs.map((t) => {
          const selected = t.id === value;
          return (
            <button
              key={t.id}
              id={`${uid}-tab-${t.id}`}
              role="tab"
              type="button"
              aria-selected={selected}
              aria-controls={`${uid}-panel-${t.id}`}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(t.id)}
              onKeyDown={onKey}
              className={cx(
                "-mb-px flex shrink-0 items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-medium transition-colors",
                selected ? "border-wind text-wind" : "border-transparent text-ink-soft hover:text-ink",
              )}
            >
              {t.label}
              {t.badge}
            </button>
          );
        })}
      </div>
      <div role="tabpanel" id={`${uid}-panel-${value}`} aria-labelledby={`${uid}-tab-${value}`} className="pt-5">
        {children}
      </div>
    </div>
  );
}
