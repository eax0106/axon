import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { components } from "@axon/contracts";

import { api, unwrap } from "../../lib/api";
import { useAction } from "../../lib/useAction";
import { ErrorState, Skeleton } from "../../ui/states";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", second: "2-digit" }) : "");
const TONE: Record<string, string> = { delivered: "text-accent", failed: "text-danger", pending: "text-warn" };

/** Every webhook send, with its answer, and a resend. */
export function Deliveries() {
  const [status, setStatus] = useState<components["schemas"]["DeliveryStatus"] | "">("");
  const qc = useQueryClient();
  const page = useQuery({ queryKey: ["dev", "deliveries", status], queryFn: () => unwrap(api.GET("/developer/deliveries", { params: { query: { status: status || undefined, limit: 50 } } })) });
  const { error, run } = useAction();
  return (
    <section aria-labelledby="deliveries">
      <div className="flex items-end justify-between gap-3">
        <h2 id="deliveries" className="eyebrow">Deliveries</h2>
        <select aria-label="Delivery status" value={status} onChange={(e) => setStatus(e.target.value as typeof status)} className="h-9 rounded-ctl border border-line bg-surface px-2 text-sm text-ink">
          <option value="">All</option><option value="delivered">Delivered</option><option value="pending">Retrying</option><option value="failed">Failed</option>
        </select>
      </div>
      {page.error ? <ErrorState error={page.error} retry={() => void page.refetch()} /> : !page.data ? <Skeleton className="mt-3 h-32 rounded-card" /> : (
        <ul className="mt-3 divide-y divide-line rounded-card border border-line">
          {page.data.data.map((d) => (
            <li key={d.id} className="grid grid-cols-[1fr_auto] gap-x-4 px-4 py-2.5 text-sm sm:grid-cols-[10rem_10rem_1fr_6rem_4rem]">
              <span className="text-ink-muted">{when(d.created_at)}</span>
              <span className="num text-ink">{d.event}{d.is_test && <span className="text-ink-muted"> · test</span>}</span>
              <span className="truncate text-ink-muted">{d.response_code ? `HTTP ${d.response_code}` : d.last_error ?? ""} · try {d.attempts}</span>
              <span className={TONE[d.status] ?? ""}>{d.status}</span>
              <button type="button" className="text-right text-xs text-ink-muted hover:text-accent" onClick={() => void run(async () => { await unwrap(api.POST("/developer/deliveries/{delivery_id}/resend", { params: { path: { delivery_id: d.id } } })); await qc.invalidateQueries({ queryKey: ["dev", "deliveries"] }); })}>Resend</button>
            </li>
          ))}
          {page.data.data.length === 0 && <li className="p-6 text-center text-sm text-ink-muted">Nothing sent yet.</li>}
        </ul>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

/** Every request made with an API key in the last 30 days. */
export function Requests() {
  const [errorsOnly, setErrorsOnly] = useState(false);
  const log = useQuery({ queryKey: ["dev", "requests", errorsOnly], queryFn: () => unwrap(api.GET("/developer/requests", { params: { query: { limit: 100, min_status: errorsOnly ? 400 : undefined } } })) });
  return (
    <section aria-labelledby="requests">
      <div className="flex items-end justify-between gap-3">
        <h2 id="requests" className="eyebrow">API requests</h2>
        <label className="flex items-center gap-2 text-sm text-ink-muted"><input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} className="accent-[var(--accent)]" />Errors only</label>
      </div>
      {log.error ? <ErrorState error={log.error} retry={() => void log.refetch()} /> : !log.data ? <Skeleton className="mt-3 h-32 rounded-card" /> : (
        <ul className="mt-3 divide-y divide-line rounded-card border border-line">
          {log.data.map((r) => (
            <li key={r.id} className="grid grid-cols-[1fr_auto] gap-x-4 px-4 py-2 text-sm sm:grid-cols-[10rem_4rem_1fr_4rem_5rem]">
              <span className="text-ink-muted">{when(r.created_at)}</span>
              <span className="num text-ink">{r.method}</span>
              <span className="num truncate text-ink">{r.path}</span>
              <span className={`num ${r.status_code >= 400 ? "text-danger" : "text-accent"}`}>{r.status_code}</span>
              <span className="num text-right text-ink-muted">{r.duration_ms} ms</span>
            </li>
          ))}
          {log.data.length === 0 && <li className="p-6 text-center text-sm text-ink-muted">No requests yet.</li>}
        </ul>
      )}
    </section>
  );
}
