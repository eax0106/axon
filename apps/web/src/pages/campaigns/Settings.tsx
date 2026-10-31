import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Campaign, type CampaignSettings, useCampaignAction } from "../../lib/campaigns";
import { fromClock, toClock } from "../../lib/instant";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const input = "num mt-1.5 h-10 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong outline-none focus:border-accent";

/** How the list is worked: hours (9 AM–9 PM at most), pace, retries, repeats and repeats across campaigns. */
export function CampaignSettingsForm({ campaign, editable }: { campaign: Campaign; editable: boolean }) {
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
    <fieldset disabled={!editable} className="rounded-card border border-line bg-surface p-6 disabled:opacity-70">
      <legend className="sr-only">Campaign settings</legend>
      {!editable && <p className="mb-4 text-sm text-ink-muted">Pause the campaign to change its settings.</p>}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <label className="block"><span className="text-sm text-ink">Calls from</span>
          <input type="time" min="09:00" max="21:00" step={300} value={toClock(s.window_start_min)} onChange={(e) => set({ window_start_min: fromClock(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Until</span>
          <input type="time" min="09:00" max="21:00" step={300} value={toClock(s.window_end_min)} onChange={(e) => set({ window_end_min: fromClock(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Calls at once</span>
          <input type="number" min={1} max={20} value={s.concurrency} onChange={(e) => set({ concurrency: Number(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Skip numbers another campaign called in</span>
          <span className="relative block"><input type="number" min={0} max={90} value={s.dedupe_days} onChange={(e) => set({ dedupe_days: Number(e.target.value) })} className={input} />
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
        <label className="block"><span className="text-sm text-ink">Minutes between tries</span>
          <input type="number" min={1} max={1440} value={s.retry_gap_min} onChange={(e) => set({ retry_gap_min: Number(e.target.value) })} className={input} /></label>
        <label className="block"><span className="text-sm text-ink">Retry</span>
          <select value={s.retry_mode} onChange={(e) => set({ retry_mode: e.target.value as CampaignSettings["retry_mode"] })} className={input}>
            <option value="same_run">In the same run</option><option value="next_day">The next day</option></select></label>
        <label className="block"><span className="text-sm text-ink">Repeat</span>
          <select value={s.repeat} onChange={(e) => set({ repeat: e.target.value as CampaignSettings["repeat"] })} className={input}>
            <option value="none">Run once</option><option value="daily">Every day</option><option value="weekly">Every week</option></select></label>
      </div>

      <label className="mt-5 flex items-start gap-3 text-sm">
        <input type="checkbox" checked={s.skip_dnc} onChange={(e) => set({ skip_dnc: e.target.checked })} className="mt-0.5 accent-[var(--accent)]" />
        <span><span className="text-ink">Skip numbers on my do-not-call list</span>
          <span className="block text-xs text-ink-muted">Anyone who asked not to be called is always skipped, whatever this says.</span></span>
      </label>

      {action.error && <div className="mt-4"><ErrorState error={action.error} /></div>}
      <div className="mt-5 flex items-center gap-3">
        <button type="button" className={btn.primary} onClick={save} disabled={action.isPending}>Save settings</button>
        {saved && <span role="status" className="text-sm text-accent">Saved.</span>}
      </div>
    </fieldset>
  );
}
