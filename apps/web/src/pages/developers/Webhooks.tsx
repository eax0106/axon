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

type EventInfo = { type: string; description: string; example: unknown };

/** Signed account webhooks: pick events, get the secret once, test, pause, rotate, delete. */
export function Webhooks() {
  const owner = useMe().data?.user.role === "owner";
  const qc = useQueryClient();
  const hooks = useQuery({ queryKey: ["dev", "webhooks"], queryFn: () => unwrap(api.GET("/developer/webhooks")) });
  const events = useQuery({ queryKey: ["dev", "events"], queryFn: () => unwrap<EventInfo[]>(api.GET("/developer/events")), staleTime: Infinity });
  const [chosen, setChosen] = useState<string[]>([]);
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [tested, setTested] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const reload = () => qc.invalidateQueries({ queryKey: ["dev", "webhooks"] });
  const at = (id: string) => ({ params: { path: { endpoint_id: id } } });

  function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    void run(async () => {
      const made = await unwrap(api.POST("/developer/webhooks", { body: { url: String(f.get("url")).trim(), description: String(f.get("description")).trim() || null, events: chosen } }));
      setSecret({ label: `Signing secret for ${made.url}`, value: made.secret });
      setChosen([]);
      form.reset();
      await reload();
    });
  }
  if (hooks.error) return <ErrorState error={hooks.error} retry={() => void hooks.refetch()} />;
  if (!hooks.data) return <Skeleton className="h-40 rounded-card" />;
  return (
    <section aria-labelledby="webhooks" className="space-y-4">
      <h2 id="webhooks" className="eyebrow">Webhooks</h2>
      <p className="text-sm text-ink-muted">Each event is posted to your address, signed with <code className="num">X-Axon-Signature</code>. Failed sends are retried for about 9 hours.</p>
      {secret && <ShownOnce label={secret.label} value={secret.value} onDone={() => setSecret(null)} />}
      {owner && (
        <form onSubmit={create} className="space-y-3 rounded-card border border-line bg-surface p-5">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Address (https)" name="url" inputMode="url" required />
            <Field label="Description (optional)" name="description" maxLength={200} />
          </div>
          <fieldset>
            <legend className="text-sm text-ink">Events</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {events.data?.map((ev) => (
                <label key={ev.type} className="flex items-start gap-2 text-sm">
                  <input type="checkbox" checked={chosen.includes(ev.type)} onChange={(e) => setChosen(e.target.checked ? [...chosen, ev.type] : chosen.filter((x) => x !== ev.type))} className="mt-0.5 accent-[var(--accent)]" />
                  <span><span className="num text-ink">{ev.type}</span><span className="block text-xs text-ink-muted">{ev.description}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          <button type="submit" className={btn.primary} disabled={busy || chosen.length === 0}>Add webhook</button>
        </form>
      )}
      <ul className="space-y-2">
        {hooks.data.map((h) => (
          <li key={h.id} className="rounded-card border border-line bg-surface p-4 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="num block break-all text-ink-strong">{h.url}</span>
                <span className="text-xs text-ink-muted">{h.events.join(", ")}{h.description && ` · ${h.description}`}</span>
              </span>
              <span className={`eyebrow ${h.active ? "" : "text-warn"}`}>● {h.active ? "Active" : "Paused"}</span>
            </div>
            {owner && (
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <button type="button" className="text-ink-muted hover:text-accent" onClick={() => void run(async () => { await unwrap(api.PATCH("/developer/webhooks/{endpoint_id}", { ...at(h.id), body: { active: !h.active } })); await reload(); })}>{h.active ? "Pause" : "Resume"}</button>
                <button type="button" className="text-ink-muted hover:text-accent" onClick={() => void run(async () => { const r = await unwrap(api.POST("/developer/webhooks/{endpoint_id}/test", { ...at(h.id), body: { event: h.events[0] ?? "call.completed" } })); setTested(JSON.stringify(r, null, 2)); })}>Send a test</button>
                <Confirm trigger={<button type="button" className="text-ink-muted hover:text-accent">Rotate secret</button>} title="Make a new signing secret?" body="The old secret stops verifying at once; update your receiver." action="Rotate"
                  onConfirm={() => void run(async () => { const r = await unwrap<{ secret: string }>(api.POST("/developer/webhooks/{endpoint_id}/rotate-secret", at(h.id))); setSecret({ label: `New signing secret for ${h.url}`, value: r.secret }); })} />
                <Confirm danger trigger={<button type="button" className="text-ink-muted hover:text-danger">Delete</button>} title="Delete this webhook?" body="Nothing more is sent to it. Past deliveries stay in the log." action="Delete"
                  onConfirm={() => void run(async () => { await unwrap(api.DELETE("/developer/webhooks/{endpoint_id}", at(h.id))); await reload(); })} />
              </div>
            )}
          </li>
        ))}
        {hooks.data.length === 0 && <li className="rounded-card border border-dashed border-line p-6 text-center text-sm text-ink-muted">No webhooks yet.</li>}
      </ul>
      {tested && <pre tabIndex={0} className="num max-h-60 overflow-auto rounded-ctl border border-line bg-bg p-3 text-xs text-ink">{tested}</pre>}
      {error !== null && <ErrorState error={error} />}
    </section>
  );
}
