import { describe, expect, it } from "vitest";

import { gridColumns, tally } from "./campaigns";

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
  it("lays dots out wider than tall and fits them all", () => {
    for (const n of [1, 10, 100, 2000]) {
      const cols = gridColumns(n);
      const rows = Math.ceil(n / cols);
      expect(cols * rows).toBeGreaterThanOrEqual(n);
      if (n > 10) expect(cols).toBeGreaterThan(rows);
    }
  });
});
