import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { api, unwrap } from "../../../lib/api";
import type { InstantInfo } from "../../../lib/instant";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { Confirm } from "../../../ui/Confirm";
import { Field } from "../../../ui/Field";
import { ErrorState } from "../../../ui/states";

type Props = { employeeId: string; info: InstantInfo };

/** Where leads come from: any tool that can POST, Meta Lead Ads, or a Google Sheet. */
export function Sources({ employeeId, info }: Props) {
  const url = `${location.origin}/api${info.intake_path}`;
  return (
    <div className="space-y-8">
      <WebIntake url={url} header={info.secret_header} employeeId={employeeId} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Meta employeeId={employeeId} info={info} />
        <Sheets employeeId={employeeId} info={info} />
      </div>
    </div>
  );
}

function WebIntake({ url, header, employeeId }: { url: string; header: string; employeeId: string }) {
  const [secret, setSecret] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employeeId } } };
  const example = `curl -X POST '${url}' \\\n  -H '${header}: ${secret ?? "<your secret>"}' \\\n  -H 'Content-Type: application/json' \\\n  -d '{"phone": "+919876543210", "name": "Ravi", "project": "Kokapet"}'`;
  return (
    <section aria-labelledby="web-intake" className="rounded-card border border-line bg-surface p-6">
      <h2 id="web-intake" className="eyebrow">Your website, forms and automation tools</h2>
      <p className="mt-2 text-sm text-ink-muted">
        Send each new lead here. The phone is required; every other field becomes a detail your employee can use. Fields the
        script doesn't ask for are ignored.
      </p>
      <dl className="mt-4 space-y-3 text-sm">
        <div>
          <dt className="text-ink-muted">Lead URL</dt>
          <dd className="num mt-1 rounded-ctl border border-line bg-bg px-3 py-2 break-all text-ink-strong">{url}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Header</dt>
          <dd className="mt-1 flex flex-wrap items-center gap-2">
            <code className="num rounded-ctl border border-line bg-bg px-3 py-2 text-ink-strong">{header}</code>
            <code className="num min-w-0 flex-1 rounded-ctl border border-line bg-bg px-3 py-2 break-all text-ink-strong" aria-label="Secret">
              {secret ?? "••••••••••••••••"}
            </code>
            <button type="button" className={btn.ghost} disabled={busy}
              onClick={() => void run(async () => setSecret((await unwrap<{ secret: string }>(api.POST("/employees/{employee_id}/instant/secret/reveal", p))).secret))}>
              Reveal
            </button>
            <Confirm trigger={<button type="button" className={btn.quiet}>Rotate</button>}
              title="Make a new secret?" body="The old one stops working at once. Update every form or tool that sends leads here." action="Rotate"
              onConfirm={() => void run(async () => setSecret((await unwrap<{ secret: string }>(api.POST("/employees/{employee_id}/instant/secret/rotate", p))).secret))} />
          </dd>
        </div>
      </dl>
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-ink-muted hover:text-ink">Example request</summary>
        <pre className="num mt-2 overflow-x-auto rounded-ctl border border-line bg-bg p-3 text-xs text-ink">{example}</pre>
      </details>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
      <TryALead employeeId={employeeId} />
    </section>
  );
}

type LeadResult = { status: string; reason: string | null; scheduled_for: string | null; variables: Record<string, unknown> };

/** A test lead runs every intake rule without a call; "Call now" places a real one. */
function TryALead({ employeeId }: { employeeId: string }) {
  const qc = useQueryClient();
  const [result, setResult] = useState<LeadResult | null>(null);
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employeeId } } };

  function send(e: FormEvent<HTMLFormElement>, real: boolean) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = { phone: String(f.get("phone")).trim(), name: String(f.get("name")).trim() || null, fields: {} };
    void run(async () => {
      const r = real
        ? await unwrap<LeadResult>(api.POST("/employees/{employee_id}/instant/call", { ...p, body }))
        : await unwrap<LeadResult>(api.POST("/employees/{employee_id}/instant/test-lead", { ...p, body }));
      setResult(r);
      void qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });
  }
  return (
    <form onSubmit={(e) => send(e, (e.nativeEvent as SubmitEvent).submitter?.getAttribute("value") === "call")} className="mt-6 border-t border-line pt-5">
      <p className="text-sm text-ink">Try a lead</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Phone" name="phone" type="tel" placeholder="+919876543210" required />
        <Field label="Name" name="name" />
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="submit" value="test" className={btn.ghost} disabled={busy}>Send a test lead (no call)</button>
        <button type="submit" value="call" className={btn.primary} disabled={busy}>Call this number now</button>
      </div>
      {result && (
        <p role="status" className="mt-3 text-sm text-ink">
          <span className={result.status === "accepted" ? "text-accent" : "text-warn"}>● {result.status}</span>
          {result.reason && <span className="text-ink-muted"> · {result.reason}</span>}
          {result.scheduled_for && <span className="text-ink-muted"> · dials {new Date(result.scheduled_for).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}</span>}
        </p>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </form>
  );
}

function Meta({ employeeId, info }: Props) {
  const qc = useQueryClient();
  const { busy, error, run } = useAction();
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    void run(async () => {
      await unwrap(api.PUT("/employees/{employee_id}/instant/meta", {
        params: { path: { employee_id: employeeId } },
        body: { form_id: String(f.get("form_id")).trim(), page_access_token: String(f.get("token")).trim() },
      }));
      await qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });
  }
  return (
    <form onSubmit={save} aria-labelledby="meta" className="rounded-card border border-line bg-surface p-6">
      <h2 id="meta" className="eyebrow">Meta Lead Ads</h2>
      <p className="mt-2 text-sm text-ink-muted">Leads from a Facebook or Instagram lead form are called as they arrive.</p>
      <div className="mt-4 space-y-3">
        <Field label="Lead form id" name="form_id" defaultValue={info.meta.form_id ?? ""} required />
        <Field label="Page access token" name="token" type="password" autoComplete="off" hint={info.meta.token_set ? "A token is saved. Enter it again to replace it." : "From Meta Business Suite for the page that owns the form."} />
      </div>
      <button type="submit" className={`${btn.ghost} mt-4`} disabled={busy}>Save</button>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </form>
  );
}

function Sheets({ employeeId, info }: Props) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const { busy, error, run } = useAction();
  const redirect = `${location.origin}/employees/${employeeId}/instant`;
  const p = { params: { path: { employee_id: employeeId } } };

  // Back from Google's consent screen with a code: finish connecting once, then tidy the address.
  const code = params.get("code");
  const state = params.get("state");
  useEffect(() => {
    if (!code || !state) return;
    setParams({}, { replace: true });
    void run(async () => {
      await unwrap(api.POST("/employees/{employee_id}/instant/sheets/connect", { ...p, body: { code, state, redirect_uri: redirect } }));
      await qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });
  }, [code, state, employeeId]); // run, p and redirect follow from these

  function choose(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    void run(async () => {
      await unwrap(api.PUT("/employees/{employee_id}/instant/sheets", { ...p, body: { sheet_id: String(f.get("sheet")).trim(), range: String(f.get("range")).trim() || "A:Z" } }));
      await qc.invalidateQueries({ queryKey: ["instant", employeeId] });
    });
  }
  return (
    <section aria-labelledby="sheets" className="rounded-card border border-line bg-surface p-6">
      <h2 id="sheets" className="eyebrow">Google Sheets</h2>
      <p className="mt-2 text-sm text-ink-muted">New rows in a sheet become leads. Rows already there are not called.</p>
      {info.sheets.connected ? (
        <form onSubmit={choose} className="mt-4 space-y-3">
          <Field label="Sheet id or link" name="sheet" defaultValue={info.sheets.sheet_id ?? ""} required />
          <Field label="Range" name="range" defaultValue={info.sheets.range ?? "A:Z"} hint="The first row is the column names; one must be the phone." />
          <button type="submit" className={btn.ghost} disabled={busy}>Use this sheet</button>
        </form>
      ) : (
        <button type="button" className={`${btn.primary} mt-4`} disabled={busy}
          onClick={() => void run(async () => {
            const { url } = await unwrap<{ url: string }>(api.GET("/employees/{employee_id}/instant/sheets/consent-url", { params: { path: { employee_id: employeeId }, query: { redirect_uri: redirect } } }));
            location.assign(url);
          })}>
          Connect Google Sheets
        </button>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}
