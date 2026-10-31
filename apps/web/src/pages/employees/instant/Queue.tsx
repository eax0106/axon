import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../../lib/api";
import { type QueueItem, useQueue } from "../../../lib/instant";
import { useAction } from "../../../lib/useAction";
import { ErrorState, Skeleton } from "../../../ui/states";

const LANES: [string, string, (i: QueueItem) => boolean][] = [
  ["waiting", "Waiting", (i) => i.state === "waiting" || i.state === "held"],
  ["ringing", "Dialing", (i) => i.state === "ringing"],
  ["on_call", "On a call", (i) => i.state === "in_progress"],
];

/** New leads moving from waiting to dialing to on a call, refreshed every 5 s. */
export function Queue({ employeeId }: { employeeId: string }) {
  const queue = useQueue(employeeId);
  const qc = useQueryClient();
  const { error, run } = useAction();
  const act = (callId: string, what: "cancel" | "redial") =>
    run(async () => {
      const p = { params: { path: { employee_id: employeeId, call_id: callId } } };
      if (what === "cancel") await unwrap(api.POST("/employees/{employee_id}/instant/queue/{call_id}/cancel", p));
      else await unwrap(api.POST("/employees/{employee_id}/instant/queue/{call_id}/redial", p));
      await qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });

  if (queue.error) return <ErrorState error={queue.error} retry={() => void queue.refetch()} />;
  if (!queue.data) return <Skeleton className="h-48 rounded-card" />;
  return (
    <section aria-labelledby="queue">
      <h2 id="queue" className="eyebrow">Queue</h2>
      <div className="mt-3 grid gap-4 md:grid-cols-4">
        {LANES.map(([key, label, match]) => {
          const items = queue.data.active.filter(match);
          return (
            <Lane key={key} label={label} count={items.length}>
              {items.map((i) => (
                <Card key={i.call_id} item={i}>
                  {key === "waiting" && <button type="button" className="text-xs text-ink-muted hover:text-danger" onClick={() => void act(i.call_id, "cancel")}>Cancel</button>}
                  {key !== "waiting" && <Link to={`/calls/${i.call_id}/live`} className="text-xs text-accent">Listen in</Link>}
                </Card>
              ))}
            </Lane>
          );
        })}
        <Lane label="Done" count={queue.data.recent.length}>
          {queue.data.recent.map((i) => (
            <Card key={i.call_id} item={i}>
              <button type="button" className="text-xs text-ink-muted hover:text-accent" onClick={() => void act(i.call_id, "redial")}>Redial</button>
            </Card>
          ))}
        </Lane>
      </div>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

function Lane({ label, count, children }: { label: string; count: number; children: ReactNode }) {
  return (
    <section aria-label={label} className="min-w-0 rounded-card border border-line bg-surface p-3">
      <h3 className="eyebrow flex justify-between px-1">
        <span>{label}</span>
        <span className="num text-ink-muted">{count}</span>
      </h3>
      <ul className="mt-3 max-h-96 space-y-2 overflow-y-auto">{children}</ul>
      {count === 0 && <p className="px-1 py-4 text-center text-xs text-ink-muted">Empty</p>}
    </section>
  );
}

function Card({ item: i, children }: { item: QueueItem; children: ReactNode }) {
  return (
    <li className="page-in rounded-ctl border border-line bg-bg p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="min-w-0">
          <span className="block truncate text-sm text-ink-strong">{i.name || i.phone || "Lead"}</span>
          <span className="num block text-xs text-ink-muted">
            {i.phone} · try {i.attempt}
          </span>
        </span>
        {i.state === "waiting" && i.scheduled_for && <Countdown to={i.scheduled_for} />}
        {i.state === "held" && <span className="eyebrow text-warn">Held</span>}
        {i.state === "in_progress" && <span aria-hidden className="live-dot mt-1 size-2 rounded-full bg-accent" />}
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className="text-xs text-ink-muted">{i.state === "waiting" || i.state === "held" || i.state === "ringing" || i.state === "in_progress" ? "" : i.status.replaceAll("_", " ")}</span>
        {children}
      </div>
    </li>
  );
}

/** A ring that empties as dial time approaches (up to an hour out shows as a full ring). */
function Countdown({ to }: { to: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  const left = Math.max(0, Date.parse(to) - now);
  const frac = Math.min(1, left / 3_600_000);
  const label = left < 60_000 ? `${Math.ceil(left / 1000)}s` : left < 3_600_000 ? `${Math.ceil(left / 60_000)}m` : new Date(to).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return (
    <span className="flex items-center gap-1.5" title={`Dials at ${new Date(to).toLocaleString("en-IN")}`}>
      <svg viewBox="0 0 20 20" className="size-5 -rotate-90" aria-hidden>
        <circle cx="10" cy="10" r="8" fill="none" stroke="var(--line-accent)" strokeWidth="2" />
        <circle cx="10" cy="10" r="8" fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray={`${frac * 50.3} 50.3`} />
      </svg>
      <span className="num text-xs text-ink">{label}</span>
    </span>
  );
}
