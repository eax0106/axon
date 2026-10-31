import { describe, expect, it } from "vitest";

import { type Entry, dailySpend, runwayDays } from "./billing";

const entry = (at: string, amount: string, kind = "call"): Entry => ({ id: 1, at, kind, amount, balance_after: "0", note: null });

describe("spend maths", () => {
  // 31 Oct 2026, 10:00 IST
  const now = Date.parse("2026-10-31T04:30:00Z");

  it("buckets spending by Indian calendar day and ignores money coming in", () => {
    const daily = dailySpend(
      [
        entry("2026-10-31T03:00:00Z", "-12.50"), // today IST
        entry("2026-10-30T19:00:00Z", "-2.50"), // 00:30 IST on the 31st: still today
        entry("2026-10-30T10:00:00Z", "-5"), // yesterday
        entry("2026-10-30T10:00:00Z", "500", "topup"),
        entry("2026-10-29T10:00:00Z", "-3", "refund"),
        entry("2026-09-01T10:00:00Z", "-99"), // outside the window
      ],
      3,
      now,
    );
    expect(daily).toEqual([0, 5, 15]);
  });

  it("estimates runway from the average, and has none without spending", () => {
    expect(runwayDays(100, [10, 10, 10])).toBe(10);
    expect(runwayDays(100, [0, 0])).toBeNull();
  });
});
