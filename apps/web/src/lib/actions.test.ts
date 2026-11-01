import { describe, expect, it } from "vitest";

import { type Action, blank, problems } from "./actions";

describe("in-call actions", () => {
  it("starts each kind with a unique callable name and the API's defaults", () => {
    const a = blank("http_api", ["check_system"]);
    expect(a.name).toBe("check_system_2");
    expect(a.kind === "http_api" && [a.method, a.timeout_s]).toEqual(["POST", 8]);
    expect(blank("calendar_booking", []).name).toBe("book_visit");
  });
  it("says what is missing before the API is asked", () => {
    const a = blank("http_api", []) as Extract<Action, { kind?: "http_api" }>;
    expect(problems(a)).toEqual(["Say when the employee should use it.", "The address must start with https:// and use the standard port."]);
    expect(problems({ ...a, description: "Check stock", url: "https://api.example.in/stock" })).toEqual([]);
    expect(problems({ ...a, name: "Bad Name", description: "x", url: "https://x.in:8443/a" })).toHaveLength(2);
  });
});
