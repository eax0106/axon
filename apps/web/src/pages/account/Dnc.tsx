import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { useMe } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";

type Entry = { id: string; phone: string; source: string; reason: string | null; created_at: string };
const SOURCE: Record<string, string> = { manual: "Added", bulk: "Pasted", caller_request: "Asked on a call" };

/** Numbers no employee will ever call: one at a time or pasted in bulk, searchable. */
export function Dnc() {
  const owner = useMe().data?.user.role === "owner";
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setTerm(q.replace(/\D/g, "")), 250);
    return () => clearTimeout(t);
  }, [q]);
  const list = useQuery({ queryKey: ["dnc", term], queryFn: () => unwrap<{ total: number; items: Entry[] }>(api.GET("/dnc", { params: { query: { q: term || undefined, limit: 100 } } })) });
  const [note, setNote] = useState("");
  const { busy, error, run } = useAction();
  const reload = () => qc.invalidateQueries({ queryKey: ["dnc"] });

  function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const phones = String(f.get("phones")).split(/[\n,;]+/).map((p) => p.trim()).filter(Boolean);
    const reason = String(f.get("reason")).trim() || null;
    void run(async () => {
      const r = await unwrap<Record<string, number>>(api.POST("/dnc/bulk", { body: { phones, reason } }));
      setNote(`${r.added} added · ${r.already_listed} already listed · ${r.invalid} not phone numbers`);
      form.reset();
      await reload();
    });
  }
  return (
    <section aria-labelledby="dnc" className="rounded-card border border-line bg-surface p-6">
      <h2 id="dnc" className="eyebrow">Do not call · {list.data?.total ?? "…"}</h2>
      <p className="mt-2 text-sm text-ink-muted">No employee calls these numbers, in any campaign or Instant lead. Anyone who asks on a call to stop is added here by itself.</p>
      <form onSubmit={add} className="mt-4 grid gap-3 sm:grid-cols-[1fr_14rem_auto] sm:items-end">
        <label className="block">
          <span className="text-sm text-ink">Numbers (one per line, or separated by commas)</span>
          <textarea name="phones" required rows={2} className="mt-1.5 block w-full rounded-ctl border border-line-accent bg-surface px-3.5 py-2.5 text-ink-strong outline-none focus:border-accent" />
        </label>
        <label className="block">
          <span className="text-sm text-ink">Reason (optional)</span>
          <input name="reason" maxLength={500} className="mt-1.5 h-12 w-full rounded-ctl border border-line-accent bg-surface px-3.5 text-ink-strong outline-none focus:border-accent" />
        </label>
        <button type="submit" className={`${btn.primary} h-12`} disabled={busy}>Add</button>
      </form>
      {note && <p role="status" className="mt-2 text-sm text-accent">{note}</p>}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
      <input type="search" aria-label="Search do-not-call numbers" placeholder="Search a number" value={q} onChange={(e) => setQ(e.target.value)} className="mt-6 h-10 w-full max-w-xs rounded-ctl border border-line bg-bg px-3 text-sm text-ink outline-none focus:border-accent" />
      {list.error ? <ErrorState error={list.error} retry={() => void list.refetch()} /> : !list.data ? <Skeleton className="mt-3 h-24" /> : (
        <ul className="mt-3 divide-y divide-line">
          {list.data.items.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
              <span className="min-w-0">
                <span className="num text-ink-strong">{d.phone}</span>
                <span className="ml-3 text-xs text-ink-muted">{SOURCE[d.source] ?? d.source} {new Date(d.created_at).toLocaleDateString("en-IN")}{d.reason && ` · ${d.reason}`}</span>
              </span>
              {owner && (
                <Confirm trigger={<button type="button" className="text-xs text-ink-muted hover:text-danger" aria-label={`Remove ${d.phone}`}>Remove</button>}
                  title={`Allow calls to ${d.phone} again?`} body="Campaigns and Instant leads can call this number again." action="Remove"
                  onConfirm={() => void run(async () => { await unwrap(api.DELETE("/dnc/{entry_id}", { params: { path: { entry_id: d.id } } })); await reload(); })} />
              )}
            </li>
          ))}
          {list.data.items.length === 0 && <li className="py-6 text-center text-sm text-ink-muted">{term ? "No number matches." : "Nobody on the list yet."}</li>}
        </ul>
      )}
    </section>
  );
}
