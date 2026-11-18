import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { queryClient } from "../../lib/queries";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";
import { Section, input, useWrite } from "./parts";

const LANGS = ["te", "hi", "en"] as const;

/** The voice catalogue owners pick from. A voice in use can't be removed (the API refuses). */
export function Voices() {
  const voices = useQuery({ queryKey: ["voices", "all"], queryFn: () => unwrap(api.GET("/voices")) });
  const { busy, write, outcome } = useWrite();
  const reload = () => queryClient.invalidateQueries({ queryKey: ["voices"] });
  function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    const scores = Object.fromEntries(LANGS.map((l) => [l, String(f.get(`score_${l}`)).trim()]).filter(([, v]) => v !== "").map(([l, v]) => [l, Number(v)]));
    const name = String(f.get("name")).trim();
    write(async () => {
      await unwrap(api.POST("/admin/voices", { body: {
        provider: String(f.get("provider")), provider_voice_id: String(f.get("voice_id")).trim(), name,
        native_language: String(f.get("native")) as (typeof LANGS)[number], accent: String(f.get("accent")).trim() || null,
        tone_tags: String(f.get("tags")).split(",").map((t) => t.trim()).filter(Boolean), language_scores: scores,
      } }));
      form.reset();
      await reload();
      return `Added ${name}; owners can pick it now.`;
    });
  }
  return (
    <div className="space-y-6">
      <Section id="catalogue" title={`Catalogue · ${voices.data?.length ?? "…"}`}>
        {voices.error ? <ErrorState error={voices.error} /> : !voices.data ? <Skeleton className="h-40" /> : (
          <ul className="divide-y divide-line text-sm">
            {voices.data.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                <span className="min-w-0"><span className="text-ink-strong">{v.name}</span><span className="ml-2 text-xs text-ink-muted">{v.provider} · {v.tier} · {v.languages.join(", ")}{v.accent && ` · ${v.accent}`}{v.tone_tags.length > 0 && ` · ${v.tone_tags.join(", ")}`}</span></span>
                <Confirm danger trigger={<button type="button" className="text-xs text-ink-muted hover:text-danger" aria-label={`Remove ${v.name}`}>Remove</button>} title={`Remove ${v.name}?`} body="Owners can no longer pick it. If an employee uses it, the API refuses." action="Remove"
                  onConfirm={() => write(async () => { await unwrap(api.DELETE("/admin/voices/{voice_id}", { params: { path: { voice_id: v.id } } })); await reload(); return `Removed ${v.name}.`; })} />
              </li>
            ))}
          </ul>
        )}
        {outcome}
      </Section>
      <CartesiaLibrary />
      <Section id="add-voice" title="Add a voice">
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-3">
          <select name="provider" aria-label="Vendor (sets the tier)" className={input}><option value="sarvam">sarvam (value)</option><option value="smallest">smallest (standard)</option><option value="cartesia">cartesia (premium)</option></select>
          <input name="voice_id" aria-label="Vendor's voice id" required maxLength={200} placeholder="Vendor's voice id" className={input} />
          <input name="name" aria-label="Name" required maxLength={100} placeholder="Name owners see" className={input} />
          <select name="native" aria-label="Native language" className={input}>{LANGS.map((l) => <option key={l} value={l}>native {l}</option>)}</select>
          <input name="accent" aria-label="Accent (optional)" maxLength={50} placeholder="Accent (optional)" className={input} />
          <input name="tags" aria-label="Tone tags, comma-separated" placeholder="warm, calm" className={input} />
          {LANGS.map((l) => <input key={l} name={`score_${l}`} aria-label={`How well it speaks ${l}, 0 to 1`} inputMode="decimal" placeholder={`${l} score 0–1`} className={input} />)}
          <button type="submit" className={`${btn.primary} sm:col-span-3 sm:w-fit`} disabled={busy}>Add voice</button>
        </form>
      </Section>
    </div>
  );
}

/** Cartesia's public Premium voices for one language; Add puts one in the catalogue. */
function CartesiaLibrary() {
  const [language, setLanguage] = useState<(typeof LANGS)[number]>("te");
  const library = useQuery({
    queryKey: ["admin", "cartesia-library", language],
    queryFn: () => unwrap(api.GET("/admin/voices/library/cartesia", { params: { query: { language } } })),
  });
  const { busy, write, outcome } = useWrite();
  type Row = NonNullable<typeof library.data>[number];
  const add = (v: Row) =>
    write(async () => {
      await unwrap(api.POST("/admin/voices", { body: {
        provider: "cartesia", provider_voice_id: v.provider_voice_id, name: v.name.slice(0, 100), native_language: language,
        accent: v.accent?.slice(0, 50) ?? null, tone_tags: v.gender ? [v.gender] : [], language_scores: { [language]: 0.7 },
      } }));
      await queryClient.invalidateQueries({ queryKey: ["voices"] });
      await library.refetch();
      return `Added ${v.name} (Premium, ${language}); owners can pick it now.`;
    });
  return (
    <Section id="cartesia-library" title={`Cartesia library · Premium · ${library.data?.length ?? "…"}`}>
      <select aria-label="Language" value={language} onChange={(e) => setLanguage(e.target.value as (typeof LANGS)[number])} className={input}>
        {LANGS.map((l) => <option key={l} value={l}>{l === "te" ? "Telugu" : l === "hi" ? "Hindi" : "English"}</option>)}
      </select>
      {library.error ? <div className="mt-3"><ErrorState error={library.error} /></div> : !library.data ? <Skeleton className="mt-3 h-40" /> : (
        <ul className="mt-3 max-h-[28rem] divide-y divide-line overflow-y-auto text-sm">
          {library.data.map((v) => (
            <li key={v.provider_voice_id} className="flex items-start justify-between gap-3 py-2">
              <span className="min-w-0">
                <span className="text-ink-strong">{v.name}</span>
                <span className="ml-2 text-xs text-ink-muted">{[v.gender, v.accent].filter(Boolean).join(" · ")}</span>
                <span className="block text-xs text-ink-muted">{v.description}</span>
              </span>
              {v.added ? <span className="shrink-0 text-xs text-accent">In catalogue</span> : <button type="button" className={`${btn.quiet} shrink-0`} disabled={busy} onClick={() => add(v)}>Add</button>}
            </li>
          ))}
          {library.data.length === 0 && <li className="py-4 text-center text-ink-muted">Cartesia lists no voices for this language.</li>}
        </ul>
      )}
      {outcome}
    </Section>
  );
}
