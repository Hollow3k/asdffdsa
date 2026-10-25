import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { RunCalibration } from "../features/calibration/RunCalibration";
import { config, detail, metrics, summary } from "./fixtures";
import { errorBody, mockFetch, type Handler } from "./mockApi";

const none = { status: 404, body: errorBody("NO_ACTIVE_CALIBRATION", "none") };

function renderPage(routes: Record<string, Handler>) {
  const f = mockFetch({ "GET /api/config": { body: config }, ...routes });
  window.location.hash = "#/calibration";
  render(<App />);
  return f;
}

describe("Calibration management", () => {
  it("first run: shows no calibration and an explicit Run initial calibration action with default range", async () => {
    renderPage({ "GET /api/calibrations/active": none, "GET /api/calibrations": { body: [] } });
    expect(await screen.findByText("No calibration exists yet")).toBeInTheDocument();
    expect(screen.getByLabelText("Calibration start date")).toHaveValue("2025-10-01");
    expect(screen.getByLabelText("Calibration end date")).toHaveValue("2025-12-31");
    expect(screen.getByRole("button", { name: "Run initial calibration" })).toBeEnabled();
  });

  it("runs the initial calibration with progress, then reports success and the active version", async () => {
    let polls = 0;
    const f = renderPage({
      "GET /api/calibrations/active": none,
      "GET /api/calibrations": { body: [] },
      "POST /api/calibrations": { status: 202, body: summary({ id: "cal-1", status: "pending", is_active: false, progress: 0, stage: "Queued", completed_at: null, n_matched: null }) },
      "GET /api/calibrations/cal-1": () => {
        polls += 1;
        return polls < 2
          ? { body: detail({ status: "running", is_active: false, progress: 45, stage: "Fetching Forecast vintages 2025-10-01", metrics: null, breakdowns: null }) }
          : { body: detail() };
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Run initial calibration" }));

    expect(await screen.findByRole("progressbar", { name: "Calibration progress" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/Fetching Forecast vintages/)).toBeInTheDocument(), { timeout: 3000 });
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "45");

    expect(await screen.findByText(/Version 1 calculated/, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/now the active calibration/)).toBeInTheDocument();
    expect(f.calls.find((c) => c.method === "POST")?.body).toEqual({ start_date: "2025-10-01", end_date: "2025-12-31", cutoff_time: "17:00" });
  }, 15000);

  it("shows a failure and states that the previous active calibration is unchanged", async () => {
    const onFinished = vi.fn();
    mockFetch({
      "POST /api/calibrations": { status: 202, body: summary({ id: "cal-2", version: 2, status: "pending", is_active: false, progress: 0 }) },
      "GET /api/calibrations/cal-2": {
        body: detail({ id: "cal-2", version: 2, is_active: false, status: "failed", error_code: "ELEXON_UNAVAILABLE", error_message: "Elexon API responded with HTTP 503", metrics: null }),
      },
    });
    render(<RunCalibration config={config} active={detail()} versions={[summary()]} onFinished={onFinished} pollMs={5} />);
    await userEvent.click(screen.getByRole("button", { name: "Review calculation" }));
    await userEvent.click(screen.getByRole("button", { name: "Start calculation" }));

    const alert = await screen.findByText(/Version 2 failed/);
    expect(alert.closest("[role=alert]")).toHaveTextContent("Elexon API responded with HTTP 503");
    expect(screen.getByText(/Active calibration v1 is unchanged and still in use/)).toBeInTheDocument();
    expect(onFinished).toHaveBeenCalled();
  });

  it("recalculation: review step, then completion and explicit activation of the new version", async () => {
    const onFinished = vi.fn();
    const f = mockFetch({
      "POST /api/calibrations": { status: 202, body: summary({ id: "cal-2", version: 2, status: "pending", is_active: false, start_date: "2025-11-01", end_date: "2025-11-30" }) },
      "GET /api/calibrations/cal-2": { body: detail({ id: "cal-2", version: 2, is_active: false, start_date: "2025-11-01", end_date: "2025-11-30", metrics: { ...metrics, n: 720, mae_mw: 1700 }, warnings: [{ code: "LOW_SAMPLE", severity: "warning", message: "Only 720 matched hourly pairs" }] }) },
      "POST /api/calibrations/cal-2/activate": { body: detail({ id: "cal-2", version: 2, is_active: true }) },
    });
    render(<RunCalibration config={config} active={detail()} versions={[summary()]} onFinished={onFinished} pollMs={5} />);

    fireEvent.change(screen.getByLabelText("Calibration start date"), { target: { value: "2025-11-01" } });
    fireEvent.change(screen.getByLabelText("Calibration end date"), { target: { value: "2025-11-30" } });
    await userEvent.click(screen.getByRole("button", { name: "Review calculation" }));

    // Review before calculating
    expect(screen.getByText("Review before calculating")).toBeInTheDocument();
    expect(screen.getByText(/30 delivery days/)).toBeInTheDocument();
    expect(screen.getByText(/v1 \(1 Oct 2025 – 31 Dec 2025\) stays active/)).toBeInTheDocument();
    expect(f.count("POST", "/api/calibrations")).toBe(0); // nothing started yet
    await userEvent.click(screen.getByRole("button", { name: "Start calculation" }));

    expect(await screen.findByText(/Version 2 calculated/)).toBeInTheDocument();
    expect(screen.queryByText(/now the active calibration/)).not.toBeInTheDocument();
    expect(screen.getByText(/Only 720 matched hourly pairs/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /compared with the active calibration/i });
    expect(within(table).getByText("New v2")).toBeInTheDocument();
    expect(within(table).getByText("Active v1")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Activate version 2" }));
    expect(await screen.findByText(/now the active calibration/)).toBeInTheDocument();
    expect(f.count("POST", "/api/calibrations/cal-2/activate")).toBe(1);
    expect(onFinished).toHaveBeenLastCalledWith({ activated: true });
  });

  it("rejects an end date before the start date and an end date that is too recent", () => {
    render(<RunCalibration config={config} active={detail()} versions={[summary()]} onFinished={() => {}} />);
    fireEvent.change(screen.getByLabelText("Calibration end date"), { target: { value: "2025-09-30" } });
    expect(screen.getByRole("alert")).toHaveTextContent("End date must not be before the start date.");
    expect(screen.getByRole("button", { name: "Review calculation" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Calibration end date"), { target: { value: "2026-10-25" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Latest allowed end date is 24 Oct 2026");
  });

  it("warns that a range reaching into January is trimmed per decision", () => {
    render(<RunCalibration config={config} active={detail()} versions={[summary()]} onFinished={() => {}} />);
    fireEvent.change(screen.getByLabelText("Calibration end date"), { target: { value: "2026-01-20" } });
    expect(screen.getByText("Range reaches into the decision window")).toBeInTheDocument();
  });

  it("surfaces a rejected start (409 job already running) without leaving the form", async () => {
    mockFetch({ "POST /api/calibrations": { status: 409, body: errorBody("CALIBRATION_IN_PROGRESS", "Calibration version 3 is still running; wait for it to finish.") } });
    render(<RunCalibration config={config} active={null} versions={[]} onFinished={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Run initial calibration" }));
    expect(await screen.findByText(/still running; wait for it to finish/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run initial calibration" })).toBeInTheDocument();
  });

  it("resumes tracking a calibration that is already running after a page reload", async () => {
    mockFetch({ "GET /api/calibrations/cal-3": { body: detail({ id: "cal-3", version: 3, is_active: false, status: "running", progress: 60, stage: "Aligning forecasts with actuals", metrics: null }) } });
    render(<RunCalibration config={config} active={detail()} versions={[summary(), summary({ id: "cal-3", version: 3, status: "running", is_active: false, progress: 60 })]} onFinished={() => {}} pollMs={5} />);
    expect(await screen.findByText(/Calculating version 3/)).toBeInTheDocument();
    expect(await screen.findByText(/Aligning forecasts with actuals/)).toBeInTheDocument();
  });

  it("lists versions and reactivates an earlier one", async () => {
    let activeId = "cal-2";
    const versions = () => [
      summary({ id: "cal-2", version: 2, is_active: activeId === "cal-2", start_date: "2025-11-01", end_date: "2025-11-30", n_matched: 720 }),
      summary({ id: "cal-1", version: 1, is_active: activeId === "cal-1" }),
    ];
    const f = renderPage({
      "GET /api/calibrations/active": () => ({ body: detail({ id: activeId, version: activeId === "cal-2" ? 2 : 1 }) }),
      "GET /api/calibrations": () => ({ body: versions() }),
      "GET /api/calibrations/cal-1": () => ({ body: detail({ id: "cal-1", version: 1, is_active: activeId === "cal-1" }) }),
      "GET /api/calibrations/cal-2": () => ({ body: detail({ id: "cal-2", version: 2, is_active: activeId === "cal-2" }) }),
      "POST /api/calibrations/cal-1/activate": () => {
        activeId = "cal-1";
        return { body: detail({ id: "cal-1", version: 1, is_active: true }) };
      },
    });
    const table = await screen.findByRole("table", { name: "Calibration versions" });
    expect(within(table).getAllByRole("row")).toHaveLength(3); // header + 2 versions
    // v2 is active, so it offers no Activate button; v1 can be reactivated.
    expect(within(table).queryByRole("button", { name: "Activate version 2" })).not.toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: "Activate version 1" }));

    await waitFor(() => expect(f.count("POST", "/api/calibrations/cal-1/activate")).toBe(1));
    // After the refresh, the roles swap: v2 can now be activated, v1 cannot.
    expect(await within(table).findByRole("button", { name: "Activate version 2" })).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: "Activate version 1" })).not.toBeInTheDocument();
  });

  it("shows warnings and an unavailable state for the inspected calibration", async () => {
    renderPage({
      "GET /api/calibrations/active": { body: detail({ warnings: [{ code: "LOW_SAMPLE", severity: "warning", message: "Only 120 matched hourly pairs" }], sample_size_note: "Only 120 matched hours (< 500): treat tail percentiles as low-confidence." }) },
      "GET /api/calibrations": { body: [summary({ warning_count: 1 })] },
      "GET /api/calibrations/cal-1": { body: detail({ warnings: [{ code: "LOW_SAMPLE", severity: "warning", message: "Only 120 matched hourly pairs" }], sample_size_note: "Only 120 matched hours (< 500): treat tail percentiles as low-confidence." }) },
    });
    expect(await screen.findByText("Only 120 matched hourly pairs")).toBeInTheDocument();
    expect(screen.getByText(/treat tail percentiles as low-confidence/)).toBeInTheDocument();
    expect(screen.getByText("P95 positive error")).toBeInTheDocument();
  });
});
