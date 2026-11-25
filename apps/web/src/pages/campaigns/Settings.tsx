import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Campaign, type CampaignSettings, MAX_LADDER_STEPS, type RetryStep, retryWaits, stepLabel, useCampaignAction } from "../../lib/campaigns";
import { fromClock, toClock } from "../../lib/instant";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const inline = "num h-10 rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong outline-none focus:border-accent";
const input = "num mt-1.5 h-10 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong outline-none focus:border-accent";

/** How the list is worked: hours (9 AM–9 PM at most), pace, retries, repeats and repeats across campaigns.
 * While it runs, the hours, days, holidays, retries and pace can change; the rest waits for a pause. */
export function CampaignSettingsForm({ campaign, editable, running }: { campaign: Campaign; editable: boolean; running: boolean }) {
  const [s, setS] = useState(campaign.settings as CampaignSettings);
  const [holiday, setHoliday] = useState("");
  const [saved, setSaved] = useState(false);
  const action = useCampaignAction(campaign.id);
  const set = (patch: Partial<CampaignSettings>) => {
    setSaved(false);
    setS((x) => ({ ...x, ...patch }));
  };
  const save = () =>
    action.mutate(async () => {
      await unwrap(api.PATCH("/campaigns/{campaign_id}", { params: { path: { campaign_id: campaign.id } }, body: { settings: s } }));
      setSaved(true);
    });

  return (
    <fieldset disabled={!editable && !running} className="rounded-card border border-line bg-surface p-6 disabled:opacity-70">
      <legend className="sr-only">Campaign settings</legend>
      {running ? (
        <p className="mb-4 text-sm text-ink-muted">The campaign is calling. Changes to the hours, days, holidays, retries and calls at once apply from the next call; pause it to change the rest.</p>
      ) : (
        !editable && <p className="mb-4 text-sm text-ink-muted">A finished campaign's settings are fixed.</p>
      )}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block"><span className="text-sm text-ink">Calls from</span>
          <input type="time" min="09:00" max="21:00" step={300} value={toClock(s.window_start_min)} onChange={(e) => set({ window_start_min: fromClock(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Until</span>
          <input type="time" min="09:00" max="21:00" step={300} value={toClock(s.window_end_min)} onChange={(e) => set({ window_end_min: fromClock(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Calls at once</span>
          <input type="number" min={1} max={20} value={s.concurrency} onChange={(e) => set({ concurrency: Number(e.target.value) })} className={input} /></label>
        <label className="block has-[:disabled]:opacity-60"><span className="text-sm text-ink">Skip numbers another campaign called in</span>
          <span className="relative block"><input type="number" min={0} max={90} disabled={running} value={s.dedupe_days} onChange={(e) => set({ dedupe_days: Number(e.target.value) })} className={input} />
            <span className="pointer-events-none absolute top-1/2 right-3 translate-y-[-25%] text-xs text-ink-muted">days</span></span></label>
      </div>
      <p className="mt-2 text-xs text-ink-muted">Indian time. Bulk calls are never placed before 9 AM or after 9 PM.</p>

      <fieldset className="mt-5"><legend className="text-sm text-ink">Days</legend>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {DAYS.map((d, i) => (
            <label key={d} className="cursor-pointer rounded-ctl border border-line px-3 py-1.5 text-sm text-ink-muted has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink-strong">
              <input type="checkbox" className="sr-only" checked={s.days.includes(i)} onChange={(e) => set({ days: e.target.checked ? [...s.days, i].sort() : s.days.filter((x) => x !== i) })} />{d}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="mt-5 flex flex-wrap items-end gap-2">
        <label className="block"><span className="text-sm text-ink">Holidays (no calls)</span>
          <input type="date" value={holiday} onChange={(e) => setHoliday(e.target.value)} className={`${input} w-44`} /></label>
        <button type="button" className={btn.quiet} disabled={!holiday} onClick={() => { set({ holidays: [...new Set([...s.holidays, holiday])].sort() }); setHoliday(""); }}>Add</button>
        <ul className="flex flex-wrap gap-1.5">
          {s.holidays.map((h) => (
            <li key={h} className="num inline-flex items-center gap-1 rounded-full border border-line-accent px-2.5 py-0.5 text-xs text-ink">{h}
              <button type="button" aria-label={`Remove holiday ${h}`} className="text-ink-muted hover:text-danger" onClick={() => set({ holidays: s.holidays.filter((x) => x !== h) })}>×</button></li>
          ))}
        </ul>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block"><span className="text-sm text-ink">Retries if no answer</span>
          <input type="number" min={0} max={9} value={s.retries} onChange={(e) => set({ retries: Number(e.target.value) })} className={input} /></label>
        <label className="block has-[:disabled]:opacity-60"><span className="text-sm text-ink">Repeat</span>
          <select disabled={running} value={s.repeat} onChange={(e) => set({ repeat: e.target.value as CampaignSettings["repeat"] })} className={input}>
            <option value="none">Run once</option><option value="daily">Every day</option><option value="weekly">Every week</option></select></label>
      </div>

      <RetryLadder ladder={s.retry_ladder} retries={s.retries} onChange={(retry_ladder) => set({ retry_ladder })} />

      <label className="mt-5 flex items-start gap-3 text-sm has-[:disabled]:opacity-60">
        <input type="checkbox" disabled={running} checked={s.skip_dnc} onChange={(e) => set({ skip_dnc: e.target.checked })} className="mt-0.5 accent-[var(--accent)]" />
        <span><span className="text-ink">Skip numbers on my do-not-call list</span>
          <span className="block text-xs text-ink-muted">Anyone who asked not to be called is always skipped, whatever this says.</span></span>
      </label>

      {action.error && <div className="mt-4"><ErrorState error={action.error} /></div>}
      <div className="mt-5 flex items-center gap-3">
        <button type="button" className={btn.primary} onClick={save} disabled={action.isPending}>Save settings</button>
        {saved && <span role="status" className="text-sm text-accent">{running ? "Saved. It applies from the next call." : "Saved."}</span>}
      </div>
    </fieldset>
  );
}

/** The wait before each retry: minutes inside the day's hours, or the next open day. Up to five steps; the last one repeats. */
function RetryLadder({ ladder, retries, onChange }: { ladder: RetryStep[]; retries: number; onChange: (l: RetryStep[]) => void }) {
  const put = (i: number, step: RetryStep) => onChange(ladder.map((x, j) => (j === i ? step : x)));
  const waits = retryWaits(retries, ladder);
  return (
    <fieldset className="mt-5"><legend className="text-sm text-ink">Wait before each retry</legend>
      <ol className="mt-2 space-y-2">
        {ladder.map((step, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="num w-14 text-ink-muted">Step {i + 1}</span>
            <select aria-label={`Step ${i + 1} kind`} value={step === "next_day" ? "next_day" : "minutes"} onChange={(e) => put(i, e.target.value === "next_day" ? "next_day" : 60)} className={`${inline} w-44`}>
              <option value="minutes">After a wait</option><option value="next_day">The next open day</option></select>
            {step !== "next_day" && (
              <label className="flex items-center gap-2"><input type="number" aria-label={`Step ${i + 1} minutes`} min={1} max={1440} value={step} onChange={(e) => put(i, Number(e.target.value))} className={`${inline} w-24`} />
                <span className="text-xs text-ink-muted">minutes</span></label>
            )}
            {ladder.length > 1 && <button type="button" aria-label={`Remove step ${i + 1}`} className="text-ink-muted hover:text-danger" onClick={() => onChange(ladder.filter((_, j) => j !== i))}>×</button>}
          </li>
        ))}
      </ol>
      {ladder.length < MAX_LADDER_STEPS && <button type="button" className={`${btn.quiet} mt-2`} onClick={() => onChange([...ladder, ladder[ladder.length - 1] ?? 60])}>Add a step</button>}
      <p className="mt-2 text-xs text-ink-muted">
        {waits.length === 0 ? "No retries: each number is called once." : `Retries wait ${waits.map(stepLabel).join(", then ")}.`} When there are more retries than steps, the last step repeats. A wait that ends after hours moves to the next opening.
      </p>
    </fieldset>
  );
}
