import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { type Action, KINDS, type Kind, blank, problems } from "../../../lib/actions";
import { api, unwrap } from "../../../lib/api";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { ErrorState, Skeleton } from "../../../ui/states";
import { useDetail } from "../Detail";
import { ActionForm } from "./ActionForm";
import { ResultWebhook } from "./ResultWebhook";

/** What the employee may do during a call. Off unless added; edits go live with "Apply to live calls". */
export default function ActionsTab() {
  const { employee } = useDetail();
  const p = { params: { path: { employee_id: employee.id } } };
  const saved = useQuery({ queryKey: ["actions", employee.id], queryFn: () => unwrap(api.GET("/employees/{employee_id}/actions", p)) });
  if (saved.error) return <ErrorState error={saved.error} retry={() => void saved.refetch()} />;
  if (!saved.data) return <Skeleton className="h-96 rounded-card" />;
  return (
    <div className="space-y-8">
      <Google />
      <Editor key={employee.id} initial={saved.data.actions as Action[]} />
      <ResultWebhook />
    </div>
  );
}

function Editor({ initial }: { initial: Action[] }) {
  const { employee } = useDetail();
  const qc = useQueryClient();
  const [list, setList] = useState(initial);
  const [dirty, setDirty] = useState(false);
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employee.id } } };
  const change = (next: Action[]) => {
    setList(next);
    setDirty(true);
  };
  const ready = list.every((a) => problems(a).length === 0);
  const save = () =>
    run(async () => {
      const back = await unwrap(api.PUT("/employees/{employee_id}/actions", { ...p, body: { actions: list as never } }));
      setList(back.actions as Action[]);
      setDirty(false);
      // Actions are publish-gated with the script: the employee now has pending edits.
      await qc.invalidateQueries({ queryKey: ["employee", employee.id] });
    });

  return (
    <section aria-labelledby="actions" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="actions" className="eyebrow">During the call</h2>
          <p className="mt-1 text-sm text-ink-muted">Up to 10. Saved changes reach callers when you apply them to live calls.</p>
        </div>
        <label className="text-sm">
          <span className="sr-only">Add an action</span>
          <select value="" disabled={list.length >= 10} onChange={(e) => e.target.value && change([...list, blank(e.target.value as Kind, list.map((a) => a.name))])}
            className="h-9 rounded-ctl border border-line-accent bg-surface px-2 text-ink">
            <option value="">+ Add an action</option>
            {Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </label>
      </div>
      <ul className="space-y-3">
        {list.map((a, i) => (
          <li key={i} className="rounded-card border border-line bg-surface p-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-ink-strong">{KINDS[a.kind as Kind]?.label}</p>
              <button type="button" className="text-xs text-ink-muted hover:text-danger" onClick={() => change(list.filter((_, j) => j !== i))}>Remove</button>
            </div>
            <ActionForm action={a} onChange={(next) => change(list.map((x, j) => (j === i ? next : x)))} />
            {!dirty && <TestConsole name={a.name} />}
          </li>
        ))}
        {list.length === 0 && <li className="rounded-card border border-dashed border-line p-8 text-center text-sm text-ink-muted">No actions: the employee only talks. Add one to let it book, look up or send things.</li>}
      </ul>
      {error !== null && <ErrorState error={error} />}
      <button type="button" className={btn.primary} disabled={busy || !dirty || !ready} onClick={() => void save()}>{busy ? "Saving…" : "Save actions"}</button>
    </section>
  );
}

/** Runs the saved draft action for real with sample values, and shows the answer. */
function TestConsole({ name }: { name: string }) {
  const { employee } = useDetail();
  const [args, setArgs] = useState("{}");
  const [result, setResult] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction();
  return (
    <details className="mt-4 border-t border-line pt-3 text-sm">
      <summary className="cursor-pointer text-ink-muted hover:text-ink">Test it</summary>
      <label className="mt-2 block"><span className="text-xs text-ink-muted">Values the employee would send (JSON)</span>
        <textarea aria-label={`Test values for ${name}`} rows={3} value={args} onChange={(e) => setArgs(e.target.value)} className="num mt-1 w-full rounded-ctl border border-line bg-bg px-3 py-2 text-xs text-ink-strong" /></label>
      <button type="button" className={`${btn.ghost} mt-2`} disabled={busy}
        onClick={() => void run(async () => {
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(args) as Record<string, unknown>;
          } catch {
            setError(new Error("The values must be JSON, like {\"date\": \"2026-11-05\"}."));
            return;
          }
          const r = await unwrap(api.POST("/employees/{employee_id}/actions/{name}/test", { params: { path: { employee_id: employee.id, name } }, body: { args: parsed } }));
          setResult(JSON.stringify(r, null, 2));
        })}>Run</button>
      {result && <pre tabIndex={0} className="num mt-2 max-h-60 overflow-auto rounded-ctl border border-line bg-bg p-3 text-xs text-ink">{result}</pre>}
      {error !== null && <div className="mt-2"><ErrorState error={error} /></div>}
    </details>
  );
}

/** One Google connection per account, for Calendar and Sheets; shows what Google actually granted. */
function Google() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { busy, error, run } = useAction();
  const status = useQuery({ queryKey: ["google"], queryFn: () => unwrap(api.GET("/integrations/google")) });
  const redirect = `${location.origin}${location.pathname}`;
  const code = params.get("code");
  const state = params.get("state");
  useEffect(() => {
    if (!code || !state) return;
    setParams({}, { replace: true });
    void run(async () => {
      await unwrap(api.POST("/integrations/google/connect", { body: { code, state, redirect_uri: redirect } }));
      await qc.invalidateQueries({ queryKey: ["google"] });
    });
  }, [code, state]); // run, redirect and qc follow from these
  const s = status.data;
  return (
    <section aria-labelledby="google" className="rounded-card border border-line bg-surface p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="google" className="eyebrow">Google</h2>
          <p className="mt-1 text-sm text-ink-muted">
            {s?.connected ? `Connected: ${["calendar", "sheets"].filter((k) => s[k]).join(" and ") || "no services granted"}.` : "Connect to let actions book in Calendar or use Sheets."}
          </p>
        </div>
        <div className="flex gap-2">
          {s?.connected ? (
            <button type="button" className={btn.quiet} disabled={busy} onClick={() => void run(async () => { await unwrap(api.DELETE("/integrations/google")); await qc.invalidateQueries({ queryKey: ["google"] }); })}>Disconnect</button>
          ) : (
            <button type="button" className={btn.ghost} disabled={busy}
              onClick={() => void run(async () => location.assign((await unwrap<{ url: string }>(api.GET("/integrations/google/consent-url", { params: { query: { redirect_uri: redirect, services: ["calendar", "sheets"] } } }))).url))}>
              Connect Google
            </button>
          )}
        </div>
      </div>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}
