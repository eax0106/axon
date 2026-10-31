import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type InboundSettings, toWindows } from "../../lib/inbound";
import { fromClock, toClock } from "../../lib/instant";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { useDetail } from "./Detail";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const area = "mt-1.5 w-full resize-y rounded-ctl border border-line-accent bg-bg px-3 py-2 text-ink-strong outline-none focus:border-accent";

/** How the employee answers its number. Instant and Bulk employees only choose whether they pick up their own leads. */
export default function IncomingTab() {
  const { employee } = useDetail();
  const p = { params: { path: { employee_id: employee.id } } };
  const settings = useQuery({ queryKey: ["inbound", employee.id], queryFn: () => unwrap<InboundSettings>(api.GET("/employees/{employee_id}/inbound-settings", p)) });
  if (settings.error) return <ErrorState error={settings.error} retry={() => void settings.refetch()} />;
  if (!settings.data) return <Skeleton className="h-96 rounded-card" />;
  return <Form key={employee.id} initial={settings.data} inbound={employee.channel === "inbound"} />;
}

function Form({ initial, inbound }: { initial: InboundSettings; inbound: boolean }) {
  const { employee } = useDetail();
  const qc = useQueryClient();
  const [s, setS] = useState(initial);
  const [saved, setSaved] = useState(false);
  const [draft, setDraft] = useState({ days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" });
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employee.id } } };
  const set = (patch: Partial<InboundSettings>) => {
    setSaved(false);
    setS((x) => ({ ...x, ...patch }));
  };
  const save = () =>
    run(async () => {
      const back = await unwrap<InboundSettings>(api.PUT("/employees/{employee_id}/inbound-settings", { ...p, body: s }));
      setS(back);
      qc.setQueryData(["inbound", employee.id], back);
      setSaved(true);
    });
  const toggle = (key: keyof InboundSettings, label: string, hint: string) => (
    <label className="flex cursor-pointer items-start justify-between gap-6 border-b border-line py-4">
      <span><span className="block text-ink">{label}</span><span className="mt-0.5 block text-sm text-ink-muted">{hint}</span></span>
      <input type="checkbox" role="switch" checked={Boolean(s[key])} onChange={(e) => set({ [key]: e.target.checked })} className="mt-1 size-5 shrink-0 accent-[var(--accent)]" />
    </label>
  );

  return (
    <div className="max-w-3xl space-y-10">
      {!inbound && toggle("answer_callbacks", "Answer my leads when they call back", "If someone this employee called rings its number, it picks up with what it knows about them.")}

      {inbound && (
        <>
          <section aria-labelledby="hours" className="space-y-4">
            <h2 id="hours" className="eyebrow">When it answers</h2>
            <div role="radiogroup" aria-label="Opening hours" className="flex gap-1 rounded-ctl border border-line p-1">
              {[[true, "Day and night"], [false, "Opening hours"]].map(([v, l]) => (
                <button key={String(v)} type="button" role="radio" aria-checked={s.always_open === v} onClick={() => set({ always_open: v as boolean })}
                  className="flex-1 rounded-tag px-3 py-1.5 text-sm text-ink-muted aria-checked:bg-accent-soft aria-checked:text-ink-strong">{l as string}</button>
              ))}
            </div>
            {!s.always_open && (
              <>
                <ul className="space-y-2">
                  {s.hours.map((w, i) => (
                    <li key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-ctl border border-line bg-surface px-3 py-2 text-sm">
                      <span className="text-ink">{w.days.map((d) => DAYS[d]).join(", ")}</span>
                      <span className="num text-ink-muted">{toClock(w.start_min)}–{w.end_min === 1440 ? "24:00" : toClock(w.end_min)}</span>
                      <button type="button" aria-label={`Remove hours ${i + 1}`} className="text-ink-muted hover:text-danger" onClick={() => set({ hours: s.hours.filter((_, j) => j !== i) })}>×</button>
                    </li>
                  ))}
                </ul>
                <fieldset className="rounded-card border border-line bg-surface p-4">
                  <legend className="px-1 text-sm text-ink">Add hours (Indian time)</legend>
                  <div className="flex flex-wrap gap-1.5">
                    {DAYS.map((d, i) => (
                      <label key={d} className="cursor-pointer rounded-ctl border border-line px-2.5 py-1 text-sm text-ink-muted has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:checked]:text-ink-strong">
                        <input type="checkbox" className="sr-only" checked={draft.days.includes(i)} onChange={(e) => setDraft({ ...draft, days: e.target.checked ? [...draft.days, i].sort() : draft.days.filter((x) => x !== i) })} />{d}
                      </label>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-end gap-2">
                    <label className="text-sm text-ink">From<input type="time" value={draft.start} onChange={(e) => setDraft({ ...draft, start: e.target.value })} className="num ml-2 h-9 rounded-ctl border border-line bg-bg px-2 text-ink-strong" /></label>
                    <label className="text-sm text-ink">To<input type="time" value={draft.end} onChange={(e) => setDraft({ ...draft, end: e.target.value })} className="num ml-2 h-9 rounded-ctl border border-line bg-bg px-2 text-ink-strong" /></label>
                    <button type="button" className={btn.ghost} disabled={draft.days.length === 0}
                      onClick={() => set({ hours: [...s.hours, ...toWindows(draft.days, fromClock(draft.start), fromClock(draft.end))] })}>Add</button>
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">Hours past midnight (10 PM to 2 AM) are saved as two windows.</p>
                </fieldset>
                <label className="block text-sm">
                  <span className="text-ink">When closed</span>
                  <select value={s.closed_mode} onChange={(e) => set({ closed_mode: e.target.value as InboundSettings["closed_mode"] })} className="mt-1.5 h-10 w-full rounded-ctl border border-line-accent bg-bg px-3 text-ink-strong">
                    <option value="take_message">Answer, say we're closed, and take a message</option>
                    <option value="hang_up">Don't answer (a missed call)</option>
                  </select>
                </label>
                {s.closed_mode === "take_message" && (
                  <label className="block text-sm"><span className="text-ink">Closed message</span>
                    <textarea rows={2} maxLength={300} value={s.closed_message} onChange={(e) => set({ closed_message: e.target.value })} placeholder="We're closed now; leave a message and we'll call you back." className={area} /></label>
                )}
              </>
            )}
          </section>

          <section aria-labelledby="words" className="space-y-4">
            <h2 id="words" className="eyebrow">What callers hear first</h2>
            <label className="block text-sm"><span className="text-ink">Recording notice</span>
              <span className="mt-0.5 block text-xs text-ink-muted">Always said first and cannot be switched off. Reword it, or leave it empty for the standard notice in the caller's language.</span>
              <textarea rows={2} maxLength={200} value={s.disclosure} onChange={(e) => set({ disclosure: e.target.value })} placeholder="This call may be recorded for quality purposes." className={area} /></label>
            <label className="block text-sm"><span className="text-ink">Greeting for a new caller</span>
              <span className="mt-0.5 block text-xs text-ink-muted">May use {"{{business_name}}"}. A new caller's name isn't known, so it can't be used here.</span>
              <textarea rows={2} maxLength={300} value={s.greeting_new} onChange={(e) => set({ greeting_new: e.target.value })} className={area} /></label>
            <label className="block text-sm"><span className="text-ink">Greeting for someone who called before</span>
              <span className="mt-0.5 block text-xs text-ink-muted">May use {"{{name}}"} and {"{{business_name}}"}.</span>
              <textarea rows={2} maxLength={300} value={s.greeting_returning} onChange={(e) => set({ greeting_returning: e.target.value })} className={area} /></label>
          </section>

          <section aria-labelledby="transfer" className="space-y-3">
            <h2 id="transfer" className="eyebrow">Hand over to a person</h2>
            <label className="block text-sm"><span className="text-ink">Transfer to</span>
              <input type="tel" value={s.transfer_number ?? ""} onChange={(e) => set({ transfer_number: e.target.value || null })} placeholder="+91 98765 43210" className={`${area} h-10`} /></label>
            <label className="block text-sm"><span className="text-ink">When</span>
              <input value={s.transfer_when} maxLength={300} onChange={(e) => set({ transfer_when: e.target.value })} placeholder="The caller asks for a person, or wants to book today" className={`${area} h-10`} /></label>
          </section>

          <section aria-label="Follow-ups">
            {toggle("auto_callback", "Call back missed callers once", "Within calling hours, never twice in a day, never anyone on the do-not-call list.")}
            {toggle("daily_summary", "Email me a summary each morning", "Yesterday's incoming calls, from 8 AM.")}
          </section>
        </>
      )}

      {error !== null && <ErrorState error={error} />}
      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className={btn.primary} disabled={busy} onClick={() => void save()}>Save</button>
        {saved && <span role="status" className="text-sm text-accent">Saved. The next call follows these settings.</span>}
        {inbound && <ConnectNumber />}
      </div>
    </div>
  );
}

/** Points the number's incoming calls at Axon again (done automatically at go-live). */
function ConnectNumber() {
  const { employee } = useDetail();
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  return (
    <>
      <button type="button" className={btn.quiet} disabled={busy}
        onClick={() => void run(async () => setDone((await unwrap<{ number: string }>(api.POST("/employees/{employee_id}/inbound/connect", { params: { path: { employee_id: employee.id } } }))).number))}>
        Reconnect the number
      </button>
      {done && <span role="status" className="text-sm text-accent">{done} rings here.</span>}
      {error !== null && <div className="w-full"><ErrorState error={error} /></div>}
    </>
  );
}
