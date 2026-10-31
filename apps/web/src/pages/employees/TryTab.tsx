import { type FormEvent, useRef, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import { useLiveCall } from "../../lib/live";
import { useMe } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { startWebCall } from "../../lib/webcall";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";
import { LiveView } from "../calls/LiveView";
import { useDetail } from "./Detail";

type Mode = "chat" | "browser" | "phone";
const MODES: [Mode, string, string][] = [
  ["chat", "Chat", "Type as a caller would. Nothing is stored or billed."],
  ["browser", "Talk in the browser", "Speak with your microphone. Free."],
  ["phone", "Ring my phone", "A real call to your verified phone. Free."],
];

/** Every way to hear the draft script before a customer does. */
export default function TryTab() {
  const [mode, setMode] = useState<Mode>("chat");
  return (
    <div>
      <div role="tablist" aria-label="How to try it" className="grid gap-2 sm:grid-cols-3">
        {MODES.map(([m, label, hint]) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => setMode(m)}
            className="rounded-card border border-line bg-surface p-4 text-left transition-colors duration-150 hover:border-line-accent aria-selected:border-accent aria-selected:bg-accent-soft"
          >
            <span className="block font-medium text-ink-strong">{label}</span>
            <span className="mt-1 block text-sm text-ink-muted">{hint}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-8">
        {mode === "chat" ? <Chat /> : mode === "browser" ? <BrowserCall /> : <PhoneCall />}
      </div>
    </div>
  );
}

type Message = { role: "user" | "assistant"; content: string };

function Chat() {
  const { employee } = useDetail();
  const [messages, setMessages] = useState<Message[]>([]);
  const { busy, error, run } = useAction();

  function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const box = e.currentTarget.elements.namedItem("say") as HTMLInputElement;
    const said = box.value.trim();
    if (!said) return;
    const next: Message[] = [...messages, { role: "user", content: said }];
    setMessages(next);
    box.value = "";
    void run(async () => {
      const { reply } = await unwrap(
        api.POST("/employees/{employee_id}/chat", {
          params: { path: { employee_id: employee.id } },
          body: { messages: next, source: "draft" },
        }),
      );
      setMessages([...next, { role: "assistant", content: reply }]);
    });
  }

  return (
    <div className="mx-auto max-w-2xl">
      <ol className="min-h-48 space-y-3 rounded-card border border-line bg-surface p-5" aria-live="polite">
        {messages.map((m, i) => (
          <li key={i} className={`flex ${m.role === "user" ? "justify-end" : ""}`}>
            <p className={`max-w-[80%] rounded-card px-4 py-2.5 text-sm ${m.role === "user" ? "bg-accent-soft text-ink-strong" : "border border-line text-ink"}`}>
              {m.content}
            </p>
          </li>
        ))}
        {messages.length === 0 && <li className="py-12 text-center text-sm text-ink-muted">Say hello the way a customer would.</li>}
        {busy && <li className="text-sm text-ink-muted">{employee.name} is typing…</li>}
      </ol>
      {error !== null && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
      <form onSubmit={send} className="mt-3 flex gap-2">
        <label className="sr-only" htmlFor="say">
          Your message
        </label>
        <input id="say" name="say" maxLength={2000} autoComplete="off" className="h-11 min-w-0 flex-1 rounded-ctl border border-line-accent bg-surface px-3.5 text-ink-strong outline-none focus:border-accent" />
        <button type="submit" className={`${btn.primary} h-11`} disabled={busy}>
          Send
        </button>
        <button type="button" className={`${btn.quiet} h-11`} onClick={() => setMessages([])} disabled={busy || !messages.length}>
          Clear
        </button>
      </form>
    </div>
  );
}

function BrowserCall() {
  const { employee } = useDetail();
  const [callId, setCallId] = useState<string | null>(null);
  const [ended, setEnded] = useState<string | null>(null);
  const call = useRef<Awaited<ReturnType<typeof startWebCall>> | null>(null);
  const level = useRef(() => call.current?.level() ?? 0).current;
  const state = useLiveCall(callId);
  const { busy, error, run } = useAction();

  const start = () =>
    run(async () => {
      setEnded(null);
      const ticket = await unwrap<{ call_id: string; ws_url: string }>(
        api.POST("/employees/{employee_id}/web-test-call", { params: { path: { employee_id: employee.id } } }),
      );
      call.current = await startWebCall(ticket.ws_url, (reason) => {
        call.current = null;
        setEnded(reason);
      });
      setCallId(ticket.call_id);
    });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {call.current ? (
          <button type="button" className={btn.danger} onClick={() => call.current?.stop()}>
            End call
          </button>
        ) : (
          <button type="button" className={btn.primary} onClick={() => void start()} disabled={busy}>
            {busy ? "Connecting…" : callId ? "Call again" : "Start a browser call"}
          </button>
        )}
        <span className="text-sm text-ink-muted">Uses the draft script. Allow the microphone when asked.</span>
      </div>
      {ended && ended !== "ended" && <p className="text-sm text-warn">The call closed: {ended}</p>}
      {error !== null && <ErrorState error={error instanceof DOMException ? new Error("Allow the microphone to talk in the browser.") : error} />}
      {callId && <LiveView state={state} level={level} who={employee.name} />}
    </div>
  );
}

function PhoneCall() {
  const { employee } = useDetail();
  const phone = useMe().data?.account.owner_phone;
  const [callId, setCallId] = useState<string | null>(null);
  const state = useLiveCall(callId);
  const { busy, error, run } = useAction();

  if (phone === "")
    return (
      <p className="text-sm text-ink-muted">
        Test calls ring only your own phone, proved by a code.{" "}
        <Link to="/account" className="text-accent underline underline-offset-4">
          Verify your phone
        </Link>{" "}
        first.
      </p>
    );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className={btn.primary}
          disabled={busy || !phone}
          onClick={() =>
            void run(async () => {
              const placed = await unwrap<{ call_id: string }>(
                api.POST("/employees/{employee_id}/test-call", { params: { path: { employee_id: employee.id } }, body: null }),
              );
              setCallId(placed.call_id);
            })
          }
        >
          {busy ? "Calling…" : `Ring ${phone ?? "my phone"}`}
        </button>
        <span className="text-sm text-ink-muted">From the employee's own number, on the draft script.</span>
      </div>
      {error !== null && <ErrorState error={error} />}
      {callId && <LiveView state={state} who={employee.name} />}
    </div>
  );
}
