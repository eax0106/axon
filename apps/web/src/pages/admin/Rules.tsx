import { useQuery } from "@tanstack/react-query";
import type { FormEvent } from "react";

import { api, unwrap } from "../../lib/api";
import { queryClient } from "../../lib/queries";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Section, input, useWrite, when } from "./parts";

type Purpose = "promotional" | "service" | "transactional";
type NumberType = "regular" | "140" | "1600";
type Context = "outbound" | "callback" | "inbound" | "instant";
type Rule = { purpose: Purpose; number_type: NumberType; context: Context; allowed: boolean; reason: string | null };
type Capacity = { max_concurrent_calls: number; calls_in_flight: number; numbers: number; channels: number; reconcile: { id: string; account_id: string; e164: string; provider: string; created_at: string }[] };
const PURPOSES: Purpose[] = ["promotional", "service", "transactional"];
const TYPES: NumberType[] = ["regular", "140", "1600"];
const CONTEXTS: Context[] = ["outbound", "callback", "inbound", "instant"];

/** Which calls may go out from which number series, how Instant calls are read, carrier capacity. */
export function Rules() {
  const rules = useQuery({ queryKey: ["admin", "rules"], queryFn: () => unwrap<{ instant_policy: string; rules: Rule[] }>(api.GET("/admin/dial-rules")) });
  const { busy, write, outcome } = useWrite();
  const reload = () => queryClient.invalidateQueries({ queryKey: ["admin", "rules"] });
  const find = (p: Purpose, t: NumberType, c: Context) => rules.data?.rules.find((r) => r.purpose === p && r.number_type === t && r.context === c);
  function set(rule: Rule) {
    write(async () => {
      await unwrap(api.PUT("/admin/dial-rules", { body: rule }));
      await reload();
      return `${rule.purpose} calls from ${rule.number_type} numbers (${rule.context}) are now ${rule.allowed ? "allowed" : `refused${rule.reason ? `: ${rule.reason}` : ""}`}.`;
    });
  }
  function refuse(e: FormEvent<HTMLFormElement>, p: Purpose, t: NumberType, c: Context) {
    e.preventDefault();
    set({ purpose: p, number_type: t, context: c, allowed: false, reason: String(new FormData(e.currentTarget).get("reason")).trim() || null });
  }
  if (rules.error) return <ErrorState error={rules.error} retry={() => void rules.refetch()} />;
  if (!rules.data) return <Skeleton className="h-64 rounded-card" />;
  const mode = rules.data.instant_policy;
  return (
    <div className="space-y-6">
      <Section id="instant" title="Instant calls">
        <p className="text-sm text-ink-muted">Strict treats an Instant call as outbound (the rule table's outbound row decides); relaxed treats it as the lead's own request (the instant row decides).</p>
        <div role="radiogroup" aria-label="Instant policy" className="mt-3 flex w-fit gap-1 rounded-ctl border border-line p-1">
          {(["strict", "relaxed"] as const).map((m) => (
            <button key={m} type="button" role="radio" aria-checked={mode === m} disabled={busy}
              onClick={() => mode !== m && write(async () => { await unwrap(api.PUT("/admin/instant-policy", { body: { mode: m } })); await reload(); return `Instant policy: ${mode} → ${m}.`; })}
              className="rounded-tag px-3 py-1 text-sm text-ink-muted capitalize aria-checked:bg-accent-soft aria-checked:text-ink-strong">{m}</button>
          ))}
        </div>
      </Section>
      <Section id="dial" title="Dialing rules">
        <p className="text-sm text-ink-muted">A pairing with no rule is refused. Every change applies to the next call.</p>
        {outcome}
        <div tabIndex={0} className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[44rem] text-sm">
            <thead className="text-xs text-ink-muted"><tr><th className="py-1 text-left font-normal">Purpose · series</th>{CONTEXTS.map((c) => <th key={c} className="font-normal capitalize">{c}</th>)}</tr></thead>
            <tbody>
              {PURPOSES.flatMap((p) => TYPES.map((t) => (
                <tr key={p + t} className="border-t border-line">
                  <th scope="row" className="py-2 text-left font-normal text-ink">{p} · <span className="num">{t}</span></th>
                  {CONTEXTS.map((c) => {
                    const r = find(p, t, c);
                    const label = `${p} from ${t}, ${c}`;
                    return (
                      <td key={c} className="px-1 py-2 align-top">
                        {r?.allowed ? (
                          <button type="button" aria-label={`${label}: allowed. Refuse`} disabled={busy} onClick={() => set({ purpose: p, number_type: t, context: c, allowed: false, reason: null })} className="w-full rounded-tag bg-accent-soft px-2 py-1 text-accent">Allowed</button>
                        ) : (
                          <div>
                            <button type="button" aria-label={`${label}: ${r ? "refused" : "no rule"}. Allow`} disabled={busy} onClick={() => set({ purpose: p, number_type: t, context: c, allowed: true, reason: null })} className={`w-full rounded-tag border border-line px-2 py-1 ${r ? "text-danger" : "text-ink-muted"}`}>{r ? "Refused" : "No rule"}</button>
                            {r && <form onSubmit={(e) => refuse(e, p, t, c)}><input name="reason" aria-label={`Reason, ${label}`} defaultValue={r.reason ?? ""} placeholder="Reason" className="mt-1 h-7 w-full rounded-tag border border-line bg-bg px-1.5 text-xs text-ink outline-none focus:border-accent" /></form>}
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </Section>
      <CapacityAndSettle />
    </div>
  );
}

function CapacityAndSettle() {
  const cap = useQuery({ queryKey: ["admin", "capacity"], queryFn: () => unwrap<Capacity>(api.GET("/admin/capacity")), refetchInterval: 30_000 });
  const { busy, write, outcome } = useWrite();
  function settle(e: FormEvent<HTMLFormElement>, id: string, e164: string) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const outcome = String(f.get("outcome")) as "kept" | "refunded";
    write(async () => {
      await unwrap(api.POST("/admin/numbers/{number_id}/settle", { params: { path: { number_id: id } }, body: { outcome, provider_ref: String(f.get("ref")).trim() || null, note: String(f.get("note")).trim() } }));
      await queryClient.invalidateQueries({ queryKey: ["admin"] });
      return outcome === "kept" ? `${e164} is live; the charge stands.` : `${e164} released; the charge went back to the account.`;
    });
  }
  if (cap.error) return <ErrorState error={cap.error} />;
  const c = cap.data;
  if (!c) return <Skeleton className="h-32 rounded-card" />;
  return (
    <Section id="capacity" title="Carrier capacity">
      <p className="num text-ink-strong">{c.calls_in_flight} / {c.max_concurrent_calls} calls now <span className="text-sm text-ink-muted">· {c.numbers} numbers, {c.channels} lines</span></p>
      <h3 className="mt-5 text-sm text-ink">Purchases to settle</h3>
      <p className="text-xs text-ink-muted">Bought while the carrier's answer was lost. Check with the carrier first; this can be done once.</p>
      <ul className="mt-2 space-y-2">
        {c.reconcile.map((n) => (
          <li key={n.id} className="rounded-ctl border border-line p-3 text-sm">
            <p className="num text-ink-strong">{n.e164} <span className="text-xs text-ink-muted">{n.provider} · {when(n.created_at)}</span></p>
            <form onSubmit={(e) => settle(e, n.id, n.e164)} className="mt-2 flex flex-wrap gap-2">
              <select name="outcome" aria-label={`Outcome for ${n.e164}`} className={input}><option value="kept">Carrier sold it: keep</option><option value="refunded">Not sold: refund</option></select>
              <input name="ref" aria-label="Carrier's id (if kept)" placeholder="Carrier's id" className={`${input} w-36`} />
              <input name="note" aria-label="Note" required minLength={3} maxLength={300} placeholder="Checked with carrier support" className={`${input} min-w-0 flex-1`} />
              <button type="submit" className={btn.primary} disabled={busy}>Settle</button>
            </form>
          </li>
        ))}
        {c.reconcile.length === 0 && <li className="text-sm text-ink-muted">Nothing to settle.</li>}
      </ul>
      {outcome}
    </Section>
  );
}
