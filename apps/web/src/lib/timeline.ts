/** Plain words for what happened during a call, from the events the engine and post-call steps keep. */
type Event = { type: string; data?: Record<string, unknown> | null };

const LEG: Record<string, string> = { stt: "speech-to-text", llm: "AI model", tts: "voice" };
const ENDED: Record<string, string> = {
  silence: "the caller went quiet",
  max_length: "it reached the length limit",
  caller_hung_up: "the caller hung up",
  agent_ended: "the employee ended it",
  transferred: "it was handed to a person",
  provider_failure: "a provider failed",
};

const vendor = (v: unknown) => (typeof v === "string" && v ? v[0]!.toUpperCase() + v.slice(1) : "another provider");
const leg = (l: unknown) => LEG[String(l)] ?? String(l ?? "a provider");

/** One line for a timeline entry, or null for bookkeeping the owner does not need to see. */
export function describe(e: Event): string | null {
  const d = e.data ?? {};
  switch (e.type) {
    case "usage":
    case "started":
      return null; // usage is billing detail; the start is already a milestone
    case "interruption":
      return "The caller spoke over the employee";
    case "recording_stored":
      return "Recording saved";
    case "recording_not_stored":
      return "Recording not saved";
    case "transferred":
      return "Handed over to a person";
    case "action":
      return `Used ${String(d.name ?? "an action")}${d.ok ? "" : " (it failed)"}`;
    case "failover":
      return `Switched ${leg(d.leg)} from ${vendor(d.from)} to ${vendor(d.to)} to stay on the call`;
    case "tier_fallback":
      return `A cheaper voice took over, so the call is billed at ${String(d.tier ?? "a lower")} rates`;
    case "provider_failure":
      return `No ${leg(d.leg)} provider was left, so the call ended with an apology`;
    case "ended":
      return `Ended because ${ENDED[String(d.reason)] ?? String(d.reason ?? "it finished").replaceAll("_", " ")}`;
    case "analysis_done":
      return "Summary and outcome ready";
    case "do_not_call":
      return "Caller asked not to be called again: added to do-not-call";
    case "callback_scheduled":
      return "Call-back scheduled";
    default:
      return e.type.replaceAll("_", " ");
  }
}
