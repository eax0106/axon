import { useState } from "react";

import { LANGUAGES, type Language, type Settings, writes } from "../../lib/employees";
import { removeAt } from "../../lib/list";
import { btn } from "../../ui/buttons";
import { useDetail } from "./Detail";

type Entry = NonNullable<Settings["pronunciations"]>[number];
const MAX = 100;
const input = "h-9 w-full rounded-ctl border border-line bg-surface px-3 text-sm text-ink-strong outline-none focus:border-accent";

/** Words the voice says wrong, and how to say them, per language. A delivery setting like the
 *  speed: it applies to the next call with no publish, and the call transcript keeps the word. */
export function Pronunciations() {
  const { employee, write } = useDetail();
  const entries = employee.settings.pronunciations ?? [];
  // English is always open to a caller, so it can always have entries.
  const languages = [...new Set([employee.language, ...employee.extra_languages, "en"])] as Language[];
  const save = (next: Entry[]) => write.mutate(writes.settings({ ...employee.settings, pronunciations: next }));
  const [language, setLanguage] = useState<Language>(languages[0] ?? "en");
  const [word, setWord] = useState("");
  const [say, setSay] = useState("");
  const taken = entries.some((e) => e.language === language && e.word.toLowerCase() === word.trim().toLowerCase());
  const add = () => {
    if (!word.trim() || !say.trim() || taken) return;
    save([...entries, { language, word: word.trim(), say: say.trim() }]);
    setWord("");
    setSay("");
  };

  return (
    <section aria-labelledby="pronunciations">
      <h2 id="pronunciations" className="eyebrow">
        Pronunciation
      </h2>
      <p className="mt-1 text-xs text-ink-muted">
        Words the voice reads wrong, such as your brand, a doctor's name or an area. Write how it should sound, in the
        language's own script if you can. Only the voice changes; transcripts keep your word. Applies to the next call.
      </p>
      {entries.length > 0 && (
        <ul className="mt-3 divide-y divide-line rounded-card border border-line bg-surface">
          {entries.map((e, i) => (
            <li key={`${e.language}:${e.word}`} className="flex items-center gap-3 px-3 py-2 text-sm">
              <span className="w-16 shrink-0 text-xs text-ink-muted">{LANGUAGES[e.language]}</span>
              <span className="min-w-0 flex-1 truncate text-ink-strong">{e.word}</span>
              <span aria-hidden className="text-ink-muted">
                →
              </span>
              <span className="min-w-0 flex-1 truncate text-ink">{e.say}</span>
              <button type="button" aria-label={`Remove ${e.word}`} className="text-ink-muted hover:text-danger" onClick={() => save(removeAt(entries, i))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      {entries.length < MAX && (
        <form
          className="mt-3 grid gap-2 sm:grid-cols-[8rem_1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <select
            aria-label="Language"
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
            className="h-9 rounded-ctl border border-line bg-surface px-2 text-sm text-ink"
          >
            {languages.map((l) => (
              <option key={l} value={l}>
                {LANGUAGES[l]}
              </option>
            ))}
          </select>
          <input aria-label="Word" placeholder="Word, e.g. Skyline" value={word} maxLength={64} onChange={(e) => setWord(e.target.value)} className={input} />
          <input aria-label="Say it like" placeholder="Say it like, e.g. స్కై లైన్" value={say} maxLength={120} onChange={(e) => setSay(e.target.value)} className={input} />
          <button type="submit" className={btn.ghost} disabled={!word.trim() || !say.trim() || taken}>
            Add
          </button>
          {taken && <p className="text-xs text-danger sm:col-span-4">This word is already listed for {LANGUAGES[language]}.</p>}
        </form>
      )}
    </section>
  );
}
