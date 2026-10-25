import { addDays, daysInclusive, fmtDate, fmtUkDateTime, mw, pct } from "./format";

describe("format helpers", () => {
  it("formats MW with separators, sign and an em dash for unavailable values", () => {
    expect(mw(12115.2)).toBe("12,115");
    expect(mw(-1449.5, { signed: true })).toBe("−1,450");
    expect(mw(1449.5, { signed: true })).toBe("+1,450");
    expect(mw(null)).toBe("—");
    expect(mw(Number.NaN)).toBe("—");
  });

  it("formats percentages", () => {
    expect(pct(0.729)).toBe("73%");
    expect(pct(null)).toBe("—");
  });

  it("shows UTC instants in UK local time (GMT in winter, BST in summer)", () => {
    expect(fmtUkDateTime("2026-01-14T15:30:00Z")).toBe("14 Jan 2026, 15:30");
    expect(fmtUkDateTime("2025-07-01T15:30:00Z")).toBe("1 Jul 2025, 16:30");
    // 23:30 UTC on 1 July is already 2 July in the UK
    expect(fmtUkDateTime("2025-07-01T23:30:00Z")).toBe("2 Jul 2025, 00:30");
  });

  it("formats business dates without timezone drift", () => {
    expect(fmtDate("2026-01-01")).toBe("1 Jan 2026");
    expect(fmtDate(null)).toBe("—");
  });

  it("does date arithmetic on strings", () => {
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(daysInclusive("2025-10-01", "2025-12-31")).toBe(92);
  });
});
