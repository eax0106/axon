import { useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "../../lib/api";
import { type Note, OUTCOME, useLead } from "../../lib/data";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";
import { Notes } from "../calls/Notes";

const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

export default function LeadDetail() {
  const { id = "" } = useParams();
  const lead = useLead(id);
  const qc = useQueryClient();
  const { busy, error, run } = useAction();
  const l = lead.data;
  if (lead.error) return <ErrorState error={lead.error} retry={() => void lead.refetch()} />;
  if (!l) return <Skeleton className="h-96 rounded-card" />;
  const path = { params: { path: { lead_id: l.id } } };

  function rename(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name")).trim();
    void run(async () => {
      await unwrap(api.PATCH("/leads/{lead_id}", { ...path, body: { name: name || null } }));
      await qc.invalidateQueries({ queryKey: ["leads"] });
    });
  }

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_320px]">
      <div className="min-w-0 space-y-8">
        <header>
          <p className="eyebrow">Lead</p>
          <form onSubmit={rename} className="mt-3 flex flex-wrap items-center gap-2">
            <label htmlFor="lead-name" className="sr-only">Name</label>
            <input id="lead-name" name="name" defaultValue={l.name ?? ""} placeholder="Add a name" maxLength={200}
              className="display min-w-0 flex-1 bg-transparent text-3xl outline-none placeholder:text-ink-muted" />
            <button type="submit" className={btn.quiet} disabled={busy}>Save name</button>
          </form>
          <p className="num mt-1 text-ink-muted">{l.phone}</p>
        </header>
        {error !== null && <ErrorState error={error} />}

        {Object.keys(l.fields).length > 0 && (
          <section aria-labelledby="fields">
            <h2 id="fields" className="eyebrow">Details</h2>
            <dl className="mt-2 divide-y divide-line border-y border-line">
              {Object.entries(l.fields).map(([k, v]) => (
                <div key={k} className="flex justify-between gap-4 py-2.5 text-sm">
                  <dt className="num text-ink-muted">{k}</dt>
                  <dd className="text-right text-ink">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}

        <section aria-labelledby="lead-calls">
          <h2 id="lead-calls" className="eyebrow">Calls</h2>
          <ul className="mt-3 divide-y divide-line rounded-card border border-line">
            {l.calls.map((c) => (
              <li key={c.id}>
                <Link to={`/calls/${c.id}`} className="block px-4 py-3 transition-colors duration-150 hover:bg-accent-soft">
                  <span className="flex justify-between text-sm">
                    <span className="text-ink-strong">{c.outcome ? OUTCOME[c.outcome] ?? c.outcome : "No outcome"}</span>
                    <span className="text-ink-muted">{when(c.created_at)}</span>
                  </span>
                  {c.summary && <span className="mt-1 block truncate text-sm text-ink-muted">{c.summary}</span>}
                </Link>
              </li>
            ))}
            {l.calls.length === 0 && <li className="p-4 text-sm text-ink-muted">Not called yet.</li>}
          </ul>
        </section>
      </div>

      <aside className="space-y-8">
        <section aria-labelledby="memory">
          <h2 id="memory" className="eyebrow">What the employee remembers</h2>
          <p className="mt-2 text-sm whitespace-pre-line text-ink">{l.memory || "Nothing yet."}</p>
          {l.memory && (
            <Confirm trigger={<button type="button" className={`${btn.quiet} mt-2`}>Forget this caller</button>}
              title="Forget this caller?" body="Your employees start fresh with this person on the next call. Calls and notes stay." action="Forget"
              onConfirm={() => void run(async () => { await unwrap(api.DELETE("/leads/{lead_id}/memory", path)); await qc.invalidateQueries({ queryKey: ["leads", l.id] }); })} />
          )}
        </section>
        <Notes notes={(l.notes ?? []) as Note[]} refresh={["leads", l.id]} add={(body) => unwrap(api.POST("/leads/{lead_id}/notes", { ...path, body: { body } }))} />
      </aside>
    </div>
  );
}
