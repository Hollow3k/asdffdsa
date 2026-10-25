import { DEFAULT_FORM, HOURS, parsePlan, type PlanForm } from "./planForm";

const form = (over: Partial<PlanForm> = {}): PlanForm => ({ ...DEFAULT_FORM, ...over });

describe("parsePlan", () => {
  it("produces no request until demand is entered", () => {
    const p = parsePlan(form());
    expect(p.hasDemand).toBe(false);
    expect(p.request).toBeNull();
    expect(p.valid).toBe(true);
  });

  it("builds a flat-demand request with sensible defaults", () => {
    expect(parsePlan(form({ demand: "15,000" })).request).toEqual({ demand_mw: 15000, contracted_mw: 0, wind_share_pct: 100 });
    expect(parsePlan(form({ demand: "250.5", contracted: "100", share: "0.5" })).request).toEqual({
      demand_mw: 250.5,
      contracted_mw: 100,
      wind_share_pct: 0.5,
    });
  });

  it("accepts zero but rejects negatives, text and absurd sizes", () => {
    expect(parsePlan(form({ demand: "0" })).request?.demand_mw).toBe(0);
    for (const bad of ["-5", "abc", "1e3", "12 000", "5,,", "99999999"]) {
      const p = parsePlan(form({ demand: bad }));
      expect(p.errors.demand, bad).toBeTruthy();
      expect(p.request, bad).toBeNull();
    }
  });

  it("validates contracted supply and wind share", () => {
    expect(parsePlan(form({ demand: "1", contracted: "x" })).errors.contracted).toBeTruthy();
    expect(parsePlan(form({ demand: "1", share: "101" })).errors.share).toBeTruthy();
    expect(parsePlan(form({ demand: "1", share: "" })).errors.share).toBeTruthy();
    expect(parsePlan(form({ demand: "1", share: "0" })).request?.wind_share_pct).toBe(0);
  });

  it("requires every hour once hourly mode has any value", () => {
    const hourly = Array.from({ length: HOURS }, () => "100");
    expect(parsePlan(form({ hourly })).request?.demand_by_hour_mw).toHaveLength(HOURS);
    expect(parsePlan(form({ hourly: hourly.map((v, i) => (i === 3 ? "" : v)) })).errors.hourly).toBeTruthy();
    expect(parsePlan(form({ hourly: Array.from({ length: HOURS }, () => "") })).hasDemand).toBe(false);
  });

  it("does not send a flat demand when hourly mode is active", () => {
    const r = parsePlan(form({ demand: "999", hourly: Array.from({ length: HOURS }, () => "5") })).request;
    expect(r).not.toHaveProperty("demand_mw");
  });
});
