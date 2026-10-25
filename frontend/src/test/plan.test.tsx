import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { planSummary, planToCsv } from "../features/decision/PlanResults";
import { config, decision, detail, plan } from "./fixtures";
import { errorBody, mockFetch, type Handler } from "./mockApi";

interface Body {
  cutoff: string;
  percentile: number;
  demand_mw?: number;
  demand_by_hour_mw?: number[];
  contracted_mw: number;
  wind_share_pct: number;
}

/** Fake backend whose purchase plan is computed from the request body, like the real one. */
function routes(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    "GET /api/config": { body: config },
    "GET /api/calibrations/active": { body: detail() },
    "GET /api/decisions/2026-01-15": { body: decision() },
    "POST /api/decisions/2026-01-15/procurement": (_url, init) => {
      const b = JSON.parse(String(init?.body)) as Body;
      return { body: plan({ demand: b.demand_by_hour_mw ?? b.demand_mw, contracted: b.contracted_mw, share: b.wind_share_pct }) };
    },
    ...extra,
  };
}

const postBodies = (f: ReturnType<typeof mockFetch>) => f.calls.filter((c) => c.method === "POST").map((c) => c.body as Body);
const loadBtn = () => screen.getByRole("button", { name: /Load analysis|Reload analysis/ });

// The dashboard is behind the #/decision route; the default route is now the landing page.
beforeEach(() => {
  window.location.hash = "#/decision";
});

async function typeDemand(value: string) {
  const input = await screen.findByLabelText(/Expected demand/);
  await userEvent.clear(input);
  await userEvent.type(input, value);
}

/** Enter a flat demand and load the analysis. */
async function loadWithDemand(value: string) {
  await typeDemand(value);
  await userEvent.click(loadBtn());
}

describe("Purchase plan", () => {
  it("calculates nothing until demand is entered and Load analysis is pressed", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await typeDemand("15000");
    // typing alone does not fetch
    await new Promise((r) => setTimeout(r, 200));
    expect(postBodies(f)).toHaveLength(0);
    expect(screen.queryByTestId("buy-total")).not.toBeInTheDocument();
    await userEvent.click(loadBtn());
    expect(await screen.findByTestId("buy-total")).toBeInTheDocument();
  });

  it("shows the recommended purchase, sending exactly what was entered", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await loadWithDemand("15000");

    const total = await screen.findByTestId("buy-total");
    const expected = plan({ demand: 15000 }).scenarios.find((s) => s.key === "cautious")!.buy_total_mwh;
    expect(total).toHaveTextContent(Math.round(expected).toLocaleString("en-GB"));
    expect(screen.getByText(/Recommended purchase/)).toBeInTheDocument();
    expect(postBodies(f)).toHaveLength(1);
    expect(postBodies(f)[0]).toEqual({ cutoff: "17:00", percentile: 95, demand_mw: 15000, contracted_mw: 0, wind_share_pct: 100 });
    expect(await screen.findByRole("table", { name: /Hourly purchase plan/i })).toBeInTheDocument();
  });

  it("switches between As published / Expected / Cautious without another request", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await loadWithDemand("15000");
    const total = await screen.findByTestId("buy-total");
    const p = plan({ demand: 15000 });
    const by = Object.fromEntries(p.scenarios.map((s) => [s.key, Math.round(s.buy_total_mwh).toLocaleString("en-GB")]));
    expect(total).toHaveTextContent(by.cautious);

    await userEvent.click(screen.getByRole("radio", { name: /As published/ }));
    expect(screen.getByTestId("buy-total")).toHaveTextContent(by.forecast);
    expect(screen.getByText(/Purchase if wind as published/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /^Expected/ }));
    expect(screen.getByTestId("buy-total")).toHaveTextContent(by.expected);
    await userEvent.click(screen.getByRole("radio", { name: /^Cautious/ }));
    expect(screen.getByTestId("buy-total")).toHaveTextContent(by.cautious);
    expect(postBodies(f)).toHaveLength(1); // switching the wind case is client-side
    expect(p.scenarios[2].buy_total_mwh).toBeGreaterThanOrEqual(p.scenarios[0].buy_total_mwh);
  });

  it("passes existing contracts and wind share to the server on load", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await typeDemand("20000");
    await userEvent.type(screen.getByLabelText(/Existing contracted supply/), "3000");
    const share = screen.getByLabelText(/Share of GB wind/);
    await userEvent.clear(share);
    await userEvent.type(share, "0.5");
    await userEvent.click(loadBtn());
    await waitFor(() => expect(postBodies(f).at(-1)).toEqual({ cutoff: "17:00", percentile: 95, demand_mw: 20000, contracted_mw: 3000, wind_share_pct: 0.5 }));
  });

  it("supports demand hour by hour, seeded from the single value", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await typeDemand("10000");
    await userEvent.click(screen.getByRole("button", { name: "Set demand hour by hour instead" }));
    const evening = screen.getByLabelText("Demand at 18:00 (MW)");
    expect(evening).toHaveValue("10000");
    fireEvent.change(evening, { target: { value: "18000" } });
    await userEvent.click(loadBtn());
    await waitFor(() => expect(postBodies(f).at(-1)?.demand_by_hour_mw?.[18]).toBe(18000));
    const body = postBodies(f).at(-1)!;
    expect(body.demand_by_hour_mw).toHaveLength(24);
    expect(body.demand_mw).toBeUndefined();
    expect(body.demand_by_hour_mw!.filter((v) => v === 10000)).toHaveLength(23);
  });

  it("rejects invalid numbers inline, disables load, and never calls the server", async () => {
    const f = mockFetch(routes());
    render(<App />);
    await typeDemand("abc");
    expect(await screen.findByText("Enter demand as a positive number of MW.")).toBeInTheDocument();
    expect(loadBtn()).toBeDisabled();
    await userEvent.clear(screen.getByLabelText(/Expected demand/));
    await userEvent.type(screen.getByLabelText(/Expected demand/), "100");
    fireEvent.change(screen.getByLabelText(/Share of GB wind/), { target: { value: "150" } });
    expect(await screen.findByText("Cannot be more than 100%.")).toBeInTheDocument();
    expect(loadBtn()).toBeDisabled();
    expect(postBodies(f)).toHaveLength(0);
  });

  it("shows a clear 'no purchase needed' result and the wind-share hint", async () => {
    mockFetch(
      routes({
        "POST /api/decisions/2026-01-15/procurement": {
          body: plan({ demand: 500 }, { warnings: [{ code: "NO_PURCHASE_NEEDED", severity: "info", message: "Wind (even in the cautious case) plus your existing contracts covers your demand. Lower the wind share to the portion you can access." }] }),
        },
      }),
    );
    render(<App />);
    await loadWithDemand("500");
    expect(await screen.findByText(/No purchase is needed in this case/)).toBeInTheDocument();
    expect(screen.getByTestId("buy-total")).toHaveTextContent("0");
    expect(screen.getByText(/Lower the wind share/)).toBeInTheDocument();
  });

  it("flags hours without a forecast as not planned", async () => {
    mockFetch(
      routes({
        "POST /api/decisions/2026-01-15/procurement": {
          body: plan({ demand: 15000, missing: ["05:00"] }, { warnings: [{ code: "HOURS_NOT_PLANNED", severity: "warning", message: "1 of 24 hours have no forecast, so no purchase volume can be calculated for them." }] }),
        },
      }),
    );
    render(<App />);
    await loadWithDemand("15000");
    await screen.findByTestId("buy-total");
    expect(screen.getByText(/no purchase volume can be calculated for them/)).toBeInTheDocument();
    expect(screen.getByText("1 hour(s) not planned")).toBeInTheDocument();
    expect(screen.getByText("No forecast for this hour: not planned")).toBeInTheDocument();
  });

  it("shows the server's error when the purchase cannot be calculated", async () => {
    mockFetch(routes({ "POST /api/decisions/2026-01-15/procurement": { status: 422, body: errorBody("INVALID_PROFILE_LENGTH", "Expected 24 hourly demand values, got 23") } }));
    render(<App />);
    await loadWithDemand("15000");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not calculate the purchase volume");
    expect(alert).toHaveTextContent("Expected 24 hourly demand values, got 23");
  });

  it("lists the assumptions behind the number on the 'How it's calculated' tab", async () => {
    mockFetch(routes());
    render(<App />);
    await loadWithDemand("15000");
    await screen.findByTestId("buy-total");
    await userEvent.click(screen.getByRole("tab", { name: "How it's calculated" }));
    expect(screen.getByText("What the purchase volume assumes")).toBeInTheDocument();
    expect(screen.getByText(/max\(0, demand - existing contracted supply - wind\)/)).toBeInTheDocument();
  });

  it("remembers the inputs in this browser; after loading they drive the request", async () => {
    window.localStorage.setItem("windplan.inputs.v1", JSON.stringify({ demand: "14000", hourly: null, contracted: "", share: "100" }));
    const f = mockFetch(routes());
    render(<App />);
    expect(await screen.findByLabelText(/Expected demand/)).toHaveValue("14000");
    await userEvent.click(loadBtn());
    await waitFor(() => expect(postBodies(f)[0]?.demand_mw).toBe(14000));
  });

  it("steps to the next day with the arrow button once an analysis is loaded", async () => {
    const seen: string[] = [];
    mockFetch(
      routes({
        "GET /api/decisions/2026-01-16": () => {
          seen.push("16");
          return { body: decision({ delivery_date: "2026-01-16" }) };
        },
      }),
    );
    render(<App />);
    await loadWithDemand("15000");
    await screen.findByTestId("buy-total");
    await userEvent.click(screen.getByRole("button", { name: "Next day" }));
    await waitFor(() => expect(seen).toEqual(["16"]));
    expect(screen.getByLabelText("Delivery date")).toHaveValue("2026-01-16");
  });

  it("disables stepping outside the January window", async () => {
    mockFetch(routes());
    render(<App />);
    await screen.findByRole("button", { name: /Load analysis/ });
    fireEvent.change(screen.getByLabelText("Delivery date"), { target: { value: "2026-01-01" } });
    expect(screen.getByRole("button", { name: "Previous day" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Delivery date"), { target: { value: "2026-01-31" } });
    expect(screen.getByRole("button", { name: "Next day" })).toBeDisabled();
  });

  it("keeps tab navigation accessible with the keyboard", async () => {
    mockFetch(routes());
    render(<App />);
    await loadWithDemand("15000");
    await screen.findByTestId("buy-total");
    const tabs = screen.getByRole("tablist", { name: "Result sections" });
    const plan0 = within(tabs).getByRole("tab", { name: "Hourly plan" });
    expect(plan0).toHaveAttribute("aria-selected", "true"); // demand present -> plan tab first
    plan0.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(within(tabs).getByRole("tab", { name: "Wind outlook & risk" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Plan exports", () => {
  it("writes a CSV with one row per hour and the chosen wind case", () => {
    const p = plan({ demand: 15000, missing: ["05:00"] });
    const csv = planToCsv(p, "cautious").trim().split("\n");
    expect(csv[0]).toBe("hour_uk,demand_mw,existing_contracts_mw,wind_mw_cautious,to_buy_mw,surplus_wind_mw");
    expect(csv).toHaveLength(25);
    expect(csv[1].startsWith("00:00,15000.0,0.0,")).toBe(true);
    expect(csv[6]).toBe("05:00,15000.0,0.0,,,"); // unplanned hour: blank, never a guess
  });

  it("produces a plain-text summary with the number, forecast time and caveat", () => {
    const text = planSummary(plan({ demand: 15000 }), "cautious", decision());
    expect(text).toMatch(/BUY [\d,]+ MWh/);
    expect(text).toContain("14 Jan 2026, 15:30");
    expect(text).toContain("Decision support only");
  });
});
