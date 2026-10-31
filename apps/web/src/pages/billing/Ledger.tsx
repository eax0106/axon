import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Entry, KIND, useInvoices, useStatement, useTransactions, useUsage } from "../../lib/billing";
import { credits } from "../../lib/format";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";

const date = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });
const signed = (v: string) => (Number(v) > 0 ? `+${credits(v)}` : credits(v));

/** Statement, per-employee usage, every ledger entry with its running balance, and invoices. */
export function Ledger() {
  const [month, setMonth] = useState<"this" | "last">("this");
  return (
    <div className="mt-12 space-y-12">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="display text-2xl">Statement</h2>
        <div role="radiogroup" aria-label="Month" className="flex gap-1 rounded-ctl border border-line p-1">
          {(["this", "last"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={month === m}
              onClick={() => setMonth(m)}
              className="rounded-tag px-3 py-1 text-sm text-ink-muted aria-checked:bg-accent-soft aria-checked:text-ink-strong"
            >
              {m === "this" ? "This month" : "Last month"}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <StatementCard month={month} />
        <UsageCard month={month} />
      </div>
      <Transactions />
      <Invoices />
    </div>
  );
}

function StatementCard({ month }: { month: "this" | "last" }) {
  const s = useStatement(month);
  if (s.error) return <ErrorState error={s.error} retry={() => void s.refetch()} />;
  if (!s.data) return <Skeleton className="h-56 rounded-card" />;
  return (
    <section aria-label={`Statement for ${s.data.month}`} className="rounded-card border border-line bg-surface p-6">
      <dl className="divide-y divide-line">
        <Row label="Opening balance" value={credits(s.data.opening_balance)} />
        {Object.entries(s.data.by_kind).map(([kind, v]) => (
          <Row key={kind} label={`${KIND[kind] ?? kind} · ${v.entries}`} value={signed(v.total)} />
        ))}
        <Row label="Closing balance" value={credits(s.data.closing_balance)} strong />
      </dl>
    </section>
  );
}

function UsageCard({ month }: { month: "this" | "last" }) {
  const u = useUsage(month);
  if (u.error) return <ErrorState error={u.error} retry={() => void u.refetch()} />;
  if (!u.data) return <Skeleton className="h-56 rounded-card" />;
  return (
    <section aria-label="Usage by employee" className="rounded-card border border-line bg-surface p-6">
      <p className="eyebrow">By employee</p>
      {u.data.employees.length === 0 ? (
        <p className="mt-4 text-sm text-ink-muted">No billed calls this month yet.</p>
      ) : (
        <dl className="mt-2 divide-y divide-line">
          {u.data.employees.map((e) => (
            <Row
              key={e.employee_id ?? "none"}
              label={`${e.name ?? "Removed employee"} · ${e.calls} call${e.calls === 1 ? "" : "s"}, ${Math.round(e.talk_seconds / 60)} min`}
              value={credits(e.credits)}
            />
          ))}
        </dl>
      )}
    </section>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-4 py-3 text-sm">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={`num ${strong ? "text-ink-strong" : "text-ink"}`}>{value}</dd>
    </div>
  );
}

/** Newest first, 50 at a time; older pages are fetched with `before`. */
function Transactions() {
  const first = useTransactions(50);
  const [older, setOlder] = useState<Entry[]>([]);
  const [end, setEnd] = useState(false);
  const rows = [...(first.data?.items ?? []), ...older];
  async function more() {
    const last = rows.at(-1);
    if (!last) return;
    const page = await unwrap<{ items: Entry[] }>(api.GET("/billing/transactions", { params: { query: { limit: 50, before: last.id } } }));
    setOlder((o) => [...o, ...page.items]);
    setEnd(page.items.length < 50);
  }
  if (first.error) return <ErrorState error={first.error} retry={() => void first.refetch()} />;
  return (
    <section aria-labelledby="txns">
      <h2 id="txns" className="display text-2xl">Transactions</h2>
      {/* Focusable so keyboard users can scroll it sideways on a phone. */}
      <div className="mt-4 overflow-x-auto rounded-card border border-line" tabIndex={0} role="region" aria-label="Transactions table">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="text-left text-xs text-ink-muted">
            <tr className="border-b border-line">
              <th className="px-4 py-3 font-medium">When</th>
              <th className="px-4 py-3 font-medium">What</th>
              <th className="px-4 py-3 text-right font-medium">Credits</th>
              <th className="px-4 py-3 text-right font-medium">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="px-4 py-3 whitespace-nowrap text-ink-muted">{date(e.at)}</td>
                <td className="px-4 py-3 text-ink">
                  {KIND[e.kind] ?? e.kind}
                  {e.note && <span className="text-ink-muted"> · {e.note}</span>}
                </td>
                <td className={`num px-4 py-3 text-right ${Number(e.amount) > 0 ? "text-accent" : "text-ink"}`}>{signed(e.amount)}</td>
                <td className="num px-4 py-3 text-right text-ink-muted">{credits(e.balance_after)}</td>
              </tr>
            ))}
            {!first.data && (
              <tr>
                <td colSpan={4} className="p-4">
                  <Skeleton />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {first.data && rows.length >= 50 && !end && (
        <button type="button" className={`${btn.quiet} mt-3`} onClick={() => void more()}>
          Show older
        </button>
      )}
    </section>
  );
}

function Invoices() {
  const list = useInvoices();
  if (list.error) return <ErrorState error={list.error} retry={() => void list.refetch()} />;
  return (
    <section aria-labelledby="invoices">
      <h2 id="invoices" className="display text-2xl">Invoices</h2>
      <p className="mt-1 text-sm text-ink-muted">One per top-up, with GST split out. Prices include GST.</p>
      {list.data?.length === 0 && <p className="mt-4 text-sm text-ink-muted">Your first top-up creates your first invoice.</p>}
      <ul className="mt-4 divide-y divide-line rounded-card border border-line">
        {list.data?.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
            <span className="num text-ink-strong">{i.number}</span>
            <span className="text-ink-muted">{date(i.issued_at)}</span>
            <span className="num text-ink-muted">
              taxable {credits(i.taxable)} · GST {credits(String(Number(i.cgst) + Number(i.sgst) + Number(i.igst)))}
            </span>
            <span className="num text-ink">₹{credits(i.total)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
