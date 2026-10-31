import { describe, expect, it } from "vitest";

import { ago, credits } from "./format";

describe("money and time formatting", () => {
  it("shows credits in Indian grouping with at most two decimals", () => {
    expect(credits("100000")).toBe("1,00,000");
    expect(credits("1234567.891")).toBe("12,34,567.89");
    expect(credits("-12.50")).toBe("-12.5");
    expect(credits("50.0000")).toBe("50");
  });
  it("says how long ago, in minutes, hours or days", () => {
    const now = Date.parse("2026-10-31T10:00:00Z");
    expect(ago("2026-10-31T09:55:00Z", now)).toBe("5 minutes ago");
    expect(ago("2026-10-31T07:00:00Z", now)).toBe("3 hours ago");
    expect(ago("2026-10-30T09:00:00Z", now)).toBe("yesterday");
  });
});
