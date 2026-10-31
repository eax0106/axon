import { describe, expect, it } from "vitest";

import { cleanFilters, duration, percent } from "./data";

describe("conversation filters and figures", () => {
  it("sends only filters that are set", () => {
    expect(cleanFilters({ q: "", outcome: "interested", include_test: false, min_duration: 0, employee_id: undefined })).toEqual({
      outcome: "interested",
      min_duration: 0,
    });
  });
  it("shows durations as m:ss and rates as whole percent, with a dash when unknown", () => {
    expect([duration(75), duration(0), duration(null)]).toEqual(["1:15", "0:00", "–"]);
    expect([percent(0.456), percent(0), percent(null)]).toEqual(["46%", "0%", "–"]);
  });
});
