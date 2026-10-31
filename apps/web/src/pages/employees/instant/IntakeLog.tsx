import { useState } from "react";

import { useIntakeLog } from "../../../lib/instant";
import { ErrorState, Skeleton } from "../../../ui/states";

const TONE: Record<string, string> = { accepted: "text-accent", deduplicated: "text-ink-muted", rejected: "text-warn" };

/** Every lead that arrived, and what happened to it. */
export function IntakeLog({ employeeId }: { employeeId: string }) {
  const [outcome, setOutcome] = useState("");
  const log = useIntakeLog(employeeId, outcome);
  return (
    <section aria-labelledby="intake-log">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="intake-log" className="eyebrow">Leads received</h2>
        <select aria-label="Show" value={outcome} onChange={(e) => setOutcome(e.target.value)} className="h-9 rounded-ctl border border-line bg-surface px-2 text-sm text-ink">
          <option value="">All</option>
          <option value="accepted">Accepted</option>
          <option value="deduplicated">Repeats skipped</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>
      {log.error ? (
        <ErrorState error={log.error} retry={() => void log.refetch()} />
      ) : !log.data ? (
        <Skeleton className="mt-3 h-32 rounded-card" />
      ) : (
        <ul className="mt-3 divide-y divide-line rounded-card border border-line">
          {log.data.map((e) => (
            <li key={e.id} className="grid grid-cols-[1fr_auto] gap-x-4 px-4 py-2.5 text-sm sm:grid-cols-[9rem_8rem_1fr_7rem]">
              <span className="text-ink-muted">{new Date(e.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })}</span>
              <span className="num text-ink">{e.phone ?? "–"}</span>
              <span className="text-ink-muted">{e.source}{e.reason ? ` · ${e.reason}` : ""}</span>
              <span className={`text-right ${TONE[e.status] ?? ""}`}>{e.status}</span>
            </li>
          ))}
          {log.data.length === 0 && <li className="p-6 text-center text-sm text-ink-muted">No leads yet. Send a test lead above.</li>}
        </ul>
      )}
    </section>
  );
}
