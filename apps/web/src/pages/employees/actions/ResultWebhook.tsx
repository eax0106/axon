import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../../lib/api";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { Confirm } from "../../../ui/Confirm";
import { Field } from "../../../ui/Field";
import { ErrorState } from "../../../ui/states";
import { useDetail } from "../Detail";

const TRIGGERS = { all_connected: "Every call that reached someone", skip_voicemail: "Calls that reached a person, not voicemail", voicemail_only: "Only calls that reached voicemail" } as const;

/** Where this employee's call results are sent (signed). Part of the script: it goes live when applied. */
export function ResultWebhook() {
  const { employee } = useDetail();
  const qc = useQueryClient();
  const p = { params: { path: { employee_id: employee.id } } };
  const current = useQuery({ queryKey: ["webhook", employee.id], queryFn: () => unwrap(api.GET("/employees/{employee_id}/webhook", p)) });
  const [result, setResult] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const hook = current.data?.webhook ?? null;
  const after = async () => {
    await qc.invalidateQueries({ queryKey: ["webhook", employee.id] });
    await qc.invalidateQueries({ queryKey: ["employee", employee.id] });
  };
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    void run(async () => {
      await unwrap(api.PUT("/employees/{employee_id}/webhook", { ...p, body: { url: String(f.get("url")).trim(), trigger: String(f.get("trigger")) as keyof typeof TRIGGERS, secret: String(f.get("secret")) } }));
      await after();
    });
  }
  return (
    <form onSubmit={save} aria-labelledby="result-hook" className="rounded-card border border-line bg-surface p-6">
      <h2 id="result-hook" className="eyebrow">Send each result to your system</h2>
      <p className="mt-1 text-sm text-ink-muted">After a call is analysed, its outcome, summary and captured details are posted here, signed.</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Field label="Address (https)" name="url" defaultValue={hook?.url ?? ""} key={hook?.url ?? "none"} inputMode="url" required />
        <label className="block"><span className="text-sm text-ink">Send for</span>
          <select name="trigger" defaultValue={hook?.trigger ?? "all_connected"} key={hook?.trigger ?? "t"} className="mt-1.5 h-12 w-full rounded-ctl border border-line-accent bg-surface px-3 text-ink-strong">
            {Object.entries(TRIGGERS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <Field label="Signing secret (optional, never shown back)" name="secret" type="password" autoComplete="off" defaultValue={hook?.secret ?? ""} key={hook?.secret ?? "s"} />
      </div>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
      {result && <pre tabIndex={0} className="num mt-3 max-h-48 overflow-auto rounded-ctl border border-line bg-bg p-3 text-xs text-ink">{result}</pre>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="submit" className={btn.primary} disabled={busy}>Save</button>
        {hook && (
          <>
            <button type="button" className={btn.ghost} disabled={busy} onClick={() => void run(async () => setResult(JSON.stringify(await unwrap(api.POST("/employees/{employee_id}/webhook/test", p)), null, 2)))}>Send a test</button>
            <Confirm trigger={<button type="button" className={btn.quiet}>Remove</button>} title="Stop sending results?" body="Applies to live calls when you apply the script." action="Remove"
              onConfirm={() => void run(async () => { await unwrap(api.DELETE("/employees/{employee_id}/webhook", p)); await after(); })} />
          </>
        )}
      </div>
    </form>
  );
}
