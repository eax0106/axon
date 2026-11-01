import type { components } from "@axon/contracts";

import { type Action, KINDS, problems } from "../../../lib/actions";

type Param = components["schemas"]["Param"];
const box = "mt-1 h-9 w-full rounded-ctl border border-line bg-bg px-2.5 text-sm text-ink-strong outline-none focus:border-accent";

/** One action's settings, by kind. Secrets arrive masked; sending the mask back keeps the stored one. */
export function ActionForm({ action: a, onChange }: { action: Action; onChange: (a: Action) => void }) {
  const set = (patch: Record<string, unknown>) => onChange({ ...a, ...patch } as Action);
  const text = (label: string, key: string, value: string, extra: Record<string, unknown> = {}) => (
    <label className="block text-sm"><span className="text-ink-muted">{label}</span>
      <input value={value} onChange={(e) => set({ [key]: e.target.value })} className={box} {...extra} /></label>
  );
  const num = (label: string, key: string, value: number, min: number, max: number) => (
    <label className="block text-sm"><span className="text-ink-muted">{label}</span>
      <input type="number" min={min} max={max} value={value} onChange={(e) => set({ [key]: Number(e.target.value) })} className={`num ${box}`} /></label>
  );
  const issues = problems(a);
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[14rem_1fr]">
        {text("Name the employee calls it by", "name", a.name, { maxLength: 40 })}
        {text("When to use it", "description", a.description, { maxLength: 300, placeholder: "When the caller wants to visit the site" })}
      </div>
      {a.kind === "calendar_booking" && (
        <div className="grid gap-3 sm:grid-cols-3">
          {text("Calendar", "calendar_id", a.calendar_id ?? "primary")}
          {text("Event title", "title", a.title ?? "Appointment")}
          {num("Minutes per slot", "duration_min", a.duration_min ?? 30, 10, 240)}
          {num("Book up to (days ahead)", "days_ahead", a.days_ahead ?? 14, 1, 60)}
          {num("From hour", "start_hour", a.start_hour ?? 10, 0, 23)}
          {num("Until hour", "end_hour", a.end_hour ?? 18, 1, 24)}
        </div>
      )}
      {(a.kind === "sheet_read" || a.kind === "sheet_write") && (
        <div className="grid gap-3 sm:grid-cols-2">
          {text("Sheet id or link", "sheet_id", a.sheet_id)}
          {text("Range", "range", a.range ?? "A:Z")}
        </div>
      )}
      {a.kind === "sheet_write" && <Params label="Columns to fill" params={a.columns} onChange={(columns) => set({ columns })} />}
      {a.kind === "http_api" && (
        <>
          <div className="grid gap-3 sm:grid-cols-[7rem_1fr_6rem]">
            <label className="block text-sm"><span className="text-ink-muted">Method</span>
              <select value={a.method} onChange={(e) => set({ method: e.target.value })} className={box}>{["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => <option key={m}>{m}</option>)}</select></label>
            {text("Address (https)", "url", a.url, { inputMode: "url" })}
            {num("Timeout (s)", "timeout_s", a.timeout_s ?? 8, 1, 15)}
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="block text-sm"><span className="text-ink-muted">Sign in with</span>
              <select value={a.auth?.kind ?? "none"} onChange={(e) => set({ auth: { ...a.auth, kind: e.target.value } })} className={box}>
                <option value="none">Nothing</option><option value="bearer">Bearer token</option><option value="header">A header</option></select></label>
            {a.auth?.kind === "header" && (
              <label className="block text-sm"><span className="text-ink-muted">Header name</span>
                <input value={a.auth.header ?? ""} onChange={(e) => set({ auth: { ...a.auth, header: e.target.value } })} className={box} /></label>
            )}
            {a.auth?.kind && a.auth.kind !== "none" && (
              <label className="block text-sm"><span className="text-ink-muted">Secret (never shown back)</span>
                <input type="password" autoComplete="off" value={a.auth.secret ?? ""} onChange={(e) => set({ auth: { ...a.auth, secret: e.target.value } })} className={box} /></label>
            )}
          </div>
          <Params label="What the employee sends" params={a.params ?? []} onChange={(params) => set({ params })} />
        </>
      )}
      {a.kind === "whatsapp" && (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {text("Approved template name", "template", a.template)}
            {text("Template language", "language", a.language ?? "en")}
          </div>
          <Params label="Template values" params={a.params ?? []} onChange={(params) => set({ params })} />
        </>
      )}
      {issues.length > 0 && <ul className="text-xs text-warn">{issues.map((i) => <li key={i}>● {i}</li>)}</ul>}
      <p className="text-xs text-ink-muted">{KINDS[a.kind as keyof typeof KINDS]?.blurb}</p>
    </div>
  );
}

function Params({ label, params, onChange }: { label: string; params: Param[]; onChange: (p: Param[]) => void }) {
  const at = (i: number, patch: Partial<Param>) => onChange(params.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  return (
    <fieldset className="text-sm">
      <legend className="text-ink-muted">{label}</legend>
      <ul className="mt-1 space-y-1.5">
        {params.map((p, i) => (
          <li key={i} className="grid grid-cols-[9rem_1fr_6rem_auto] items-center gap-2">
            <input aria-label={`${label} ${i + 1} name`} value={p.name} onChange={(e) => at(i, { name: e.target.value })} placeholder="name" className={`num ${box} mt-0`} />
            <input aria-label={`${label} ${i + 1} meaning`} value={p.description} onChange={(e) => at(i, { description: e.target.value })} placeholder="what it is" className={`${box} mt-0`} />
            <select aria-label={`${label} ${i + 1} type`} value={p.type ?? "string"} onChange={(e) => at(i, { type: e.target.value as Param["type"] })} className={`${box} mt-0`}>
              <option value="string">Text</option><option value="number">Number</option><option value="boolean">Yes/no</option></select>
            <button type="button" aria-label={`Remove ${label} ${i + 1}`} className="text-ink-muted hover:text-danger" onClick={() => onChange(params.filter((_, j) => j !== i))}>×</button>
          </li>
        ))}
      </ul>
      <button type="button" className="mt-1.5 text-xs text-accent" onClick={() => onChange([...params, { name: "", description: "", type: "string", required: true }])}>+ Add</button>
    </fieldset>
  );
}
