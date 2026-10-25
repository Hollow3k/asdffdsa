import { useCallback, useEffect, useState } from "react";
import { AppProvider, useApp, type Page } from "./AppContext";
import { LoadingBlock } from "./components/ui";
import { RemoteError } from "./components/states";
import { CalibrationPage } from "./features/calibration/CalibrationPage";
import { DecisionPage } from "./features/decision/DecisionPage";
import { LandingPage } from "./features/landing/LandingPage";
import { fmtDate } from "./lib/format";
import { useRemote } from "./lib/useRemote";
import { api } from "./services/api";

const PAGES: Array<{ id: Page; label: string }> = [
  { id: "decision", label: "Plan" },
  { id: "calibration", label: "Calibration" },
];

/** "" or "landing" -> landing; otherwise a dashboard page. The landing is the default front door. */
function routeFromHash(): "landing" | Page {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "" || h === "landing") return "landing";
  return (PAGES.find((p) => p.id === h)?.id ?? "decision") as Page;
}

export default function App() {
  const [route, setRoute] = useState<"landing" | Page>(routeFromHash);
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const navigate = useCallback((p: Page) => {
    window.location.hash = `/${p}`;
    setRoute(p);
  }, []);
  const goLanding = useCallback(() => {
    window.location.hash = "/";
    setRoute("landing");
  }, []);

  // The landing renders instantly and does not need backend config.
  if (route === "landing") return <LandingPage onStart={() => navigate("decision")} />;
  return <Dashboard page={route} navigate={navigate} goLanding={goLanding} />;
}

/** The dashboard shell. Separated from App so its config fetch only runs off the landing route. */
function Dashboard({ page, navigate, goLanding }: { page: Page; navigate: (p: Page) => void; goLanding: () => void }) {
  const config = useRemote(() => api.config(), "config");
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      {config.status === "success" ? (
        <AppProvider config={config.data} page={page} navigate={navigate}>
          <Shell onHome={goLanding} />
        </AppProvider>
      ) : (
        <div className="mx-auto max-w-[1180px] px-3 pb-10 pt-4 sm:px-5">
          <header className="overflow-hidden rounded-3xl bg-gradient-to-br from-[#0c2f2c] via-[#0f766e] to-[#1fb8a6] px-6 py-6 text-white shadow-sm sm:px-8">
            <Brand />
          </header>
          <main id="main" className="mt-6">
            {config.status === "error" ? <RemoteError error={config.error} onRetry={config.reload} title="Cannot start the dashboard" /> : <LoadingBlock label="Starting…" height={160} />}
          </main>
        </div>
      )}
    </div>
  );
}

function Brand({ onHome }: { onHome?: () => void }) {
  const inner = (
    <>
      <svg width="34" height="34" viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
        <rect width="32" height="32" rx="8" fill="#14b8a6" />
        <path d="M6 19c4-8 8 4 12-4s6 2 8-2" stroke="#06322f" strokeWidth="2.6" fill="none" strokeLinecap="round" />
      </svg>
      <div className="text-left">
        <h1 className="text-xl font-semibold leading-tight tracking-tight">Wind Procurement Decision Support</h1>
        <p className="text-xs text-white/70">GB national wind · Elexon WINDFOR forecast vs FUELHH outturn</p>
      </div>
    </>
  );
  if (onHome)
    return (
      <button type="button" onClick={onHome} className="flex items-center gap-3 rounded-lg hover:opacity-90" aria-label="Back to home">
        {inner}
      </button>
    );
  return <div className="flex items-center gap-3">{inner}</div>;
}

function Shell({ onHome }: { onHome: () => void }) {
  const { page, navigate, active, activeLoading, config } = useApp();
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "Europe/London" });
  return (
    <div className="mx-auto max-w-[1180px] px-3 pb-10 pt-4 sm:px-5">
      <header className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-[#0c2f2c] via-[#0f766e] to-[#1fb8a6] px-6 py-6 text-white shadow-sm sm:px-8">
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-medium text-white/70">{today}</p>
            <div className="mt-2">
              <Brand onHome={onHome} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {activeLoading ? (
              <span className="rounded-full bg-white/15 px-3 py-1.5">Loading calibration…</span>
            ) : active ? (
              <button
                type="button"
                onClick={() => navigate("calibration")}
                className="rounded-full bg-white/15 px-3.5 py-1.5 font-medium backdrop-blur hover:bg-white/25"
                aria-label={`Active calibration version ${active.version}, ${fmtDate(active.start_date)} to ${fmtDate(active.end_date)}. Open calibration.`}
              >
                Calibration <strong className="font-semibold">v{active.version}</strong> · {fmtDate(active.start_date)} – {fmtDate(active.end_date)}
              </button>
            ) : (
              <button type="button" onClick={() => navigate("calibration")} className="rounded-full bg-amber-300/25 px-3.5 py-1.5 font-medium text-amber-50 hover:bg-amber-300/35">
                No calibration · set up
              </button>
            )}
            <span className="rounded-full bg-white/15 px-3.5 py-1.5 font-medium">{config.timezone}</span>
          </div>
        </div>
        <nav aria-label="Primary" className="relative mt-6 inline-flex gap-1 rounded-full bg-black/15 p-1 backdrop-blur">
          {PAGES.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => navigate(p.id)}
              aria-current={page === p.id ? "page" : undefined}
              className={`rounded-full px-5 py-2 text-sm font-medium transition-colors ${page === p.id ? "bg-white text-ink shadow-sm" : "text-white/80 hover:text-white"}`}
            >
              {p.label}
            </button>
          ))}
        </nav>
      </header>

      <main id="main" className="mt-6">
        {page === "decision" && <DecisionPage />}
        {page === "calibration" && <CalibrationPage />}
      </main>
      <footer className="mt-8 px-1 text-xs text-ink-faint">
        Retrospective simulation of January 2026 day-ahead decisions using Elexon wind data and the demand you enter. Volumes only: prices, imbalance costs and your risk policy are not modelled. error = forecast − actual.
      </footer>
    </div>
  );
}
