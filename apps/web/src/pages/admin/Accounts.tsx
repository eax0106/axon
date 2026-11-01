import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api, supportSession, unwrap } from "../../lib/api";
import { credits } from "../../lib/format";
import { queryClient } from "../../lib/queries";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Section, input, useWrite, when } from "./parts";

type Row = { id: string; name: string; business_name: string | null; owner_email: string | null; credit_balance: string; created_at: string };
type Detail = Omit<Row, "owner_email"> & {
  max_call_s: number;
  users: { id: string; email: string; role: string }[];
  employees: number;
  numbers: number;
  calls_30d: number;
  ledger: { kind: string; amount: string; balance_after: string; note: string | null; created_at: string }[];
};
const PAGE = 50;

export function Accounts() {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const t = setTimeout(() => { setTerm(q.trim()); setOffset(0); }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const list = useQuery({ queryKey: ["admin", "accounts", term, offset], queryFn: () => unwrap<{ total: number; items: Row[] }>(api.GET("/admin/accounts", { params: { query: { q: term || undefined, limit: PAGE, offset } } })) });
  return (
    <>
      <input type="search" aria-label="Find an account" placeholder="Name, business or a person's email" value={q} onChange={(e) => setQ(e.target.value)} className={`${input} w-full max-w-md`} />
      {list.error ? <div className="mt-4"><ErrorState error={list.error} retry={() => void list.refetch()} /></div> : !list.data ? <Skeleton className="mt-4 h-64 rounded-card" /> : (
        <>
          <p className="mt-4 text-sm text-ink-muted">{list.data.total} accounts</p>
          <ul className="mt-2 divide-y divide-line rounded-card border border-line">
            {list.data.items.map((a) => (
              <li key={a.id}>
                <Link to={`/admin/accounts/${a.id}`} className="grid grid-cols-[1fr_auto] gap-x-4 px-4 py-3 text-sm hover:bg-accent-soft sm:grid-cols-[1fr_16rem_8rem_8rem]">
                  <span className="truncate text-ink-strong">{a.name}{a.business_name && <span className="text-ink-muted"> · {a.business_name}</span>}</span>
                  <span className="num text-right text-ink sm:order-last">{credits(a.credit_balance)}</span>
                  <span className="truncate text-ink-muted">{a.owner_email ?? "no owner"}</span>
                  <span className="text-ink-muted">{new Date(a.created_at).toLocaleDateString("en-IN")}</span>
                </Link>
              </li>
            ))}
            {list.data.items.length === 0 && <li className="p-6 text-center text-sm text-ink-muted">No account matches.</li>}
          </ul>
          {list.data.total > PAGE && (
            <div className="mt-3 flex items-center gap-2 text-sm">
              <button type="button" className={btn.ghost} disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Newer</button>
              <button type="button" className={btn.ghost} disabled={offset + PAGE >= list.data.total} onClick={() => setOffset(offset + PAGE)}>Older</button>
              <span className="text-ink-muted">{offset + 1}–{Math.min(offset + PAGE, list.data.total)}</span>
            </div>
          )}
        </>
      )}
    </>
  );
}

export function AccountDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const path = { params: { path: { account_id: id } } };
  const detail = useQuery({ queryKey: ["admin", "account", id], queryFn: () => unwrap<Detail>(api.GET("/admin/accounts/{account_id}", path)) });
  const adjust = useWrite();
  const act = useWrite();
  if (detail.error) return <ErrorState error={detail.error} retry={() => void detail.refetch()} />;
  const a = detail.data;
  if (!a) return <Skeleton className="h-64 rounded-card" />;

  function credit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const amount = String(f.get("amount")).trim();
    adjust.write(async () => {
      const r = await unwrap<{ balance: string }>(api.POST("/admin/accounts/{account_id}/credits", { ...path, body: { amount, note: String(f.get("note")).trim() } }));
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["admin", "account", id] });
      return `${Number(amount) > 0 ? "Added" : "Took back"} ${credits(amount.replace("-", ""))} credits. Balance now ${credits(r.balance)}.`;
    });
  }
  function impersonate(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const reason = String(new FormData(e.currentTarget).get("reason")).trim();
    act.write(async () => {
      const r = await unwrap<{ access_token: string }>(api.POST("/admin/accounts/{account_id}/impersonate", { ...path, body: { reason } }));
      supportSession.start(r.access_token);
      navigate("/");
      return "";
    });
  }
  return (
    <div className="space-y-6">
      <Link to="/admin/accounts" className="text-sm text-ink-muted hover:text-accent">← Accounts</Link>
      <header>
        <h2 className="display text-3xl">{a.name}</h2>
        <p className="mt-1 text-sm text-ink-muted">{a.business_name ?? "No business name"} · since {new Date(a.created_at).toLocaleDateString("en-IN")} · calls capped at {a.max_call_s / 60} min</p>
      </header>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-4">
        {[["Credits", credits(a.credit_balance)], ["Employees", a.employees], ["Numbers", a.numbers], ["Calls, 30 days", a.calls_30d]].map(([k, v]) => (
          <div key={k} className="bg-surface p-4"><dt className="text-xs text-ink-muted">{k}</dt><dd className="num mt-1 text-xl text-ink-strong">{v}</dd></div>
        ))}
      </dl>
      <div className="grid gap-6 lg:grid-cols-2">
        <Section id="session" title="Support session">
          <p className="text-sm text-ink-muted">Act as the owner for 30 minutes to see what they see. The reason and every change are logged under your name. Passwords, keys, numbers and payments stay off limits.</p>
          <form onSubmit={impersonate} className="mt-3 flex gap-2">
            <input name="reason" aria-label="Reason" required minLength={5} maxLength={500} placeholder="Ticket 42: calls not starting" className={`${input} min-w-0 flex-1`} />
            <button type="submit" className={btn.primary} disabled={act.busy}>Start</button>
          </form>
          {act.outcome}
        </Section>
        <Section id="credits" title="Adjust credits">
          <form onSubmit={credit} className="flex flex-wrap gap-2">
            <input name="amount" aria-label="Credits (negative takes back)" required inputMode="decimal" pattern="-?\d+(\.\d{1,2})?" placeholder="100 or -25" className={`${input} w-32`} />
            <input name="note" aria-label="Note" required minLength={3} maxLength={300} placeholder="Goodwill: dropped calls on 30 Oct" className={`${input} min-w-0 flex-1`} />
            <button type="submit" className={btn.primary} disabled={adjust.busy}>Post</button>
          </form>
          {adjust.outcome}
        </Section>
      </div>
      <div className="grid gap-6 lg:grid-cols-[1fr_2fr]">
        <Section id="people" title="People">
          <ul className="space-y-2 text-sm">{a.users.map((u) => <li key={u.id} className="flex justify-between gap-3"><span className="truncate text-ink">{u.email}</span><span className="text-ink-muted">{u.role}</span></li>)}</ul>
        </Section>
        <Section id="ledger" title="Ledger, latest 20">
          <ul className="divide-y divide-line text-sm">
            {a.ledger.map((l, i) => (
              <li key={i} className="grid grid-cols-[1fr_auto_auto] gap-x-4 py-2">
                <span className="truncate text-ink">{l.kind}{l.note && <span className="text-ink-muted"> · {l.note}</span>}<span className="block text-xs text-ink-muted">{when(l.created_at)}</span></span>
                <span className={`num ${Number(l.amount) < 0 ? "text-ink" : "text-accent"}`}>{Number(l.amount) > 0 ? "+" : ""}{credits(l.amount)}</span>
                <span className="num text-ink-muted">{credits(l.balance_after)}</span>
              </li>
            ))}
          </ul>
        </Section>
      </div>
    </div>
  );
}
