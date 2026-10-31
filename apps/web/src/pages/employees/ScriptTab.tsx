import { useEffect, useRef, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Script, type Section, type Settings, writes } from "../../lib/employees";
import { useAction } from "../../lib/useAction";
import { identifier, move, removeAt, replaceAt } from "../../lib/list";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";
import { useDetail } from "./Detail";

/** The parts of the script this editor owns. Actions and the result webhook are left out, so the
 *  API keeps them as they are (they have their own tabs, F10). */
type Editable = Omit<Script, "actions" | "result_webhook">;
const editable = ({ actions: _a, result_webhook: _r, ...rest }: Script): Editable => rest;

const STRICTNESS = ["Loose", "Relaxed", "Balanced", "Firm", "Word for word"];

export default function ScriptTab() {
  const { employee, draftKey } = useDetail();
  // Remount the editor when the draft is replaced from outside (discard, restore).
  return <Editor key={`${employee.id}:${draftKey}`} />;
}

function Editor() {
  const { employee, write } = useDetail();
  const [script, setScript] = useState<Editable>(() => editable(employee.script));
  const [saved, setSaved] = useState<"saved" | "saving" | "failed">("saved");
  const typed = useRef(false);
  // The mutation object changes on every status update; the save must follow the script only.
  const writeRef = useRef(write);
  writeRef.current = write;

  // Autosave the draft 700 ms after the last keystroke; it reaches calls only after "Apply".
  useEffect(() => {
    if (!typed.current) return;
    setSaved("saving");
    const t = setTimeout(
      () =>
        writeRef.current.mutate(writes.script(script), {
          onSuccess: () => setSaved("saved"),
          onError: () => setSaved("failed"),
        }),
      700,
    );
    return () => clearTimeout(t);
  }, [script]);

  const set = (patch: Partial<Editable>) => {
    typed.current = true;
    setScript((s) => ({ ...s, ...patch }));
  };
  const sections = script.sections ?? [];
  const faq = script.faq ?? [];

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_280px]">
      <div className="min-w-0 space-y-10">
        <p className="text-sm text-ink-muted" aria-live="polite">
          {saved === "saving" ? "Saving draft…" : saved === "failed" ? (
            <span className="text-danger">Couldn't save: {write.error?.message}</span>
          ) : (
            "Draft saved. Changes reach calls when you apply them."
          )}
        </p>

        <Text label="Welcome line" hint="The first thing callers hear after the recording notice." value={script.welcome_message ?? ""} max={500} rows={2} onChange={(v) => set({ welcome_message: v })} />

        <section aria-labelledby="flow">
          <div className="flex items-end justify-between">
            <h2 id="flow" className="eyebrow">Call flow</h2>
            <button
              type="button"
              className={btn.quiet}
              disabled={sections.length >= 20}
              onClick={() => set({ sections: [...sections, { title: "New step", body: "" }] })}
            >
              + Add a step
            </button>
          </div>
          <ol className="mt-3 space-y-3">
            {sections.map((s, i) => (
              <SectionCard
                key={s.id ?? i}
                n={i + 1}
                section={s}
                first={i === 0}
                last={i === sections.length - 1}
                onChange={(next) => set({ sections: replaceAt(sections, i, next) })}
                onMove={(by) => set({ sections: move(sections, i, by) })}
                onRemove={() => set({ sections: removeAt(sections, i) })}
              />
            ))}
            {sections.length === 0 && <li className="rounded-card border border-dashed border-line p-6 text-sm text-ink-muted">No steps yet. Add the stages of a good call: greet, qualify, handle doubts, close.</li>}
          </ol>
        </section>

        <Text label="When to end the call" hint="Conduct rules: when to wrap up, transfer or stop." value={script.end_rules ?? ""} max={2000} rows={3} onChange={(v) => set({ end_rules: v })} />
        <Text label="About your business" hint="Facts the employee may use: prices, hours, address, offers." value={script.agent_information ?? ""} max={4000} rows={5} onChange={(v) => set({ agent_information: v })} />

        <section aria-labelledby="faq">
          <div className="flex items-end justify-between">
            <h2 id="faq" className="eyebrow">Questions callers ask</h2>
            <button type="button" className={btn.quiet} disabled={faq.length >= 50} onClick={() => set({ faq: [...faq, { question: "", answer: "" }] })}>
              + Add a question
            </button>
          </div>
          <p className="mt-1 text-xs text-ink-muted">Always part of the script; it can be empty but not removed.</p>
          <ul className="mt-3 space-y-3">
            {faq.map((f, i) => (
              <li key={i} className="rounded-card border border-line bg-surface p-4">
                <input aria-label={`Question ${i + 1}`} value={f.question} maxLength={300} placeholder="Question" onChange={(e) => set({ faq: replaceAt(faq, i, { ...f, question: e.target.value }) })} className="w-full bg-transparent font-medium text-ink-strong outline-none placeholder:text-ink-muted" />
                <textarea aria-label={`Answer ${i + 1}`} value={f.answer} maxLength={1500} rows={2} placeholder="Answer" onChange={(e) => set({ faq: replaceAt(faq, i, { ...f, answer: e.target.value }) })} className="mt-2 w-full resize-y bg-transparent text-sm text-ink outline-none placeholder:text-ink-muted" />
                <button type="button" className="text-xs text-ink-muted hover:text-danger" onClick={() => set({ faq: removeAt(faq, i) })}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <aside className="space-y-8">
        <fieldset>
          <legend className="eyebrow">How closely to follow the script</legend>
          <div className="mt-3 grid grid-cols-5 gap-1 rounded-ctl border border-line p-1">
            {STRICTNESS.map((label, i) => (
              <label key={label} title={label} className="cursor-pointer rounded-tag py-1.5 text-center text-sm text-ink-muted transition-colors duration-150 has-[:checked]:bg-accent-soft has-[:checked]:text-ink-strong">
                <input type="radio" name="strictness" className="sr-only" checked={(script.strictness ?? 3) === i + 1} onChange={() => set({ strictness: i + 1 })} aria-label={`${i + 1}: ${label}`} />
                {i + 1}
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-ink-muted">{STRICTNESS[(script.strictness ?? 3) - 1]}</p>
        </fieldset>
        <Names
          label="Details you send in"
          hint="Filled from your lead form or list before the call, e.g. name, project."
          names={script.pre_call_variables ?? []}
          max={30}
          onChange={(v) => set({ pre_call_variables: v })}
        />
        <Capture />
        <AiEdit onProposal={(next) => set(editable(next))} />
      </aside>
    </div>
  );
}

function Text(props: { label: string; hint: string; value: string; max: number; rows: number; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="eyebrow">{props.label}</span>
      <span className="mt-1 block text-xs text-ink-muted">{props.hint}</span>
      <textarea value={props.value} maxLength={props.max} rows={props.rows} onChange={(e) => props.onChange(e.target.value)} className="mt-3 w-full resize-y rounded-ctl border border-line-accent bg-surface px-3.5 py-2.5 text-ink-strong outline-none focus:border-accent" />
    </label>
  );
}

function SectionCard(props: {
  n: number;
  section: Section;
  first: boolean;
  last: boolean;
  onChange: (s: Section) => void;
  onMove: (by: -1 | 1) => void;
  onRemove: () => void;
}) {
  const s = props.section;
  return (
    <li className="rounded-card border border-line bg-surface p-4 transition-colors duration-150 focus-within:border-line-accent">
      <div className="flex items-center gap-3">
        <span className="num text-xs text-accent">{String(props.n).padStart(2, "0")}</span>
        <input aria-label={`Step ${props.n} title`} value={s.title} maxLength={120} onChange={(e) => props.onChange({ ...s, title: e.target.value })} className="min-w-0 flex-1 bg-transparent font-medium text-ink-strong outline-none" />
        <span className="flex shrink-0">
          <button type="button" aria-label={`Move step ${props.n} up`} disabled={props.first} onClick={() => props.onMove(-1)} className={btn.quiet}>↑</button>
          <button type="button" aria-label={`Move step ${props.n} down`} disabled={props.last} onClick={() => props.onMove(1)} className={btn.quiet}>↓</button>
          <button type="button" aria-label={`Delete step ${props.n}`} onClick={props.onRemove} className={`${btn.quiet} hover:text-danger`}>✕</button>
        </span>
      </div>
      <textarea aria-label={`Step ${props.n} instructions`} value={s.body} maxLength={4000} rows={3} onChange={(e) => props.onChange({ ...s, body: e.target.value })} className="mt-2 w-full resize-y bg-transparent text-sm text-ink outline-none" />
    </li>
  );
}

/** A list of identifiers typed as plain labels ("Budget range" becomes budget_range). */
function Names(props: { label: string; hint: string; names: string[]; max: number; onChange: (v: string[]) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    const name = identifier(text);
    if (name && !props.names.includes(name) && props.names.length < props.max) props.onChange([...props.names, name]);
    setText("");
  };
  return (
    <div>
      <p className="eyebrow">{props.label}</p>
      <p className="mt-1 text-xs text-ink-muted">{props.hint}</p>
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {props.names.map((n) => (
          <li key={n} className="num inline-flex items-center gap-1 rounded-full border border-line-accent px-2.5 py-0.5 text-xs text-ink">
            {n}
            <button type="button" aria-label={`Remove ${n}`} className="text-ink-muted hover:text-danger" onClick={() => props.onChange(props.names.filter((x) => x !== n))}>×</button>
          </li>
        ))}
      </ul>
      <input
        aria-label={`Add to ${props.label}`}
        value={text}
        placeholder="Type and press Enter"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }}
        onBlur={add}
        className="mt-2 h-9 w-full rounded-ctl border border-line bg-surface px-3 text-sm text-ink-strong outline-none focus:border-accent"
      />
    </div>
  );
}

/** Captured fields are settings: they apply to calls at once, with no publish step. */
function Capture() {
  const { employee, write } = useDetail();
  const capture = employee.settings.capture ?? [];
  const save = (next: Settings["capture"]) => write.mutate(writes.settings({ ...employee.settings, capture: next }));
  return (
    <div>
      <Names
        label="Details to capture"
        hint="Pulled from each call into the lead. Applies at once."
        names={capture.map((c) => c.name)}
        max={20}
        onChange={(names) =>
          save(names.map((name) => capture.find((c) => c.name === name) ?? { name, description: name.replaceAll("_", " ") }))
        }
      />
    </div>
  );
}

/** Ask the AI for a change; its proposal lands in the editor as a draft the owner can still edit. */
function AiEdit({ onProposal }: { onProposal: (s: Script) => void }) {
  const { employee } = useDetail();
  const [instruction, setInstruction] = useState("");
  const { busy, error, run } = useAction();
  const ask = () =>
    run(async () => {
      onProposal(
        await unwrap(
          api.POST("/employees/{employee_id}/ai/edit-flow", {
            params: { path: { employee_id: employee.id } },
            body: { instruction },
          }),
        ),
      );
      setInstruction("");
    });
  return (
    <div>
      <p className="eyebrow">Change it with AI</p>
      <textarea
        aria-label="What to change"
        rows={3}
        maxLength={2000}
        value={instruction}
        onChange={(e) => setInstruction(e.target.value)}
        placeholder="Ask for the site-visit day before ending the call."
        className="mt-3 w-full resize-y rounded-ctl border border-line bg-surface px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent"
      />
      <button type="button" className={`${btn.ghost} mt-2 w-full`} disabled={busy || instruction.trim().length < 3} onClick={() => void ask()}>
        {busy ? "Rewriting…" : "Rewrite the draft"}
      </button>
      {error !== null && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
    </div>
  );
}
