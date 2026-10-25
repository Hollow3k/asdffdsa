import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { config, decision, detail, metrics } from "./fixtures";
import { errorBody, mockFetch, type Handler } from "./mockApi";

const base = (extra: Record<string, Handler> = {}): Record<string, Handler> => ({
  "GET /api/config": { body: config },
  "GET /api/calibrations/active": { body: detail() },
  "GET /api/decisions/2026-01-15": { body: decision() },
  ...extra,
});

/** Nothing is fetched until the user loads the analysis. This presses the button and waits. */
async function load() {
  await userEvent.click(await screen.findByRole("button", { name: /Load analysis/ }));
}

describe("Decision dashboard", () => {
  it("fetches nothing until Load analysis is pressed", async () => {
    const f = mockFetch(base());
    render(<App />);
    // The getting-started prompt is shown; no decision request yet.
    expect(await screen.findByText(/Set your inputs, then load the analysis/)).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 200));
    expect(f.count("GET", "/api/decisions/2026-01-15")).toBe(0);
    await load();
    await waitFor(() => expect(f.count("GET", "/api/decisions/2026-01-15")).toBe(1));
  });

  it("shows a loading state, then the forecast, provenance and shortfall buffer", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    let first = true;
    mockFetch(
      base({
        "GET /api/decisions/2026-01-15": async () => {
          if (first) {
            first = false;
            await gate;
          }
          return { body: decision() };
        },
      }),
    );
    render(<App />);
    await load();

    expect(await screen.findByText(/Selecting the eligible forecast/i)).toBeInTheDocument();
    release();

    expect(await screen.findByTestId("shortfall-buffer")).toHaveTextContent("5,043");
    // Wind outlook tab shows provenance and the positive-error tail
    await userEvent.click(screen.getByRole("tab", { name: "Wind outlook & risk" }));
    expect(screen.getByText("Elexon BMRS · WINDFOR")).toBeInTheDocument();
    expect(screen.getAllByText(/14 Jan 2026, 15:30/).length).toBeGreaterThan(0);
    expect(screen.getByText("P95 absolute error")).toBeInTheDocument();
    expect(screen.getByText("P95 positive error")).toBeInTheDocument();
    // Calibration version is in the header band
    expect(screen.getByRole("button", { name: /Active calibration version 1/i })).toBeInTheDocument();
    // No demand -> no purchase volume
    expect(screen.queryByTestId("buy-total")).not.toBeInTheDocument();
    expect(screen.getByText(/No demand entered, so no purchase volume/)).toBeInTheDocument();
    // Explanation on its own tab
    await userEvent.click(screen.getByRole("tab", { name: "How it's calculated" }));
    expect(screen.getByText("Why this estimate")).toBeInTheDocument();
    expect(screen.getByText("Decision support only")).toBeInTheDocument();
  });

  it("renders the exact forecast table in UK local hours", async () => {
    mockFetch(base());
    render(<App />);
    await load();
    await userEvent.click(await screen.findByRole("tab", { name: "Wind outlook & risk" }));
    const table = await screen.findByRole("table", { name: /Hourly forecast values/i });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(25); // header + 24 hours
    expect(within(rows[1]).getByText("00:00")).toBeInTheDocument();
    expect(within(rows[1]).getByText("12,000")).toBeInTheDocument();
  });

  it("explains the empty state when no calibration exists and offers the initial run", async () => {
    mockFetch(base({ "GET /api/calibrations/active": { status: 404, body: errorBody("NO_ACTIVE_CALIBRATION", "none") } }));
    render(<App />);
    expect(await screen.findByText("Set up your calibration first")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run initial calibration" }));
    expect(window.location.hash).toBe("#/calibration");
  });

  it("surfaces an upstream error without fake data, and recovers on retry", async () => {
    let calls = 0;
    mockFetch(
      base({
        "GET /api/decisions/2026-01-15": () => {
          calls += 1;
          return calls === 1
            ? { status: 502, body: errorBody("ELEXON_UNAVAILABLE", "Elexon API responded with HTTP 503") }
            : { body: decision() };
        },
      }),
    );
    render(<App />);
    await load();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The Elexon data service is not responding right now.");
    expect(alert).toHaveTextContent("Elexon API responded with HTTP 503");
    expect(screen.queryByTestId("shortfall-buffer")).not.toBeInTheDocument();

    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("shortfall-buffer")).toBeInTheDocument();
    expect(calls).toBe(2);
  });

  it("explains why a calibration cannot support the decision (no silent future leakage)", async () => {
    mockFetch(
      base({
        "GET /api/decisions/2026-01-15": {
          status: 422,
          body: errorBody("CALIBRATION_UNAVAILABLE_AT_CUTOFF", "Calibration v2 has only 0 matched hours that were already observed by the decision cutoff"),
        },
      }),
    );
    render(<App />);
    await load();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The calibration cannot support this decision.");
    expect(alert).toHaveTextContent("already observed by the decision cutoff");
  });

  it("flags missing forecast hours instead of hiding them", async () => {
    mockFetch(base({ "GET /api/decisions/2026-01-15": { body: decision({}, ["05:00", "06:00"]) } }));
    render(<App />);
    await load();
    expect(await screen.findByTestId("shortfall-buffer")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Wind outlook & risk" }));
    expect(screen.getByText(/Missing hours: 05:00, 06:00 UK/)).toBeInTheDocument();
    expect(screen.getByText("incomplete")).toBeInTheDocument();
    expect(screen.getAllByText("No forecast published for this hour")).toHaveLength(2);
  });

  it("shows data-quality warnings from the API", async () => {
    mockFetch(
      base({
        "GET /api/decisions/2026-01-15": {
          body: decision({ warnings: [{ code: "LOW_SAMPLE", severity: "warning", message: "Only 120 calibration hours; tail percentiles are low-confidence." }] }),
        },
      }),
    );
    render(<App />);
    await load();
    expect(await screen.findByText(/tail percentiles are low-confidence/)).toBeInTheDocument();
  });

  it("shows an unavailable state, not zeros, when there are no matched observations", async () => {
    mockFetch(base({ "GET /api/decisions/2026-01-15": { body: decision({ metrics: { ...metrics, n: 0, mae_mw: null, rmse_mw: null, bias_mw: null, p90_abs_error_mw: null, p95_abs_error_mw: null, share_overforecast: null, p90_positive_error_mw: null, p95_positive_error_mw: null } }) } }));
    render(<App />);
    await load();
    await userEvent.click(await screen.findByRole("tab", { name: "Wind outlook & risk" }));
    expect(screen.getByText(/Metrics unavailable: no matched hours/)).toBeInTheDocument();
  });

  it("validates the delivery date window and blocks submission", async () => {
    const f = mockFetch(base());
    render(<App />);
    await screen.findByRole("button", { name: /Load analysis/ });
    const date = screen.getByLabelText("Delivery date");
    fireEvent.change(date, { target: { value: "2026-02-03" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a date between 1 Jan 2026 and 31 Jan 2026.");
    expect(screen.getByRole("button", { name: /Load analysis/ })).toBeDisabled();
    await new Promise((r) => setTimeout(r, 100));
    expect(f.count("GET", "/api/decisions/2026-02-03")).toBe(0);
  });

  it("validates the cutoff time format", async () => {
    mockFetch(base());
    render(<App />);
    await screen.findByRole("button", { name: /Load analysis/ });
    fireEvent.change(screen.getByLabelText("Forecast cutoff (UK time)"), { target: { value: "" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a time as HH:MM");
    expect(screen.getByRole("button", { name: /Load analysis/ })).toBeDisabled();
  });

  it("sends the chosen date, cutoff and percentile only on load, and states the decision instant", async () => {
    const seen: string[] = [];
    const f = mockFetch(
      base({
        "GET /api/decisions/2026-01-20": (url) => {
          seen.push(url.search);
          return { body: decision({ delivery_date: "2026-01-20" }) };
        },
      }),
    );
    render(<App />);
    await screen.findByRole("button", { name: /Load analysis/ });
    fireEvent.change(screen.getByLabelText("Delivery date"), { target: { value: "2026-01-20" } });
    fireEvent.change(screen.getByLabelText("Forecast cutoff (UK time)"), { target: { value: "12:30" } });
    await userEvent.click(screen.getByRole("radio", { name: "P90" }));
    expect(screen.getByText(/published by this time on Mon, 19 Jan 2026/)).toBeInTheDocument();
    // Still nothing fetched: changing inputs does not calculate
    expect(f.count("GET", "/api/decisions/2026-01-20")).toBe(0);
    await userEvent.click(screen.getByRole("button", { name: /Load analysis/ }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]).toContain("cutoff=12%3A30");
    expect(seen[0]).toContain("percentile=90");
    expect(f.count("GET", "/api/decisions/2026-01-20")).toBe(1);
  });

  it("changing the percentile does not fetch until Load analysis is pressed again", async () => {
    const seen: string[] = [];
    mockFetch(
      base({
        "GET /api/decisions/2026-01-15": (url) => {
          seen.push(url.searchParams.get("percentile") ?? "");
          return { body: decision() };
        },
      }),
    );
    render(<App />);
    await load();
    await screen.findByTestId("shortfall-buffer");
    expect(seen).toEqual(["95"]);
    await userEvent.click(screen.getByRole("radio", { name: "P90" }));
    await new Promise((r) => setTimeout(r, 150));
    expect(seen).toEqual(["95"]); // no fetch on percentile change alone
    await userEvent.click(screen.getByRole("button", { name: /Load analysis/ }));
    await waitFor(() => expect(seen).toEqual(["95", "90"]));
  });

  it("shows a clear error when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Cannot reach the application server");
    expect(within(alert).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
