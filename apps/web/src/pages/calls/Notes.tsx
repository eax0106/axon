import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useRef } from "react";

import { api, unwrap } from "../../lib/api";
import type { Note } from "../../lib/data";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";

const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

/** Notes on a call or a lead; `refresh` names the query that holds them. */
export function Notes({ notes, add, refresh }: { notes: Note[]; add: (body: string) => Promise<unknown>; refresh: unknown[] }) {
  const qc = useQueryClient();
  const box = useRef<HTMLTextAreaElement>(null);
  const { busy, error, run } = useAction();
  const reload = () => qc.invalidateQueries({ queryKey: refresh });

  function submit(e: FormEvent) {
    e.preventDefault();
    const body = box.current?.value.trim();
    if (!body) return;
    void run(async () => {
      await add(body);
      if (box.current) box.current.value = "";
      await reload();
    });
  }
  return (
    <section aria-labelledby="notes">
      <h2 id="notes" className="eyebrow">Notes</h2>
      <ul className="mt-3 space-y-2">
        {notes.map((n) => (
          <li key={n.id} className="group rounded-card border border-line bg-surface p-3 text-sm">
            <p className="whitespace-pre-line text-ink">{n.body}</p>
            <p className="mt-1 flex justify-between text-xs text-ink-muted">
              {when(n.created_at)}
              <button type="button" className="opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus:opacity-100 hover:text-danger"
                onClick={() => void run(async () => { await unwrap(api.DELETE("/notes/{note_id}", { params: { path: { note_id: n.id } } })); await reload(); })}>
                Delete
              </button>
            </p>
          </li>
        ))}
      </ul>
      <form onSubmit={submit} className="mt-3">
        <label htmlFor="note" className="sr-only">Add a note</label>
        <textarea id="note" ref={box} rows={2} maxLength={2000} placeholder="Add a note for your team"
          className="w-full resize-y rounded-ctl border border-line bg-surface px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
        <button type="submit" className={`${btn.ghost} mt-2`} disabled={busy}>Add note</button>
      </form>
      {error !== null && <div className="mt-2"><ErrorState error={error} /></div>}
    </section>
  );
}
