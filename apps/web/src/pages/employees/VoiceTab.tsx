import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { LANGUAGES, type Language, type Settings, type Voice, useVoices, writes } from "../../lib/employees";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { useDetail } from "./Detail";

const TIERS = { value: "Value", standard: "Standard", premium: "Premium" } as const;
const AMBIENCE: Record<NonNullable<Settings["ambience"]>, string> = {
  none: "None",
  office: "Office",
  call_center: "Call center",
  restaurant: "Restaurant",
  quiet_room: "Quiet room",
  retail_store: "Retail store",
};

export default function VoiceTab() {
  const { employee, write } = useDetail();
  const voices = useVoices();
  const [tier, setTier] = useState<Voice["tier"] | "all">("all");
  const settings = employee.settings;
  const needs = [employee.language, ...employee.extra_languages];
  // Only voices that speak every language this employee speaks can be picked (the API's rule).
  const fits = (voices.data ?? []).filter((v) => needs.every((l) => v.languages.includes(l)));
  const shown = fits.filter((v) => tier === "all" || v.tier === tier);
  const saveSettings = (patch: Partial<Settings>) => write.mutate(writes.settings({ ...settings, ...patch }));

  return (
    <div className="grid gap-10 lg:grid-cols-[1fr_300px]">
      <section aria-labelledby="voices">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 id="voices" className="eyebrow">Voice</h2>
          <div role="radiogroup" aria-label="Voice tier" className="flex gap-1 rounded-ctl border border-line p-1">
            {(["all", "value", "standard", "premium"] as const).map((t) => (
              <button
                key={t}
                type="button"
                role="radio"
                aria-checked={tier === t}
                onClick={() => setTier(t)}
                className="rounded-tag px-2.5 py-1 text-xs text-ink-muted transition-colors duration-150 aria-checked:bg-accent-soft aria-checked:text-ink-strong"
              >
                {t === "all" ? "All" : TIERS[t]}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-1 text-xs text-ink-muted">Changing the voice applies to the next call at once.</p>
        {voices.error ? (
          <div className="mt-4">
            <ErrorState error={voices.error} retry={() => void voices.refetch()} />
          </div>
        ) : !voices.data ? (
          <Skeleton className="mt-4 h-40 rounded-card" />
        ) : (
          <div className="mt-4 grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="Voices">
            {shown.map((v) => (
              <VoiceRow
                key={v.id}
                voice={v}
                language={employee.language}
                chosen={employee.voice?.id === v.id}
                onChoose={() => write.mutate(writes.update({ voice_id: v.id }))}
              />
            ))}
            {shown.length === 0 && (
              <p className="text-sm text-ink-muted">
                No {tier === "all" ? "" : `${TIERS[tier]} `}voice speaks {needs.map((l) => LANGUAGES[l as Language] ?? l).join(" and ")} yet.
              </p>
            )}
          </div>
        )}
      </section>

      <aside className="space-y-8">
        <Slider
          label="Speaking speed"
          value={settings.tts_speed ?? 1}
          min={0.5}
          max={2}
          step={0.05}
          format={(v) => `${v.toFixed(2)}×`}
          onCommit={(v) => saveSettings({ tts_speed: v })}
        />
        <label className="block">
          <span className="eyebrow">Background sound</span>
          <select
            value={settings.ambience ?? "none"}
            onChange={(e) => saveSettings({ ambience: e.target.value as Settings["ambience"] })}
            className="mt-3 h-10 w-full rounded-ctl border border-line-accent bg-surface px-3 text-ink-strong outline-none focus:border-accent"
          >
            {Object.entries(AMBIENCE).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {settings.ambience !== "none" && (
          <Slider
            label="Background volume"
            value={settings.ambience_volume ?? 0.3}
            min={0}
            max={1}
            step={0.05}
            format={(v) => `${Math.round(v * 100)}%`}
            onCommit={(v) => saveSettings({ ambience_volume: v })}
          />
        )}
        {write.error && <p className="text-sm text-danger">{write.error.message}</p>}
      </aside>
    </div>
  );
}

function VoiceRow(props: { voice: Voice; language: string; chosen: boolean; onChoose: () => void }) {
  const v = props.voice;
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<unknown>(null);

  /** A WAV sample made by the voice's own vendor, played from a blob. */
  async function preview() {
    setPlaying(true);
    setError(null);
    try {
      const wav = await unwrap<Blob>(
        api.POST("/voices/{voice_id}/preview", {
          params: { path: { voice_id: v.id }, query: { language: props.language } },
          parseAs: "blob",
        }),
      );
      const audio = new Audio(URL.createObjectURL(wav));
      audio.onended = () => setPlaying(false);
      await audio.play();
    } catch (err) {
      setError(err);
      setPlaying(false);
    }
  }

  return (
    <div
      className={`rounded-card border p-4 transition-colors duration-150 ${
        props.chosen ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-line-accent"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <button type="button" role="radio" aria-checked={props.chosen} onClick={props.onChoose} className="min-w-0 text-left">
          <span className="block font-medium text-ink-strong">{v.name}</span>
          <span className="block text-xs text-ink-muted">
            {TIERS[v.tier]} · {v.tone_tags.slice(0, 3).join(", ") || v.provider.charAt(0).toUpperCase() + v.provider.slice(1)}
          </span>
        </button>
        <button type="button" className={btn.quiet} onClick={() => void preview()} disabled={playing} aria-label={`Play a sample of ${v.name}`}>
          {playing ? "Playing…" : "▶ Listen"}
        </button>
      </div>
      {error !== null && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
    </div>
  );
}

/** A range input that saves when released, not on every pixel of the drag. */
function Slider(props: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (v: number) => string;
  onCommit: (v: number) => void;
}) {
  const [value, setValue] = useState(props.value);
  return (
    <label className="block">
      <span className="flex justify-between">
        <span className="eyebrow">{props.label}</span>
        <span className="num text-sm text-ink">{props.format(value)}</span>
      </span>
      <input
        type="range"
        min={props.min}
        max={props.max}
        step={props.step}
        value={value}
        onChange={(e) => setValue(Number(e.target.value))}
        onPointerUp={() => props.onCommit(value)}
        onKeyUp={() => props.onCommit(value)}
        className="mt-3 w-full accent-[var(--accent)]"
      />
    </label>
  );
}
