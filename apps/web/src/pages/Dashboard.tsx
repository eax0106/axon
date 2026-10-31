import { useState } from "react";
import { Link } from "react-router";

import { type Overview, percent, useOverview } from "../lib/data";
import { CHANNELS, type Channel } from "../lib/employees";
import { Bars } from "../ui/Bars";
import { ErrorState, Skeleton } from "../ui/states";

const RANGES = [
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["custom", "Custom"],
] as const;
const SPLIT_COLOUR: Record<string, string> = { instant: "bg-[var(--chart-1)]", bulk: "bg-[var(--chart-4)]", inbound: "bg-[var(--chart-5)]" };
const hour = (h: number) => `${h % 12 || 12}${h < 12 ? "am" : "pm"}`;

/** How the AI team is doing: the numbers an owner checks every morning. */
export function Dashboard() {
  const [range, setRange] = useState<(typeof RANGES)[number][0]>("7d");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const stats = useOverview(range, from, to);
  const s = stats.data;

  return (
    <section aria-labelledby="perf" className="mt-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 id="perf" className="display text-2xl">Performance</h2>
        <div className="flex flex-wrap items-center gap-2">
          <div role="radiogroup" aria-label="Range" className="flex gap-1 rounded-ctl border border-line p-1">
            {RANGES.map(([r, label]) => (
              <button key={r} type="button" role="radio" aria-checked={range === r} onClick={() => setRange(r)}
                className="rounded-tag px-2.5 py-1 text-sm text-ink-muted aria-checked:bg-accent-soft aria-checked:text-ink-strong">
                {label}
              </button>
            ))}
          </div>
          {range === "custom" && (
            <>
              <input type="date" aria-label="From" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 rounded-ctl border border-line bg-surface px-2 text-sm text-ink" />
              <input type="date" aria-label="To" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 rounded-ctl border border-line bg-surface px-2 text-sm text-ink" />
            </>
          )}
        </div>
      </div>

      {stats.error ? (
        <div className="mt-6"><ErrorState error={stats.error} retry={() => void stats.refetch()} /></div>
      ) : !s ? (
        range === "custom" && !(from && to) ? <p className="mt-6 text-sm text-ink-muted">Pick both dates.</p> : <Skeleton className="mt-6 h-64 rounded-card" />
      ) : s.totals.calls === 0 ? (
        <p className="mt-6 rounded-card border border-dashed border-line p-8 text-center text-ink-muted">
          No calls in this range yet. Results appear here as your employees talk to people.
        </p>
      ) : (
        <Body s={s} />
      )}
    </section>
  );
}

function Body({ s }: { s: Overview }) {
  const split = Object.entries(s.channel_split);
  const all = split.reduce((a, [, n]) => a + n, 0) || 1;
  return (
    <div className={`mt-6 space-y-6 transition-opacity duration-200`}>
      <dl className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Calls" value={String(s.totals.calls)} sub={`${s.totals.connected} connected`} />
        <Stat label="Connect rate" value={percent(s.rates.connect)} sub={`of ${s.totals.placed} placed`} />
        <Stat label="Qualified" value={percent(s.rates.qualify)} sub={`${s.totals.qualified} leads`} />
        <Stat label="Converted" value={percent(s.rates.conversion)} sub={`${s.totals.converted} leads`} accent />
      </dl>

      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-card border border-line bg-surface p-6">
          <div className="flex items-baseline justify-between gap-3">
            <p className="eyebrow">Calls by hour</p>
            {s.best_hour !== null && <p className="text-sm text-ink-muted">Best hour <span className="text-accent">{hour(s.best_hour)}</span></p>}
          </div>
          <div className="mt-4">
            <Bars
              data={Array.from({ length: 24 }, (_, h) => {
                const row = s.by_hour.find((b) => b.hour === h);
                return { label: hour(h), total: row?.placed ?? 0, part: row?.connected ?? 0 };
              })}
              highlight={s.best_hour === null ? undefined : hour(s.best_hour)}
              caption="Calls placed and connected by hour of day (IST)"
              totalName="Placed"
              partName="Connected"
            />
          </div>
        </div>
        <div className="space-y-6">
          <div className="rounded-card border border-line bg-surface p-6">
            <p className="eyebrow">Channel split</p>
            <div className="mt-4 flex h-2 overflow-hidden rounded-full bg-line">
              {split.map(([c, n]) => <span key={c} className={SPLIT_COLOUR[c] ?? "bg-[var(--chart-3)]"} style={{ width: `${(n / all) * 100}%` }} />)}
            </div>
            <ul className="mt-3 space-y-1 text-sm">
              {split.map(([c, n]) => (
                <li key={c} className="flex justify-between">
                  <span className="flex items-center gap-2 text-ink-muted">
                    <span aria-hidden className={`size-2 rounded-full ${SPLIT_COLOUR[c] ?? "bg-[var(--chart-3)]"}`} />
                    {CHANNELS[c as Channel]?.label ?? c}
                  </span>
                  <span className="num text-ink">{n}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-card border border-line bg-surface p-6">
            <p className="eyebrow">New leads called within 60 s</p>
            <p className="display num mt-3 text-4xl">{percent(s.speed.rate)}</p>
            <p className="text-sm text-ink-muted">{s.speed.within_60s} of {s.speed.accepted} Instant leads</p>
          </div>
        </div>
      </div>

      {s.leaderboard.length > 0 && (
        <div className="rounded-card border border-line bg-surface p-6">
          <p className="eyebrow">Leaderboard</p>
          <ol className="mt-3 divide-y divide-line">
            {s.leaderboard.map((e, i) => (
              <li key={e.employee_id} className="grid grid-cols-[2rem_1fr_auto] items-center gap-3 py-3 text-sm">
                <span className="num text-accent">{String(i + 1).padStart(2, "0")}</span>
                <Link to={`/employees/${e.employee_id}`} className="truncate text-ink-strong hover:text-accent">{e.name}</Link>
                <span className="num text-ink-muted">
                  {/* Inbound employees place no calls; their connected calls are answered ones. */}
                  {e.placed ? `${e.connected}/${e.placed} connected` : `${e.connected} answered`} · {e.converted} converted
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, sub, accent }: { label: string; value: string; sub: string; accent?: boolean }) {
  return (
    <div className="bg-surface p-5">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className={`display num mt-2 text-3xl ${accent ? "text-accent" : ""}`}>{value}</dd>
      <dd className="mt-1 text-xs text-ink-muted">{sub}</dd>
    </div>
  );
}
