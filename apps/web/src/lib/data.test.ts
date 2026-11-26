import { describe, expect, it } from "vitest";

import { boardColumns, cleanFilters, columnLabel, duration, outcomeLabel, percent } from "./data";

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

describe("outcomeLabel", () => {
  it("reads an employee's own outcome as words and a built-in one by its label", () => {
    expect(outcomeLabel("interested", "site_visit_booked")).toBe("Site visit booked");
    expect(outcomeLabel("callback_requested")).toBe("Call back");
    expect(outcomeLabel(null, null, "Not called yet")).toBe("Not called yet");
    expect(outcomeLabel("something_new")).toBe("something_new");
  });
});

describe("boardColumns", () => {
  it("puts built-ins first, then the employees' own outcomes, then leads not called yet", () => {
    const counts = { no_outcome: 2, site_visit_booked: 1, interested: 3, brochure_sent: 1, other: 0 };
    expect(boardColumns(counts)).toEqual(["interested", "brochure_sent", "site_visit_booked", "no_outcome"]);
    expect(columnLabel("site_visit_booked")).toBe("Site visit booked");
    expect(columnLabel("no_outcome")).toBe("Not called yet");
  });
});
