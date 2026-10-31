import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import type { CallRow } from "../../lib/data";
import type { Message, Missed } from "../../lib/inbound";
import { useLiveCall } from "../../lib/live";
import { ErrorState, Skeleton } from "../../ui/states";
import { LiveView } from "../calls/LiveView";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");
const AUTO: Record<string, string> = { none: "", scheduled: "Call-back booked", calling: "Calling back now", answered: "Called back", not_answered: "Called back, no answer", cancelled: "Call-back cancelled" };

export default function Inbox() {
  return (
    <>
      <p className="eyebrow">Inbox</p>
      <h1 className="display mt-3 text-4xl">Incoming calls</h1>
      <p className="mt-2 text-ink-muted">Messages people left, call-backs they asked for, and calls nobody answered.</p>
      <AnsweringNow />
      <div className="mt-10 grid gap-10 xl:grid-cols-2">
        <Messages />
        <MissedCallers />
      </div>
    </>
  );
}

/** When an incoming call is on, it is shown live with the orb. */
function AnsweringNow() {
  const live = useQuery({
    queryKey: ["calls", "inbound-live"],
    queryFn: async () => {
      const page = await unwrap<{ items: CallRow[] }>(api.GET("/calls", { params: { query: { direction: "inbound", limit: 20, include_test: true } } }));
      return page.items.find((c) => c.status === "in_progress" || c.status === "ringing") ?? null;
    },
    refetchInterval: 5000,
  });
  const call = live.data;
  const state = useLiveCall(call?.id ?? null);
  if (!call) return null;
  return (
    <section aria-labelledby="answering" className="mt-10 rounded-card border border-line-accent bg-surface p-6">
      <h2 id="answering" className="eyebrow">Answering now · {call.name || call.phone || "a caller"}</h2>
      <div className="mt-6"><LiveView state={state} who={call.employee_name ?? "Employee"} /></div>
    </section>
  );
}

function Messages() {
  const qc = useQueryClient();
  const [view, setView] = useState<"open" | "done">("open");
  const key = ["inbound", "messages", view];
  const list = useQuery({ queryKey: key, queryFn: () => unwrap<{ total: number; items: Message[] }>(api.GET("/inbound/messages", { params: { query: { state: view } } })) });
  // Ticking is instant: the row leaves the list at once and comes back if the API refuses.
  const tick = useMutation({
    mutationFn: (m: Message) =>
      unwrap(m.done
        ? api.POST("/inbound/messages/{message_id}/reopen", { params: { path: { message_id: m.id } } })
        : api.POST("/inbound/messages/{message_id}/done", { params: { path: { message_id: m.id } } })),
    onMutate: async (m) => {
      await qc.cancelQueries({ queryKey: key });
      const before = qc.getQueryData<{ total: number; items: Message[] }>(key);
      if (before) qc.setQueryData(key, { total: before.total - 1, items: before.items.filter((x) => x.id !== m.id) });
      return { before };
    },
    onError: (_e, _m, ctx) => ctx?.before && qc.setQueryData(key, ctx.before),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["inbound", "messages"] }),
  });
  return (
    <section aria-labelledby="messages">
      <div className="flex items-end justify-between gap-3">
        <h2 id="messages" className="display text-2xl">Messages and call-backs</h2>
        <div role="radiogroup" aria-label="Which messages" className="flex gap-1 rounded-ctl border border-line p-1">
          {(["open", "done"] as const).map((v) => (
            <button key={v} type="button" role="radio" aria-checked={view === v} onClick={() => setView(v)}
              className="rounded-tag px-2.5 py-1 text-sm text-ink-muted aria-checked:bg-accent-soft aria-checked:text-ink-strong">{v === "open" ? "To do" : "Done"}</button>
          ))}
        </div>
      </div>
      {list.error ? <div className="mt-4"><ErrorState error={list.error} retry={() => void list.refetch()} /></div> : !list.data ? <Skeleton className="mt-4 h-40 rounded-card" /> : (
        <ul className="mt-4 space-y-2">
          {list.data.items.map((m) => (
            <li key={m.id} className="flex gap-3 rounded-card border border-line bg-surface p-4">
              <input type="checkbox" checked={m.done} onChange={() => tick.mutate(m)} aria-label={m.done ? `Reopen message from ${m.name || m.phone}` : `Mark message from ${m.name || m.phone} done`} className="mt-1 size-4 shrink-0 accent-[var(--accent)]" />
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap justify-between gap-2 text-sm">
                  <span className="text-ink-strong">{m.name || m.phone || "Caller"} {m.name && <span className="num text-ink-muted">{m.phone}</span>}</span>
                  <span className="text-ink-muted">{when(m.created_at)}</span>
                </p>
                <p className="mt-1 text-sm whitespace-pre-line text-ink">{m.body}</p>
                <p className="mt-1 text-xs text-ink-muted">
                  {m.callback_at && <span className="text-accent">Call back {when(m.callback_at)} · </span>}
                  {m.employee_name}{m.call_id && <> · <Link to={`/calls/${m.call_id}`} className="underline underline-offset-4">the call</Link></>}
                </p>
              </div>
            </li>
          ))}
          {list.data.items.length === 0 && <li className="rounded-card border border-dashed border-line p-8 text-center text-sm text-ink-muted">{view === "open" ? "Nothing to do." : "Nothing done yet."}</li>}
        </ul>
      )}
      {tick.error && <div className="mt-3"><ErrorState error={tick.error} /></div>}
    </section>
  );
}

function MissedCallers() {
  const list = useQuery({ queryKey: ["inbound", "missed"], queryFn: () => unwrap<{ total: number; items: Missed[] }>(api.GET("/inbound/missed")) });
  return (
    <section aria-labelledby="missed">
      <h2 id="missed" className="display text-2xl">Missed callers</h2>
      {list.error ? <div className="mt-4"><ErrorState error={list.error} retry={() => void list.refetch()} /></div> : !list.data ? <Skeleton className="mt-4 h-40 rounded-card" /> : (
        <ul className="mt-4 divide-y divide-line rounded-card border border-line">
          {list.data.items.map((m) => (
            <li key={m.call_id} className="p-4 text-sm">
              <p className="flex flex-wrap justify-between gap-2">
                <span className="text-ink-strong">{m.name || m.phone || "Unknown caller"}</span>
                <span className="text-ink-muted">{when(m.at)}</span>
              </p>
              <p className="mt-1 text-ink">{m.reason ?? "Not answered."}</p>
              <p className="mt-1 text-xs text-ink-muted">
                {AUTO[m.auto_callback.state] ?? m.auto_callback.state}
                {m.auto_callback.at && ` ${when(m.auto_callback.at)}`}
                {m.auto_callback.not_made_because && `No call-back: ${m.auto_callback.not_made_because}`}
              </p>
            </li>
          ))}
          {list.data.items.length === 0 && <li className="p-8 text-center text-sm text-ink-muted">No missed calls.</li>}
        </ul>
      )}
    </section>
  );
}
