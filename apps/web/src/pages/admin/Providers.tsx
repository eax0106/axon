import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { credits } from "../../lib/format";
import { queryClient } from "../../lib/queries";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Section, input, useWrite, when } from "./parts";

type Report = { kind: string; name: string; selected: boolean; status: string; missing_keys: string[]; error: string | null };
type Score = { kind: string; vendor: string; ok: number; failed: number; success_rate: number | null; healthy: boolean };
type Rate = { kind: string; vendor: string; unit: string; inr_per_unit: string };
type Cost = { kind: string; vendor: string; unit: string; usage: string; inr_per_unit: string | null; cost_inr: string | null };
type Balance = { vendor: string; recorded_inr: string; recorded_at: string; spent_since_inr: string; estimated_inr: string; alert_below_inr: string | null; low: boolean };

/** Every vendor: is it configured, is it working, what it costs, and what is left on it. */
export function Providers() {
  const report = useQuery({ queryKey: ["admin", "providers"], queryFn: () => unwrap<{ providers: Report[] }>(api.GET("/admin/providers")) });
  const health = useQuery({ queryKey: ["admin", "health"], queryFn: () => unwrap<{ window_minutes: number; providers: Score[] }>(api.GET("/admin/provider-health")), refetchInterval: 30_000 });
  const score = (kind: string, vendor: string) => health.data?.providers.find((s) => s.kind === kind && s.vendor === vendor);
  return (
    <div className="space-y-6">
      <Section id="vendors" title={`Vendors · live score over ${health.data?.window_minutes ?? "…"} min`}>
        {report.error ? <ErrorState error={report.error} /> : !report.data ? <Skeleton className="h-40" /> : (
          <ul className="divide-y divide-line text-sm">
            {report.data.providers.map((p) => {
              const s = score(p.kind, p.name);
              return (
                <li key={`${p.kind}/${p.name}`} className="grid grid-cols-[6rem_1fr_auto] gap-x-4 py-2 sm:grid-cols-[7rem_10rem_1fr_12rem]">
                  <span className="text-ink-muted">{p.kind}</span>
                  <span className="num text-ink-strong">{p.name}{p.selected && <span className="text-accent"> · in use</span>}</span>
                  <span className={`${p.status === "ok" ? "text-ink-muted" : "text-warn"} sm:order-last`}>{s ? `${s.ok} ok · ${s.failed} failed${s.healthy ? "" : " · avoided"}` : ""}</span>
                  <span className={p.status === "ok" ? "text-accent" : "text-warn"}>{p.status}{p.missing_keys.length > 0 && <span className="num text-xs text-ink-muted"> · needs {p.missing_keys.join(", ")}</span>}{p.error && <span className="text-xs text-danger"> · {p.error}</span>}</span>
                </li>
              );
            })}
          </ul>
        )}
      </Section>
      <Costs />
      <div className="grid gap-6 lg:grid-cols-2">
        <Rates />
        <Balances vendors={[...new Set(report.data?.providers.map((p) => p.name) ?? [])]} />
      </div>
    </div>
  );
}

function Costs() {
  const [days, setDays] = useState(30);
  const c = useQuery({ queryKey: ["admin", "costs", days], queryFn: () => unwrap<{ total_inr: string; unpriced: string[]; items: Cost[] }>(api.GET("/admin/provider-costs", { params: { query: { days } } })) });
  return (
    <Section id="costs" title="Usage and cost">
      <div className="flex flex-wrap items-center gap-3">
        <select aria-label="Days" value={days} onChange={(e) => setDays(Number(e.target.value))} className={input}>{[1, 7, 30, 90].map((d) => <option key={d} value={d}>Last {d} days</option>)}</select>
        {c.data && <span className="num text-ink-strong">₹{credits(c.data.total_inr)}</span>}
        {c.data && c.data.unpriced.length > 0 && <span className="text-sm text-warn">No rate for {c.data.unpriced.join(", ")}: their cost is missing from the total.</span>}
      </div>
      {c.error ? <ErrorState error={c.error} /> : !c.data ? <Skeleton className="mt-3 h-24" /> : (
        <ul className="mt-3 divide-y divide-line text-sm">
          {c.data.items.map((r) => (
            <li key={`${r.kind}${r.vendor}${r.unit}`} className="grid grid-cols-[1fr_auto] gap-x-4 py-1.5 sm:grid-cols-[1fr_10rem_10rem]">
              <span className="num text-ink">{r.kind}/{r.vendor} <span className="text-ink-muted">{r.unit}</span></span>
              <span className="num text-right text-ink-muted">{Number(r.usage).toLocaleString("en-IN")}</span>
              <span className="num text-right text-ink-strong">{r.cost_inr === null ? "no rate" : `₹${credits(r.cost_inr)}`}</span>
            </li>
          ))}
          {c.data.items.length === 0 && <li className="py-4 text-center text-ink-muted">No usage in this range.</li>}
        </ul>
      )}
    </Section>
  );
}

function Rates() {
  const rates = useQuery({ queryKey: ["admin", "rates"], queryFn: () => unwrap<Rate[]>(api.GET("/admin/provider-rates")) });
  const { busy, write, outcome } = useWrite();
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const body = { kind: String(f.get("kind")).trim(), vendor: String(f.get("vendor")).trim(), unit: String(f.get("unit")).trim(), inr_per_unit: String(f.get("rate")).trim() };
    const before = rates.data?.find((r) => r.kind === body.kind && r.vendor === body.vendor && r.unit === body.unit);
    write(async () => {
      await unwrap(api.PUT("/admin/provider-rates", { body }));
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["admin"] });
      return `${body.kind}/${body.vendor} per ${body.unit}: ₹${before ? `${before.inr_per_unit} → ` : ""}${body.inr_per_unit}.`;
    });
  }
  return (
    <Section id="rates" title="Rates (from each vendor's price list)">
      {rates.error ? <ErrorState error={rates.error} /> : !rates.data ? <Skeleton className="h-24" /> : (
        <ul className="divide-y divide-line text-sm">
          {rates.data.map((r) => <li key={`${r.kind}${r.vendor}${r.unit}`} className="flex justify-between gap-3 py-1.5"><span className="num text-ink">{r.kind}/{r.vendor} <span className="text-ink-muted">per {r.unit}</span></span><span className="num text-ink-strong">₹{r.inr_per_unit}</span></li>)}
          {rates.data.length === 0 && <li className="py-3 text-ink-muted">No rates yet: costs can't be counted.</li>}
        </ul>
      )}
      <form onSubmit={save} className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-[1fr_1fr_1fr_1fr_auto]">
        <input name="kind" aria-label="Kind" required placeholder="tts" className={input} />
        <input name="vendor" aria-label="Vendor" required placeholder="sarvam" className={input} />
        <input name="unit" aria-label="Unit" required placeholder="character" className={input} />
        <input name="rate" aria-label="INR per unit" required inputMode="decimal" placeholder="0.0003" className={input} />
        <button type="submit" className={btn.primary} disabled={busy}>Set rate</button>
      </form>
      {outcome}
    </Section>
  );
}

function Balances({ vendors }: { vendors: string[] }) {
  const list = useQuery({ queryKey: ["admin", "balances"], queryFn: () => unwrap<Balance[]>(api.GET("/admin/provider-balances")) });
  const { busy, write, outcome } = useWrite();
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const vendor = String(f.get("vendor"));
    const alert = String(f.get("alert")).trim();
    write(async () => {
      const b = await unwrap<Balance>(api.PUT("/admin/provider-balances/{vendor}", { params: { path: { vendor } }, body: { balance_inr: String(f.get("balance")).trim(), alert_below_inr: alert || null } }));
      form.reset();
      await queryClient.invalidateQueries({ queryKey: ["admin"] });
      return `${vendor}: ₹${credits(b.recorded_inr)} recorded now${b.alert_below_inr ? `, alert under ₹${credits(b.alert_below_inr)}` : ""}.`;
    });
  }
  return (
    <Section id="balances" title="Vendor balances">
      {list.error ? <ErrorState error={list.error} /> : !list.data ? <Skeleton className="h-24" /> : (
        <ul className="divide-y divide-line text-sm">
          {list.data.map((b) => (
            <li key={b.vendor} className="py-1.5">
              <div className="flex justify-between gap-3"><span className="num text-ink">{b.vendor}</span><span className={`num ${b.low ? "text-danger" : "text-ink-strong"}`}>≈ ₹{credits(b.estimated_inr)}</span></div>
              <p className="text-xs text-ink-muted">₹{credits(b.recorded_inr)} read {when(b.recorded_at)}, ₹{credits(b.spent_since_inr)} used since{b.alert_below_inr && ` · alert under ₹${credits(b.alert_below_inr)}`}</p>
            </li>
          ))}
          {list.data.length === 0 && <li className="py-3 text-ink-muted">No balance recorded yet.</li>}
        </ul>
      )}
      <form onSubmit={save} className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-[1fr_1fr_1fr_auto]">
        <select name="vendor" aria-label="Vendor" required className={input}>{vendors.map((v) => <option key={v}>{v}</option>)}</select>
        <input name="balance" aria-label="Balance now, INR" required inputMode="decimal" placeholder="Balance ₹" className={input} />
        <input name="alert" aria-label="Alert below, INR (optional)" inputMode="decimal" placeholder="Alert under ₹" className={input} />
        <button type="submit" className={btn.primary} disabled={busy}>Record</button>
      </form>
      {outcome}
    </Section>
  );
}
