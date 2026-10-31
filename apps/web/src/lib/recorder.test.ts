// @vitest-environment node

import { describe, expect, it } from "vitest";

import { encodeWav } from "./recorder";

describe("encodeWav", () => {
  it("writes a 16 kHz mono 16-bit PCM header and clamps samples", async () => {
    const wav = encodeWav(new Float32Array([0, 1, -1, 2]), 16_000);
    const view = new DataView(await wav.arrayBuffer());
    const tag = (at: number) => String.fromCharCode(...new Uint8Array(view.buffer, at, 4));
    expect([tag(0), tag(8), tag(12), tag(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(8); // 4 samples x 2 bytes
    expect([view.getInt16(44, true), view.getInt16(46, true), view.getInt16(48, true), view.getInt16(50, true)]).toEqual([
      0, 32767, -32767, 32767,
    ]);
  });
});
