import { describe as group, expect, it } from "vitest";

import { describe } from "./timeline";

group("timeline words", () => {
  it("says which leg failed over, from whom to whom", () => {
    expect(describe({ type: "failover", data: { leg: "tts", from: "cartesia", to: "sarvam" } })).toBe(
      "Switched voice from Cartesia to Sarvam to stay on the call",
    );
  });
  it("says what a cheaper voice means for the bill", () => {
    expect(describe({ type: "tier_fallback", data: { tier: "value" } })).toBe(
      "A cheaper voice took over, so the call is billed at value rates",
    );
  });
  it("explains why a call ended, and falls back to the raw reason", () => {
    expect(describe({ type: "ended", data: { reason: "silence" } })).toBe("Ended because the caller went quiet");
    expect(describe({ type: "ended", data: { reason: "odd_reason" } })).toBe("Ended because odd reason");
  });
  it("hides bookkeeping and keeps unknown events readable", () => {
    expect(describe({ type: "usage", data: {} })).toBeNull();
    expect(describe({ type: "something_new" })).toBe("something new");
  });
});
