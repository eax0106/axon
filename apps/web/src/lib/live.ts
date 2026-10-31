import { useEffect, useReducer } from "react";

import { api, session, unwrap } from "./api";

/** The stages of a call as the owner sees them, in order. */
export const STAGES = ["ringing", "listening", "thinking", "speaking", "done"] as const;
export type Stage = (typeof STAGES)[number];
export type Turn = { who: "caller" | "employee"; text: string };
export type LiveState = {
  stage: Stage;
  turns: Turn[];
  notes: string[]; // tools used, vendor switches: shown quietly under the transcript
  endedReason: string | null;
  connection: "connecting" | "open" | "closed" | "refused";
};

export const initial: LiveState = { stage: "ringing", turns: [], notes: [], endedReason: null, connection: "connecting" };

/** Engine events (services/engine/engine/events.py and call.py) folded into what the view shows. */
export function reduce(state: LiveState, event: Record<string, unknown>): LiveState {
  const text = typeof event.text === "string" ? event.text : "";
  switch (event.type) {
    case "started":
    case "user_started_speaking":
    case "bot_stopped_speaking":
    case "interruption":
      return { ...state, stage: "listening" };
    case "user_stopped_speaking":
      return { ...state, stage: "thinking" };
    case "bot_started_speaking":
      return { ...state, stage: "speaking" };
    case "user_transcript":
      return text ? { ...state, turns: [...state.turns, { who: "caller", text }] } : state;
    case "bot_text": {
      if (!text) return state;
      // The voice streams its words; consecutive pieces belong to one turn.
      const last = state.turns.at(-1);
      if (last?.who === "employee")
        return { ...state, turns: [...state.turns.slice(0, -1), { who: "employee", text: join(last.text, text) }] };
      return { ...state, turns: [...state.turns, { who: "employee", text }] };
    }
    case "action":
      return { ...state, notes: [...state.notes, `Used ${String(event.name)}${event.ok ? "" : " (it failed)"}`] };
    case "failover":
      return { ...state, notes: [...state.notes, `Switched ${String(event.leg)} provider to stay on the call`] };
    case "transferred":
      return { ...state, notes: [...state.notes, "Handed over to a person"] };
    case "ended":
      return { ...state, stage: "done", endedReason: String(event.reason ?? "ended") };
    default:
      return state;
  }
}

// Streamed pieces arrive with or without their leading space; never glue two words together.
const join = (a: string, b: string) => (/\s$/.test(a) || /^[\s,.!?।]/.test(b) ? a + b : `${a} ${b}`);

type Action =
  | { event: Record<string, unknown> }
  | { connection: LiveState["connection"] }
  | { finished: { status: string; transcript: { role: string; text: string }[] } };

const LIVE_STATUSES = new Set(["queued", "ringing", "in_progress"]);

function apply(s: LiveState, a: Action): LiveState {
  if ("event" in a) return reduce(s, a.event);
  if ("connection" in a) return { ...s, connection: a.connection };
  // Opened after the call ended: show what was said, from the stored record.
  const turns: Turn[] = a.finished.transcript.map((t) => ({ who: t.role === "user" ? "caller" : "employee", text: t.text }));
  return { ...s, stage: "done", endedReason: a.finished.status, turns: s.turns.length ? s.turns : turns };
}

/** Follow a call's live events over the API's WebSocket until it ends. */
export function useLiveCall(callId: string | null): LiveState {
  const [state, dispatch] = useReducer(apply, initial);
  useEffect(() => {
    if (!callId) return;
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const token = encodeURIComponent(session.token() ?? "");
    const ws = new WebSocket(`${scheme}://${location.host}/api/calls/${callId}/live?token=${token}`);
    ws.onopen = () => {
      dispatch({ connection: "open" });
      // A call that is already over sends no more events; its record says how it went.
      void unwrap<{ status: string; transcript: { role: string; text: string }[] }>(
        api.GET("/calls/{call_id}", { params: { path: { call_id: callId } } }),
      )
        .then((call) => {
          if (!LIVE_STATUSES.has(call.status)) dispatch({ finished: call });
        })
        .catch(() => undefined); // the socket's own refusal already says why
    };
    ws.onmessage = (m) => {
      try {
        dispatch({ event: JSON.parse(String(m.data)) as Record<string, unknown> });
      } catch {
        /* not an event */
      }
    };
    // 4401/4404: the API refused the token or the call.
    ws.onclose = (e) => dispatch({ connection: e.code >= 4400 ? "refused" : "closed" });
    return () => ws.close();
  }, [callId]);
  return state;
}
