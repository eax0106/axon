import { describe, expect, it } from "vitest";

import { gridColumns, retryWaits, stepLabel, tally } from "./campaigns";

describe("campaign figures", () => {
  it("tallies contacts by status with every status present", () => {
    expect(tally([{ status: "done" }, { status: "done" }, { status: "calling" }])).toEqual({
      pending: 0,
      calling: 1,
      callback: 0,
      done: 2,
      exhausted: 0,
      skipped: 0,
      canceled: 0,
    });
  });
  it("gives each retry its ladder step and repeats the last one", () => {
    expect(retryWaits(4, [10, "next_day"])).toEqual([10, "next_day", "next_day", "next_day"]);
    expect(retryWaits(1, [10, 60, 120])).toEqual([10]);
    expect(retryWaits(0, [10])).toEqual([]);
  });
  it("names a step in plain words", () => {
    expect([stepLabel(45), stepLabel(120), stepLabel("next_day")]).toEqual(["45 min", "2 h", "the next open day"]);
  });
  it("lays dots out wider than tall and fits them all", () => {
    for (const n of [1, 10, 100, 2000]) {
      const cols = gridColumns(n);
      const rows = Math.ceil(n / cols);
      expect(cols * rows).toBeGreaterThanOrEqual(n);
      if (n > 10) expect(cols).toBeGreaterThan(rows);
    }
  });
});
