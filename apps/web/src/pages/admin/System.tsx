import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { credits } from "../../lib/format";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Section, input, useWrite, when } from "./parts";

type Health = { database: { ok: boolean; ms: number }; redis: { ok: boolean; ms?: number; error?: string }; worker: { last_heartbeat: string | null; silent: boolean }; queues: Record<string, number> };
type Day = { day: string; topups: string; used: string; provider_cost: string; margin: string };

/** What needs a person now, the platform's own health, money in and out, and a note to everyone. */
export function System() {
  const alerts = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => unwrap<{ kind: string; detail: string }[]>(api.GET("/admin/alerts")), refetchInterval: 60_000 });
  const health = useQuery({ queryKey: ["admin", "system"], queryFn: () => unwrap<Health>(api.GET("/admin/system")), refetchInterval: 30_000 });
  const h = health.data;
  return (
    <div className="space-y-6">
      <Section id="alerts" title="Needs attention">
        {alerts.error ? <ErrorState error={alerts.error} /> : !alerts.data ? <Skeleton className="h-10" /> : alerts.data.length === 0 ? <p className="text-sm text-accent">● All clear.</p> : (
          <ul className="space-y-1 text-sm">{alerts.data.map((a, i) => <li key={i} className="text-warn">● {a.detail}</li>)}</ul>
        )}
      </Section>
      <Section id="health" title="System">
        {health.error ? <ErrorState error={health.error} /> : !h ? <Skeleton className="h-24" /> : (
          <dl className="grid gap-px overflow-hidden rounded-ctl border border-line bg-line sm:grid-cols-3 lg:grid-cols-7">
            {[
              ["Database", h.database.ok ? `ok · ${h.database.ms} ms` : "down", h.database.ok],
              ["Redis", h.redis.ok ? `ok · ${h.redis.ms} ms` : h.redis.error ?? "down", h.redis.ok],
              ["Worker", h.worker.silent ? `silent since ${when(h.worker.last_heartbeat)}` : `seen ${when(h.worker.last_heartbeat)}`, !h.worker.silent],
              ...Object.entries(h.queues).map(([k, v]) => [k.replaceAll("_", " "), String(v), true] as const),
            ].map(([k, v, ok]) => (
              <div key={String(k)} className="bg-surface p-3"><dt className="text-xs text-ink-muted capitalize">{k}</dt><dd className={`num mt-1 text-sm ${ok ? "text-ink-strong" : "text-danger"}`}>{v}</dd></div>
            ))}
          </dl>
        )}
      </Section>
      <Revenue />
      <Announce />
    </div>
  );
}

function Revenue() {
  const [days, setDays] = useState(30);
  const r = useQuery({ queryKey: ["admin", "revenue", days], queryFn: () => unwrap<{ items: Day[] }>(api.GET("/admin/revenue", { params: { query: { days } } })) });
  const sum = (k: keyof Day) => credits(String((r.data?.items ?? []).reduce((a, d) => a + Number(d[k]), 0)));
  return (
    <Section id="revenue" title="Revenue, INR">
      <select aria-label="Days" value={days} onChange={(e) => setDays(Number(e.target.value))} className={input}>
        {[7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}
      </select>
      {r.error ? <ErrorState error={r.error} /> : !r.data ? <Skeleton className="mt-3 h-32" /> : (
        <div tabIndex={0} className="mt-3 max-h-80 overflow-auto">
          <table className="num w-full text-right text-sm">
            <thead className="text-xs text-ink-muted"><tr><th className="py-1 text-left font-normal">Day</th><th className="font-normal">Top-ups</th><th className="font-normal">Used</th><th className="font-normal">Vendor cost</th><th className="font-normal">Margin</th></tr></thead>
            <tbody className="text-ink">
              <tr className="border-b border-line text-ink-strong"><td className="py-1.5 text-left">Total</td><td>{sum("topups")}</td><td>{sum("used")}</td><td>{sum("provider_cost")}</td><td>{sum("margin")}</td></tr>
              {r.data.items.map((d) => <tr key={d.day}><td className="py-1 text-left text-ink-muted">{d.day}</td><td>{credits(d.topups)}</td><td>{credits(d.used)}</td><td>{credits(d.provider_cost)}</td><td className={Number(d.margin) < 0 ? "text-danger" : ""}>{credits(d.margin)}</td></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function Announce() {
  const { busy, write, outcome } = useWrite();
  function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    write(async () => {
      const r = await unwrap<{ accounts: number }>(api.POST("/admin/announcements", { body: { title: String(f.get("title")).trim(), body: String(f.get("body")).trim() } }));
      form.reset();
      return `Sent to ${r.accounts} accounts' notification bells.`;
    });
  }
  return (
    <Section id="announce" title="Announcement to every account">
      <form onSubmit={send} className="space-y-2">
        <input name="title" aria-label="Title" required minLength={3} maxLength={200} placeholder="Title" className={`${input} w-full`} />
        <textarea name="body" aria-label="Message" required maxLength={4000} rows={3} className="block w-full rounded-ctl border border-line-accent bg-bg px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
        <button type="submit" className={btn.primary} disabled={busy}>Send to everyone</button>
      </form>
      {outcome}
    </Section>
  );
}
