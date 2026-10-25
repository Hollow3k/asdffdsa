import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { config, detail } from "./fixtures";
import { mockFetch } from "./mockApi";

describe("Landing page", () => {
  it("is the default route and fetches nothing from the backend", async () => {
    window.location.hash = "";
    const f = mockFetch({ "GET /api/config": { body: config }, "GET /api/calibrations/active": { body: detail() } });
    render(<App />);
    expect(await screen.findByText(/before the wind decides/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Get started/ })).toBeInTheDocument();
    // Landing is static: it must not call the API (not even config).
    await new Promise((r) => setTimeout(r, 100));
    expect(f.calls).toHaveLength(0);
  });

  it("links the GitHub button to the public repo", () => {
    window.location.hash = "";
    mockFetch({ "GET /api/config": { body: config } });
    render(<App />);
    const repo = screen.getByRole("link", { name: /GitHub repo/ });
    expect(repo).toHaveAttribute("href", "https://github.com/Hollow3k/asdffdsa");
    expect(repo).toHaveAttribute("target", "_blank");
  });

  it("Get started routes into the dashboard", async () => {
    window.location.hash = "";
    mockFetch({ "GET /api/config": { body: config }, "GET /api/calibrations/active": { body: detail() } });
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: /Get started/ }));
    expect(window.location.hash).toBe("#/decision");
    // The dashboard header now appears
    expect(await screen.findByRole("button", { name: /Load analysis/ })).toBeInTheDocument();
  });
});
