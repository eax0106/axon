import { describe, expect, it } from "vitest";

import { toWindows } from "./inbound";

describe("opening hours", () => {
  it("keeps a daytime window as one", () => {
    expect(toWindows([0, 1, 2], 540, 1080)).toEqual([{ days: [0, 1, 2], start_min: 540, end_min: 1080 }]);
  });
  it("splits an overnight window at midnight, the early part on the following days", () => {
    expect(toWindows([4, 5, 6], 22 * 60, 2 * 60)).toEqual([
      { days: [4, 5, 6], start_min: 1320, end_min: 1440 },
      { days: [0, 5, 6], start_min: 0, end_min: 120 },
    ]);
  });
  it("needs no early part when the window ends at midnight", () => {
    expect(toWindows([0], 1200, 0)).toEqual([{ days: [0], start_min: 1200, end_min: 1440 }]);
  });
});
