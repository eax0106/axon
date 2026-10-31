import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../../lib/api";
import { type Dialer as Settings, fromClock, toClock, wait } from "../../../lib/instant";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { ErrorState } from "../../../ui/states";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const OUT_OF_WINDOW: Record<string, string> = {
  next_window: "Call when the window next opens",
  plus_3h: "Call 3 hours later (inside the window)",
  plus_6h: "Call 6 hours later (inside the window)",
  next_day: "Call the next day",
  hold: "Hold for me to call by hand",
};

/** When and how persistently new leads are called. The law's 6 AM–10 PM limit always applies. */
export function DialerForm({ employeeId, settings }: { employeeId: string; settings: Required<Settings> }) {
  const qc = useQueryClient();
  const [s, setS] = useState(settings);
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  const set = (patch: Partial<Settings>) => {
    setSaved(false);
    setS((x) => ({ ...x, ...patch }));
  };

  function save(e: FormEvent) {
    e.preventDefault();
    void run(async () => {
      await unwrap(api.PUT("/employees/{employee_id}/instant/dialer", { params: { path: { employee_id: employeeId } }, body: s }));
      setSaved(true);
      await qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });
  }
  const ladder = s.retry_ladder_min;
  return (
    <form onSubmit={save} className="rounded-card border border-line bg-surface p-6" aria-labelledby="dialer">
      <h2 id="dialer" className="eyebrow">Calling rules</h2>
      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        <label className="block">
          <span className="text-sm text-ink">Wait before calling</span>
          <span className="mt-1.5 flex h-11 items-center rounded-ctl border border-line-accent bg-bg px-3 focus-within:border-accent">
            <input type="number" min={0} max={3600} value={s.dial_delay_s} onChange={(e) => set({ dial_delay_s: Number(e.target.value) })} className="num w-full bg-transparent text-ink-strong outline-none" aria-label="Seconds before calling" />
            <span className="text-sm text-ink-muted">sec</span>
          </span>
        </label>
        <label className="block">
          <span className="text-sm text-ink">Calls from</span>
          <input type="time" min="06:00" max="22:00" step={300} value={toClock(s.window_start_min)} onChange={(e) => set({ window_start_min: fromClock(e.target.value) })} className="num mt-1.5 h-11 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong" />
        </label>
        <label className="block">
          <span className="text-sm text-ink">Until</span>
          <input type="time" min="06:00" max="22:00" step={300} value={toClock(s.window_end_min)} onChange={(e) => set({ window_end_min: fromClock(e.target.value) })} className="num mt-1.5 h-11 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong" />
        </label>
      </div>
      <p className="mt-2 text-xs text-ink-muted">Indian time. Never before 6 AM or after 10 PM, whatever is set here.</p>

      <fieldset className="mt-5">
        <legend className="text-sm text-ink">Days</legend>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {DAYS.map((d, i) => (
            <label key={d} className="cursor-pointer rounded-ctl border border-line px-3 py-1.5 text-sm text-ink-muted has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink-strong">
              <input type="checkbox" className="sr-only" checked={s.days.includes(i)} onChange={(e) => set({ days: e.target.checked ? [...s.days, i].sort() : s.days.filter((x) => x !== i) })} />
              {d}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="mt-5 block">
        <span className="text-sm text-ink">A lead that arrives outside these hours</span>
        <select value={s.out_of_window} onChange={(e) => set({ out_of_window: e.target.value as Settings["out_of_window"] })} className="mt-1.5 h-11 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong">
          {Object.entries(OUT_OF_WINDOW).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>

      <fieldset className="mt-5">
        <legend className="text-sm text-ink">If nobody answers, try again after</legend>
        <ol className="mt-2 flex flex-wrap items-center gap-2">
          {ladder.map((m, i) => (
            <li key={i} className="flex items-center gap-1 rounded-ctl border border-line bg-bg pl-2">
              <span className="num text-xs text-accent">{i + 2}</span>
              <input type="number" min={1} max={10080} value={m} aria-label={`Wait before attempt ${i + 2}, minutes`}
                onChange={(e) => set({ retry_ladder_min: ladder.map((x, j) => (j === i ? Number(e.target.value) : x)) })}
                className="num h-8 w-20 bg-transparent px-1 text-sm text-ink-strong outline-none" />
              <span className="text-xs text-ink-muted">min</span>
              <button type="button" aria-label={`Remove attempt ${i + 2}`} onClick={() => set({ retry_ladder_min: ladder.filter((_, j) => j !== i) })} className="px-2 text-ink-muted hover:text-danger">×</button>
            </li>
          ))}
          {ladder.length < 9 && (
            <li>
              <button type="button" className={btn.quiet} onClick={() => set({ retry_ladder_min: [...ladder, ladder.at(-1) ?? 60] })}>+ Add a retry</button>
            </li>
          )}
        </ol>
        <p className="mt-2 text-xs text-ink-muted">
          {ladder.length === 0 ? "One attempt only." : `${ladder.length + 1} attempts: ${ladder.map(wait).join(", then ")} apart.`}
        </p>
      </fieldset>

      <label className="mt-5 block max-w-xs">
        <span className="text-sm text-ink">Don't call the same number again within</span>
        <span className="mt-1.5 flex h-11 items-center rounded-ctl border border-line-accent bg-bg px-3 focus-within:border-accent">
          <input type="number" min={0} max={90} value={s.dedup_recent_days} onChange={(e) => set({ dedup_recent_days: Number(e.target.value) })} className="num w-full bg-transparent text-ink-strong outline-none" aria-label="Days to skip repeat leads" />
          <span className="text-sm text-ink-muted">days</span>
        </span>
      </label>

      {error !== null && <div className="mt-4"><ErrorState error={error} /></div>}
      <div className="mt-5 flex items-center gap-3">
        <button type="submit" className={btn.primary} disabled={busy}>{busy ? "Saving…" : "Save calling rules"}</button>
        {saved && <span role="status" className="text-sm text-accent">Saved. New leads follow these rules.</span>}
      </div>
    </form>
  );
}
