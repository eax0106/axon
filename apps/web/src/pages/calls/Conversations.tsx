import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import { type Filters, OUTCOME, SENTIMENT, cleanFilters, download, duration, useCalls } from "../../lib/data";
import { CHANNELS, useEmployees } from "../../lib/employees";
import { credits } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";

const PAGE = 50;
const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export default function Conversations() {
  const [filters, setFilters] = useState<Filters | null>(null);
  const [limit, setLimit] = useState(PAGE);
  const loaded = useRef(false);

  // Filters are remembered per user on the server; read them once, save each change after a pause.
  useEffect(() => {
    void unwrap<Filters>(api.GET("/me/filters/conversations"))
      .then((f) => setFilters(cleanFilters(f ?? {})))
      .catch(() => setFilters({}));
  }, []);
  useEffect(() => {
    if (!filters) return;
    if (!loaded.current) {
      loaded.current = true;
      return;
    }
    const t = setTimeout(() => void api.PUT("/me/filters/conversations", { body: { include_test: false, ...filters } as never }), 600);
    return () => clearTimeout(t);
  }, [filters]);

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Conversations</p>
          <h1 className="display mt-3 text-4xl">Every call</h1>
        </div>
        {filters && <Export filters={filters} />}
      </div>
      {filters ? (
        <>
          <FilterBar filters={filters} onChange={(f) => { setFilters(f); setLimit(PAGE); }} />
          <List filters={filters} limit={limit} more={() => setLimit((l) => l + PAGE)} />
        </>
      ) : (
        <Skeleton className="mt-8 h-64 rounded-card" />
      )}
    </>
  );
}

function Export({ filters }: { filters: Filters }) {
  const { busy, error, run } = useAction();
  const query = new URLSearchParams(Object.entries(cleanFilters(filters)).map(([k, v]) => [k, String(v)])).toString();
  return (
    <div className="text-right">
      <button type="button" className={btn.ghost} disabled={busy} onClick={() => void run(() => download(`/calls/export.csv?${query}`, "calls.csv"))}>
        {busy ? "Exporting…" : "Export CSV"}
      </button>
      {error !== null && <p className="mt-1 text-xs text-danger">{(error as Error).message}</p>}
    </div>
  );
}

function FilterBar({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const employees = useEmployees().data ?? [];
  const set = (patch: Filters) => onChange(cleanFilters({ ...filters, ...patch }));
  const select = (label: string, key: keyof Filters, options: [string, string][]) => (
    <label className="block min-w-0">
      <span className="text-xs text-ink-muted">{label}</span>
      <select value={String(filters[key] ?? "")} onChange={(e) => set({ [key]: e.target.value })}
        className="mt-1 h-9 w-full rounded-ctl border border-line bg-surface px-2 text-sm text-ink outline-none focus:border-accent">
        <option value="">Any</option>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
  const number = (label: string, key: keyof Filters) => (
    <label className="block min-w-0">
      <span className="text-xs text-ink-muted">{label}</span>
      <input type="number" min={0} value={String(filters[key] ?? "")} onChange={(e) => set({ [key]: e.target.value === "" ? undefined : Number(e.target.value) })}
        className="num mt-1 h-9 w-full rounded-ctl border border-line bg-surface px-2 text-sm text-ink outline-none focus:border-accent" />
    </label>
  );
  const active = Object.keys(filters).length;
  return (
    <section aria-label="Filters" className="mt-8 rounded-card border border-line bg-surface p-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <label className="col-span-2 block">
          <span className="text-xs text-ink-muted">Search</span>
          <input type="search" placeholder="Name, phone or words in the summary" value={filters.q ?? ""} onChange={(e) => set({ q: e.target.value })}
            className="mt-1 h-9 w-full rounded-ctl border border-line bg-bg px-3 text-sm text-ink-strong outline-none focus:border-accent" />
        </label>
        {select("Outcome", "outcome", Object.entries(OUTCOME).filter(([k]) => k !== "no_outcome"))}
        {select("Sentiment", "sentiment", Object.entries(SENTIMENT))}
        {select("Employee", "employee_id", employees.map((e) => [e.id, e.name]))}
        {select("Channel", "channel", Object.entries(CHANNELS).map(([k, v]) => [k, v.label]))}
        {select("Direction", "direction", [["outbound", "Outgoing"], ["inbound", "Incoming"]])}
        <label className="block min-w-0">
          <span className="text-xs text-ink-muted">From</span>
          <input type="date" value={filters.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value })} className="mt-1 h-9 w-full rounded-ctl border border-line bg-surface px-2 text-sm text-ink" />
        </label>
        <label className="block min-w-0">
          <span className="text-xs text-ink-muted">To</span>
          <input type="date" value={filters.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value })} className="mt-1 h-9 w-full rounded-ctl border border-line bg-surface px-2 text-sm text-ink" />
        </label>
        {number("Min seconds", "min_duration")}
        {number("Max seconds", "max_duration")}
        {number("Min credits", "min_credits")}
        {number("Max credits", "max_credits")}
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm">
        <label className="flex items-center gap-2 text-ink-muted">
          <input type="checkbox" checked={Boolean(filters.include_test)} onChange={(e) => set({ include_test: e.target.checked })} className="accent-[var(--accent)]" />
          Include test calls
        </label>
        {active > 0 && <button type="button" className={btn.quiet} onClick={() => onChange({})}>Clear {active} filter{active === 1 ? "" : "s"}</button>}
      </div>
    </section>
  );
}

function List({ filters, limit, more }: { filters: Filters; limit: number; more: () => void }) {
  const calls = useCalls(filters, limit);
  if (calls.error) return <div className="mt-6"><ErrorState error={calls.error} retry={() => void calls.refetch()} /></div>;
  const items = calls.data?.items ?? [];
  return (
    <section aria-label="Calls" className={`mt-6 transition-opacity duration-150 ${calls.isPlaceholderData ? "opacity-60" : ""}`}>
      <p className="text-sm text-ink-muted" aria-live="polite">{calls.data ? `${calls.data.total} call${calls.data.total === 1 ? "" : "s"}` : " "}</p>
      <div aria-hidden className="mt-2 hidden grid-cols-[10rem_1fr_9rem_5rem_5rem] gap-x-4 px-4 py-2 text-xs text-ink-muted md:grid">
        <span>When</span>
        <span>Who and what</span>
        <span>Outcome</span>
        <span className="text-right">Talk</span>
        <span className="text-right">Credits</span>
      </div>
      <ul className="divide-y divide-line rounded-card border border-line">
        {items.map((c) => (
          <li key={c.id}>
            <Link to={`/calls/${c.id}`} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-4 py-3 transition-colors duration-150 hover:bg-accent-soft md:grid-cols-[10rem_1fr_9rem_5rem_5rem]">
              <span className="text-sm text-ink-muted">{when(c.created_at)}</span>
              <span className="min-w-0 md:order-none">
                <span className="block truncate text-ink-strong">{c.name || c.phone || "Unknown caller"}{c.is_test && <span className="eyebrow ml-2 text-ink-muted">Test</span>}</span>
                <span className="block truncate text-sm text-ink-muted">{c.summary || c.miss_reason || `${c.employee_name ?? "Employee"} · ${c.status.replaceAll("_", " ")}`}</span>
              </span>
              <span className="text-sm text-ink">{c.outcome ? OUTCOME[c.outcome] ?? c.outcome : "–"}</span>
              <span className="num text-right text-sm text-ink-muted">{duration(c.duration_s)}</span>
              <span className="num text-right text-sm text-ink-muted">{credits(String(c.credits_charged))}</span>
            </Link>
          </li>
        ))}
        {calls.data && items.length === 0 && <li className="p-10 text-center text-sm text-ink-muted">No calls match. Clear a filter or two.</li>}
        {!calls.data && <li className="p-4"><Skeleton /></li>}
      </ul>
      {calls.data && items.length < calls.data.total && (
        <button type="button" className={`${btn.quiet} mt-3`} onClick={more}>Show {Math.min(PAGE, calls.data.total - items.length)} more</button>
      )}
    </section>
  );
}
