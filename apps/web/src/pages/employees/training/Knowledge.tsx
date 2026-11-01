import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../../lib/api";
import { type Item, LIMITS, MAX_ITEM, type Training, raw, useSuggestions } from "../../../lib/training";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { Confirm } from "../../../ui/Confirm";
import { ErrorState } from "../../../ui/states";

type Props = { employeeId: string; training: Training };
const DOC_TYPES = ".txt,.md,.csv,.pdf,image/png,image/jpeg,image/webp";
// Why a moment was flagged (app/calls/analysis.py Struggle.reason).
const REASON: Record<string, string> = {
  unanswered: "A caller asked something the employee couldn't answer.",
  conduct: "The employee said or did something it shouldn't have.",
};

/** Facts (what it knows) and rules (how it behaves), each list with its limit. */
export function Items({ employeeId, training }: Props) {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <List employeeId={employeeId} kind="fact" items={training.facts} title="Facts" hint="Prices, offers, timings. Newer than the script: a fact wins where they disagree." />
      <List employeeId={employeeId} kind="rule" items={training.rules} title="Rules" hint="How to behave. A rule beats the call flow, never the built-in conduct." />
    </div>
  );
}

function List({ employeeId, kind, items, title, hint }: { employeeId: string; kind: "fact" | "rule"; items: Item[]; title: string; hint: string }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const at = (id: string) => ({ params: { path: { employee_id: employeeId, item_id: id } } });
  const reload = () => qc.invalidateQueries({ queryKey: ["training", employeeId] });

  function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const text = String(new FormData(form).get("text")).trim();
    if (!text) return;
    void run(async () => {
      await unwrap(api.POST("/employees/{employee_id}/training/items", { params: { path: { employee_id: employeeId } }, body: { items: [{ kind, text, source: "text" }] } }));
      form.reset();
      await reload();
    });
  }
  return (
    <section aria-labelledby={`${kind}s`} className="rounded-card border border-line bg-surface p-6">
      <h2 id={`${kind}s`} className="eyebrow flex justify-between"><span>{title}</span><span className="num text-ink-muted">{items.length}/{LIMITS[kind]}</span></h2>
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
      <ul className="mt-3 divide-y divide-line">
        {items.map((it) => (
          <li key={it.id} className="py-2.5 text-sm">
            {editing === it.id ? (
              <form onSubmit={(e) => { e.preventDefault(); const text = String(new FormData(e.currentTarget).get("text")).trim(); void run(async () => { await unwrap(api.PATCH("/employees/{employee_id}/training/items/{item_id}", { ...at(it.id), body: { text } })); setEditing(null); await reload(); }); }}>
                <textarea name="text" aria-label={`Edit ${kind}`} defaultValue={it.text} maxLength={MAX_ITEM} rows={2} autoFocus className="w-full resize-y rounded-ctl border border-line-accent bg-bg px-2 py-1.5 text-ink-strong outline-none" />
                <div className="mt-1 flex gap-2"><button type="submit" className={btn.quiet} disabled={busy}>Save</button><button type="button" className={btn.quiet} onClick={() => setEditing(null)}>Cancel</button></div>
              </form>
            ) : (
              <div className="flex items-start justify-between gap-3">
                <p className="text-ink">{it.text}</p>
                <span className="flex shrink-0 gap-2 text-xs">
                  <button type="button" className="text-ink-muted hover:text-accent" onClick={() => setEditing(it.id)} aria-label={`Edit: ${it.text.slice(0, 40)}`}>Edit</button>
                  <button type="button" className="text-ink-muted hover:text-danger" aria-label={`Remove: ${it.text.slice(0, 40)}`}
                    onClick={() => void run(async () => { await unwrap(api.DELETE("/employees/{employee_id}/training/items/{item_id}", at(it.id))); await reload(); })}>Remove</button>
                </span>
              </div>
            )}
          </li>
        ))}
        {items.length === 0 && <li className="py-3 text-sm text-ink-muted">None yet.</li>}
      </ul>
      {items.length < LIMITS[kind] && (
        <form onSubmit={add} className="mt-3 flex gap-2">
          <label className="sr-only" htmlFor={`new-${kind}`}>New {kind}</label>
          <input id={`new-${kind}`} name="text" maxLength={MAX_ITEM} placeholder={kind === "fact" ? "Add a fact" : "Add a rule"} className="h-9 min-w-0 flex-1 rounded-ctl border border-line bg-bg px-3 text-sm text-ink-strong outline-none focus:border-accent" />
          <button type="submit" className={btn.ghost} disabled={busy}>Add</button>
        </form>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

/** Longer material (brochures, price sheets) the employee looks up only when a caller asks. */
export function Documents({ employeeId, training }: Props) {
  const qc = useQueryClient();
  const [question, setQuestion] = useState("");
  const [found, setFound] = useState<{ document: string; score: number; text: string }[] | null>(null);
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employeeId } } };
  const upload = (file: File) =>
    run(async () => {
      const type = file.type || (file.name.endsWith(".md") ? "text/markdown" : file.name.endsWith(".csv") ? "text/csv" : "text/plain");
      await unwrap(api.POST("/employees/{employee_id}/training/documents", { params: { path: { employee_id: employeeId }, query: { name: file.name } }, ...raw(file, type) }));
      await qc.invalidateQueries({ queryKey: ["training", employeeId] });
    });
  return (
    <section aria-labelledby="documents" className="rounded-card border border-line bg-surface p-6">
      <h2 id="documents" className="eyebrow flex justify-between"><span>Documents</span><span className="num text-ink-muted">{training.documents.length}/10</span></h2>
      <p className="mt-1 text-xs text-ink-muted">Text, Markdown, CSV, PDF or a photo, up to 60,000 characters each. The original file isn't kept.</p>
      <ul className="mt-3 divide-y divide-line">
        {training.documents.map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
            <span className="min-w-0 truncate text-ink">{d.name} <span className="num text-xs text-ink-muted">· {d.chars.toLocaleString("en-IN")} chars</span></span>
            <Confirm trigger={<button type="button" className="text-xs text-ink-muted hover:text-danger">Remove</button>} title={`Remove ${d.name}?`} body="The employee stops looking things up in it from the next call." action="Remove"
              onConfirm={() => void run(async () => { await unwrap(api.DELETE("/employees/{employee_id}/training/documents/{doc_id}", { params: { path: { employee_id: employeeId, doc_id: d.id } } })); await qc.invalidateQueries({ queryKey: ["training", employeeId] }); })} />
          </li>
        ))}
      </ul>
      {training.documents.length < 10 && (
        <label className={`${btn.ghost} mt-3 cursor-pointer`}>
          {busy ? "Reading…" : "Add a document"}
          <input type="file" accept={DOC_TYPES} className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
        </label>
      )}
      {training.documents.length > 0 && (
        <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); void run(async () => setFound(await unwrap(api.POST("/employees/{employee_id}/training/documents/search", { ...p, body: { question } })))); }}>
          <label className="sr-only" htmlFor="doc-q">Try a question</label>
          <input id="doc-q" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={300} placeholder="Try a caller's question" className="h-9 min-w-0 flex-1 rounded-ctl border border-line bg-bg px-3 text-sm text-ink-strong outline-none focus:border-accent" />
          <button type="submit" className={btn.quiet} disabled={!question.trim()}>Look up</button>
        </form>
      )}
      {found && (
        <ul className="mt-3 space-y-2 text-sm" aria-live="polite">
          {found.map((f, i) => <li key={i} className="rounded-ctl border border-line bg-bg p-3"><span className="eyebrow text-[10px] text-ink-muted">{f.document} · {Math.round(f.score * 100)}%</span><p className="mt-1 text-ink">{f.text}</p></li>)}
          {found.length === 0 && <li className="text-ink-muted">Nothing relevant enough: the employee would say it doesn't know.</li>}
        </ul>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

/** Moments real callers stumped the employee, with the caller's own words; nothing is taught until accepted. */
export function Suggestions({ employeeId }: { employeeId: string }) {
  const list = useSuggestions(employeeId);
  const qc = useQueryClient();
  const { error, run } = useAction();
  const at = (id: string) => ({ params: { path: { employee_id: employeeId, suggestion_id: id } } });
  const reload = () => qc.invalidateQueries({ queryKey: ["training", employeeId] }); // suggestions too
  if (!list.data?.length) return null;
  return (
    <section aria-labelledby="suggestions" className="rounded-card border border-line-accent bg-surface p-6">
      <h2 id="suggestions" className="eyebrow">From real calls · {list.data.length}</h2>
      <ul className="mt-3 space-y-3">
        {list.data.map((s) => (
          <li key={s.id} className="rounded-ctl border border-line bg-bg p-4 text-sm">
            <p className="text-ink-muted">{REASON[s.reason] ?? s.reason}</p>
            <blockquote className="mt-2 border-l-2 border-accent pl-3 text-ink">“{s.caller_quote}”</blockquote>
            {s.agent_quote && <blockquote className="mt-1 border-l-2 border-line pl-3 text-ink-muted">“{s.agent_quote}”</blockquote>}
            <form className="mt-3" onSubmit={(e) => { e.preventDefault(); const text = String(new FormData(e.currentTarget).get("text")).trim(); void run(async () => { await unwrap(api.POST("/employees/{employee_id}/training/suggestions/{suggestion_id}/accept", { ...at(s.id), body: { text: text || null } })); await reload(); }); }}>
              <label className="sr-only" htmlFor={`sug-${s.id}`}>What to teach</label>
              <textarea id={`sug-${s.id}`} name="text" rows={2} maxLength={MAX_ITEM} defaultValue={s.text} placeholder="Write the answer the employee should give" className="w-full resize-y rounded-ctl border border-line-accent bg-surface px-3 py-2 text-ink-strong outline-none focus:border-accent" />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button type="submit" className={btn.primary}>Teach this {s.kind}</button>
                <button type="button" className={btn.quiet} onClick={() => void run(async () => { await unwrap(api.POST("/employees/{employee_id}/training/suggestions/{suggestion_id}/dismiss", at(s.id))); await reload(); })}>Dismiss</button>
                {s.call_id && <Link to={`/calls/${s.call_id}`} className="text-xs text-ink-muted underline underline-offset-4">the call</Link>}
              </div>
            </form>
          </li>
        ))}
      </ul>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}
