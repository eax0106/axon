import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { useMe } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { Field } from "../../ui/Field";
import { ShownOnce } from "../../ui/Secret";
import { ErrorState, Skeleton } from "../../ui/states";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "never");

/** Keys for the public API. Only the owner makes or revokes them; a key is shown once. */
export function Keys() {
  const owner = useMe().data?.user.role === "owner";
  const keys = useQuery({ queryKey: ["dev", "keys"], queryFn: () => unwrap(api.GET("/developer/keys")) });
  const qc = useQueryClient();
  const [fresh, setFresh] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const name = String(new FormData(form).get("name")).trim();
    void run(async () => {
      const made = await unwrap(api.POST("/developer/keys", { body: { name } }));
      setFresh(made.key);
      form.reset();
      await qc.invalidateQueries({ queryKey: ["dev", "keys"] });
    });
  }
  if (keys.error) return <ErrorState error={keys.error} retry={() => void keys.refetch()} />;
  if (!keys.data) return <Skeleton className="h-40 rounded-card" />;
  const active = keys.data.filter((k) => !k.revoked_at);
  return (
    <section aria-labelledby="keys" className="space-y-4">
      <h2 id="keys" className="eyebrow">API keys · {active.length}/20</h2>
      {fresh && <ShownOnce label="Your new API key" value={fresh} onDone={() => setFresh(null)} />}
      {owner ? (
        <form onSubmit={create} className="flex max-w-xl items-end gap-2">
          <div className="flex-1"><Field label="New key for" name="name" placeholder="Zapier, our CRM" maxLength={100} required /></div>
          <button type="submit" className={`${btn.primary} h-12`} disabled={busy || active.length >= 20}>Create key</button>
        </form>
      ) : <p className="text-sm text-ink-muted">Only the account owner creates or revokes keys.</p>}
      <ul className="divide-y divide-line rounded-card border border-line">
        {keys.data.map((k) => (
          <li key={k.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
            <span className="min-w-0">
              <span className="block text-ink-strong">{k.name}</span>
              <span className="num text-xs text-ink-muted">{k.prefix}… · made {when(k.created_at)} · last used {when(k.last_used_at)}</span>
            </span>
            {k.revoked_at ? <span className="text-xs text-ink-muted">Revoked {when(k.revoked_at)}</span> : owner && (
              <Confirm danger trigger={<button type="button" className={btn.quiet}>Revoke</button>} title={`Revoke ${k.name}?`}
                body="Anything using this key stops working at once. This can't be undone." action="Revoke"
                onConfirm={() => void run(async () => { await unwrap(api.DELETE("/developer/keys/{key_id}", { params: { path: { key_id: k.id } } })); await qc.invalidateQueries({ queryKey: ["dev", "keys"] }); })} />
            )}
          </li>
        ))}
        {keys.data.length === 0 && <li className="p-6 text-center text-sm text-ink-muted">No keys yet.</li>}
      </ul>
      {error !== null && <ErrorState error={error} />}
    </section>
  );
}
