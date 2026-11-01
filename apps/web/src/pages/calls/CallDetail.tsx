import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "../../lib/api";
import { OUTCOME, SENTIMENT, duration, useCall } from "../../lib/data";
import { credits } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Notes } from "./Notes";
import { Rate } from "./Rate";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", second: "2-digit" }) : "");
const LIVE = new Set(["queued", "ringing", "in_progress"]);

export default function CallDetail() {
  const { id = "" } = useParams();
  const call = useCall(id);
  const c = call.data;
  if (call.error) return <ErrorState error={call.error} retry={() => void call.refetch()} />;
  if (!c) return <Skeleton className="h-96 rounded-card" />;
  const path = { params: { path: { call_id: c.id } } };

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
      <div className="min-w-0 space-y-8">
        <header>
          <p className="eyebrow">{c.direction === "inbound" ? "Incoming call" : "Outgoing call"} · {when(c.created_at)}</p>
          <h1 className="display mt-3 text-3xl">{c.name || c.phone || "Unknown caller"}</h1>
          <p className="mt-1 text-sm text-ink-muted">
            {c.phone} · {c.employee_name ?? "Removed employee"} · {c.status.replaceAll("_", " ")}
            {c.is_test && " · test call"}
          </p>
          {LIVE.has(c.status) && <Link to={`/calls/${c.id}/live`} className={`${btn.primary} mt-4`}>Listen in live</Link>}
        </header>

        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-4">
          {[
            ["Outcome", c.outcome ? OUTCOME[c.outcome] ?? c.outcome : "–"],
            ["Sentiment", c.sentiment ? SENTIMENT[c.sentiment] ?? c.sentiment : "–"],
            ["Talk time", duration(c.duration_s)],
            ["Credits", credits(String(c.credits_charged))],
          ].map(([k, v]) => (
            <div key={k} className="bg-surface p-4">
              <dt className="text-xs text-ink-muted">{k}</dt>
              <dd className="num mt-1 text-lg text-ink-strong">{v}</dd>
            </div>
          ))}
        </dl>

        <section aria-labelledby="summary">
          <h2 id="summary" className="eyebrow">Summary</h2>
          <p className="mt-2 text-ink">{c.summary ?? (c.analysis_status === "failed" ? `The analysis failed${c.analysis_error ? `: ${c.analysis_error}` : ""}.` : c.analysis_status === "pending" ? "Being written…" : "No summary for this call.")}</p>
        </section>

        {Object.keys(c.captured).length > 0 && (
          <section aria-labelledby="captured">
            <h2 id="captured" className="eyebrow">Captured</h2>
            <dl className="mt-2 divide-y divide-line border-y border-line">
              {Object.entries(c.captured).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 py-2.5 text-sm">
                  <dt className="num text-ink-muted">{k}</dt>
                  <dd className="text-right text-ink">{v === null ? "–" : String(v)}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        <Recording id={c.id} has={c.has_recording} />

        <section aria-labelledby="transcript">
          <h2 id="transcript" className="eyebrow">Transcript</h2>
          <ol className="mt-3 space-y-3">
            {c.transcript.map((t, i) => (
              <li key={i} className={`flex ${t.role === "user" ? "justify-end" : ""}`}>
                <p className={`max-w-[85%] rounded-card px-4 py-2.5 text-sm ${t.role === "user" ? "bg-accent-soft text-ink-strong" : "border border-line text-ink"}`}>
                  <span className="eyebrow mb-1 block text-[10px] text-ink-muted">{t.role === "user" ? "Caller" : c.employee_name ?? "Employee"}</span>
                  {t.text}
                </p>
              </li>
            ))}
            {c.transcript.length === 0 && <li className="text-sm text-ink-muted">Nothing was said on this call.</li>}
          </ol>
        </section>
      </div>

      <aside className="space-y-8">
        <Actions callId={c.id} />
        <Notes notes={c.notes} refresh={["calls", c.id]} add={(body) => unwrap(api.POST("/calls/{call_id}/notes", { ...path, body: { body } }))} />
        {!LIVE.has(c.status) && <Rate callId={c.id} />}
        <section aria-labelledby="timeline">
          <h2 id="timeline" className="eyebrow">Timeline</h2>
          <ol className="mt-3 space-y-2 border-l border-line pl-4 text-sm">
            {[
              // The call's own milestones, then what happened during it (words are in the transcript).
              ...([["Started", c.started_at], ["Answered", c.answered_at], ["Ended", c.ended_at]] as const)
                .filter(([, at]) => at)
                .map(([type, at]) => ({ type, at })),
              ...c.timeline.filter((t) => t.type !== "caller_said" && t.type !== "agent_said"),
            ].sort((x, y) => String(x.at).localeCompare(String(y.at))).map((t, i) => (
              <li key={i}>
                <span className="text-ink">{t.type.replaceAll("_", " ")}</span>
                <span className="ml-2 text-xs text-ink-muted">{when(t.at)}</span>
              </li>
            ))}
          </ol>
        </section>
      </aside>
    </div>
  );
}

function Recording({ id, has }: { id: string; has: boolean }) {
  const [url, setUrl] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  if (!has) return null;
  return (
    <section aria-labelledby="recording">
      <h2 id="recording" className="eyebrow">Recording</h2>
      {url ? (
        <audio controls src={url} className="mt-3 w-full" />
      ) : (
        <button type="button" className={`${btn.ghost} mt-3`} disabled={busy}
          onClick={() => void run(async () => setUrl((await unwrap<{ url: string }>(api.GET("/calls/{call_id}/recording", { params: { path: { call_id: id } } }))).url))}>
          {busy ? "Loading…" : "Play recording"}
        </button>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

function Actions({ callId }: { callId: string }) {
  const qc = useQueryClient();
  const [copied, setCopied] = useState(false);
  const { busy, error, run } = useAction();
  const path = { params: { path: { call_id: callId } } };
  return (
    <section aria-label="Actions" className="flex flex-wrap gap-2">
      <button type="button" className={btn.ghost} disabled={busy}
        onClick={() => void run(async () => {
          const text = await unwrap<string>(api.GET("/calls/{call_id}/share-text", { ...path, parseAs: "text" }));
          await navigator.clipboard.writeText(text);
          setCopied(true);
        })}>
        {copied ? "Copied" : "Copy summary to share"}
      </button>
      <button type="button" className={btn.quiet} disabled={busy}
        onClick={() => void run(async () => { await unwrap(api.POST("/calls/{call_id}/reanalyze", path)); await qc.invalidateQueries({ queryKey: ["calls", callId] }); })}>
        Re-analyse
      </button>
      {error !== null && <div className="w-full"><ErrorState error={error} /></div>}
    </section>
  );
}
