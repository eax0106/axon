import { describe, expect, it } from "vitest";

import { identifier, move, removeAt, replaceAt } from "./list";

describe("list edits", () => {
  it("moves an item one place and ignores moves past either end", () => {
    expect(move(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(move(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    const same = ["a", "b"];
    expect(move(same, 0, -1)).toBe(same);
    expect(move(same, 1, 1)).toBe(same);
  });
  it("replaces and removes by index without touching the input", () => {
    const xs = [1, 2, 3];
    expect(replaceAt(xs, 1, 9)).toEqual([1, 9, 3]);
    expect(removeAt(xs, 0)).toEqual([2, 3]);
    expect(xs).toEqual([1, 2, 3]);
  });
  it("turns a label into the API's identifier", () => {
    expect(identifier("Budget range")).toBe("budget_range");
    expect(identifier("  2nd Locality! ")).toBe("nd_locality");
    expect(identifier("ఊరు")).toBe("");
  });
});
