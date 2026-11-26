import { useState } from "react";

import { OUTCOME } from "../../lib/data";
import { type Settings, writes } from "../../lib/employees";
import { identifier, removeAt, replaceAt } from "../../lib/list";
import { btn } from "../../ui/buttons";
import { useDetail } from "./Detail";

type Own = NonNullable<Settings["outcomes"]>[number];
// What a custom outcome may count as in the figures (the API refuses do_not_call and no_conversation).
const COUNTS_AS: Own["counts_as"][] = ["interested", "not_interested", "callback_requested", "wrong_number", "other"];
const MAX = 8;
const input = "h-9 w-full rounded-ctl border border-line bg-surface px-3 text-sm text-ink-strong outline-none focus:border-accent";

/** The employee's own outcomes are settings, like the details to capture: they are read when a
 *  call is analysed, never heard by the caller, so they apply to the next call with no publish. */
export function Outcomes() {
  const { employee, write } = useDetail();
  const outcomes = employee.settings.outcomes ?? [];
  const save = (next: Own[]) => write.mutate(writes.settings({ ...employee.settings, outcomes: next }));
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const name = identifier(label);
  const problem = !name
    ? null
    : name in OUTCOME
      ? "That is one of the standard outcomes."
      : outcomes.some((o) => o.name === name)
        ? "This employee already has that outcome."
        : null;
  const add = () => {
    if (!name || problem || !description.trim()) return;
    save([...outcomes, { name, description: description.trim(), counts_as: "interested" }]);
    setLabel("");
    setDescription("");
  };

  return (
    <div>
      <p className="eyebrow">Your own outcomes</p>
      <p className="mt-1 text-xs text-ink-muted">
        Up to {MAX}. After each call one is picked when it fits better than a standard outcome. Each counts as a standard
        outcome in your figures. Applies at once.
      </p>
      <ul className="mt-3 space-y-2">
        {outcomes.map((o, i) => (
          <li key={o.name} className="rounded-card border border-line bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="num truncate text-xs text-ink-strong">{o.name}</span>
              <button type="button" aria-label={`Remove ${o.name}`} className="text-ink-muted hover:text-danger" onClick={() => save(removeAt(outcomes, i))}>
                ×
              </button>
            </div>
            <input
              aria-label={`When ${o.name} applies`}
              defaultValue={o.description}
              maxLength={200}
              onBlur={(e) => {
                const next = e.target.value.trim();
                if (!next) e.target.value = o.description;
                else if (next !== o.description) save(replaceAt(outcomes, i, { ...o, description: next }));
              }}
              className={`${input} mt-2`}
            />
            <label className="mt-2 flex items-center justify-between gap-2 text-xs text-ink-muted">
              Counts as
              <select
                value={o.counts_as}
                onChange={(e) => save(replaceAt(outcomes, i, { ...o, counts_as: e.target.value as Own["counts_as"] }))}
                className="h-8 rounded-ctl border border-line bg-surface px-2 text-sm text-ink"
              >
                {COUNTS_AS.map((k) => (
                  <option key={k} value={k}>
                    {OUTCOME[k]}
                  </option>
                ))}
              </select>
            </label>
          </li>
        ))}
      </ul>
      {outcomes.length < MAX && (
        <form
          className="mt-2 space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <input aria-label="New outcome name" placeholder="Name, e.g. Site visit booked" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} className={input} />
          <input
            aria-label="When the new outcome applies"
            placeholder="When it applies, e.g. the caller agreed a visit date"
            value={description}
            maxLength={200}
            onChange={(e) => setDescription(e.target.value)}
            className={input}
          />
          {problem && <p className="text-xs text-danger">{problem}</p>}
          <button type="submit" className={`${btn.ghost} w-full`} disabled={!name || Boolean(problem) || !description.trim()}>
            Add outcome
          </button>
        </form>
      )}
    </div>
  );
}
