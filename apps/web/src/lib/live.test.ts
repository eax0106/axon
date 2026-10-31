import { describe, expect, it } from "vitest";

import { initial, reduce } from "./live";

const run = (...events: Record<string, unknown>[]) => events.reduce(reduce, initial);

describe("live call events", () => {
  it("moves through the stages the engine reports", () => {
    expect(run({ type: "started" }).stage).toBe("listening");
    expect(run({ type: "started" }, { type: "user_stopped_speaking" }).stage).toBe("thinking");
    expect(run({ type: "bot_started_speaking" }).stage).toBe("speaking");
    expect(run({ type: "bot_started_speaking" }, { type: "interruption" }).stage).toBe("listening");
    const ended = run({ type: "ended", reason: "caller_hung_up" });
    expect([ended.stage, ended.endedReason]).toEqual(["done", "caller_hung_up"]);
  });

  it("joins streamed employee words into one turn, keeping Telugu intact", () => {
    const s = run(
      { type: "user_transcript", text: "నమస్తే" },
      { type: "bot_text", text: "నమస్కారం," },
      { type: "bot_text", text: "ప్రియ" },
      { type: "bot_text", text: " మాట్లాడుతున్నాను।" },
      { type: "user_transcript", text: "budget 80 lakhs" },
    );
    expect(s.turns).toEqual([
      { who: "caller", text: "నమస్తే" },
      { who: "employee", text: "నమస్కారం, ప్రియ మాట్లాడుతున్నాను।" },
      { who: "caller", text: "budget 80 lakhs" },
    ]);
  });

  it("notes tools and provider switches, ignores events it does not know", () => {
    const s = run({ type: "action", name: "book_visit", ok: false }, { type: "failover", leg: "tts" }, { type: "usage" });
    expect(s.notes).toEqual(["Used book_visit (it failed)", "Switched tts provider to stay on the call"]);
  });
});
