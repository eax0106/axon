import { describe, expect, it } from "vitest";

import { fromPcm16Base64, toPcm16Base64 } from "./pcm";

describe("web-call PCM framing", () => {
  it("round-trips samples through 16-bit little-endian base64 and clamps", () => {
    const back = fromPcm16Base64(toPcm16Base64(new Float32Array([0, 0.5, -0.5, 1, -2])));
    expect([...back].map((v) => Math.round(v * 1000) / 1000)).toEqual([0, 0.5, -0.5, 1, -1]);
  });
  it("encodes little-endian as the engine expects", () => {
    expect(atob(toPcm16Base64(new Float32Array([1]))).split("").map((c) => c.charCodeAt(0))).toEqual([0xff, 0x7f]);
  });
});
