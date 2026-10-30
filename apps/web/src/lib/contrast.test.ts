import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(__dirname, "../styles.css"), "utf8");

// WCAG 2 contrast of two #rrggbb colours.
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** The hex tokens of one theme block in styles.css. */
function tokens(css: string, selector: string) {
  const start = css.indexOf(`${selector} {`);
  const block = css.slice(start, css.indexOf("}", start));
  return Object.fromEntries([...block.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6});/gi)].map((m) => [m[1], m[2]]));
}

const TEXT = ["ink", "ink-strong", "ink-muted", "accent", "danger", "warn", "info"];
const GROUNDS = ["bg", "bg-deep", "surface"];
const CHARTS = ["chart-1", "chart-2", "chart-3", "chart-4", "chart-5"];

/** Every pair the UI draws that misses WCAG AA: 4.5:1 for text, 3:1 for chart marks. */
function failures(t: Record<string, string>) {
  const pairs: [string, string, number][] = [
    ...TEXT.flatMap((fg) => GROUNDS.map((bg) => [fg, bg, 4.5] as [string, string, number])),
    ["accent-ink", "btn", 4.5], // text on the filled button
    ["bg", "accent", 4.5], // the unread badge
    ...CHARTS.map((c) => [c, "surface", 3] as [string, string, number]),
  ];
  return pairs
    .filter(([fg, bg, min]) => {
      const a = t[fg];
      const b = t[bg];
      return !a || !b || ratio(a, b) < min;
    })
    .map(([fg, bg]) => `${fg} on ${bg}${t[fg] && t[bg] ? ` = ${ratio(t[fg], t[bg]).toFixed(2)}` : " (missing)"}`);
}

describe("colour tokens", () => {
  it.each([":root", '[data-theme="light"]'])("%s passes contrast on every pair", (selector) => {
    const t = tokens(css, selector);
    expect(Object.keys(t).length).toBeGreaterThan(15);
    expect(failures(t)).toEqual([]);
  });

  it("catches a failing pair (control)", () => {
    expect(ratio("#ffffff", "#000000")).toBeCloseTo(21, 0);
    const t = { ...tokens(css, ":root"), "ink-muted": "#2a3a30" };
    expect(failures(t)).toContain(`ink-muted on surface = ${ratio("#2a3a30", t.surface!).toFixed(2)}`);
  });

  it("only uses token colours in source", () => {
    // Hex colours belong in styles.css alone; anything else would bypass the tokens.
    const offenders = Object.entries(import.meta.glob("../**/*.tsx", { query: "?raw", import: "default", eager: true }))
      .filter(([, src]) => /#[0-9a-f]{3,8}\b|rgba?\(/i.test(src as string))
      .map(([file]) => file);
    expect(offenders).toEqual([]);
  });
});
