import { describe, expect, it } from "vitest";

import { fromClock, toClock, wait } from "./instant";

describe("dialer conversions", () => {
  it("turns the stored window minutes into clock times and back", () => {
    expect([toClock(540), toClock(1260), toClock(365)]).toEqual(["09:00", "21:00", "06:05"]);
    expect([fromClock("09:00"), fromClock("21:30"), fromClock("06:00")]).toEqual([540, 1290, 360]);
  });
  it("says retry waits the way an owner reads them", () => {
    expect([wait(10), wait(60), wait(180), wait(1440), wait(1570)]).toEqual(["10 min", "1 h", "3 h", "1 day", "1 day 2 h 10 min"]);
  });
});
