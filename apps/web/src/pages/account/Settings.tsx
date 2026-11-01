import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ApiError, api, unwrap } from "../../lib/api";
import { signIn, useMe } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { Field, SubmitButton } from "../../ui/Field";
import { ErrorState, Skeleton } from "../../ui/states";

const card = "rounded-card border border-line bg-surface p-6";

/** Business name the employees introduce themselves with, and the hard cap on any call's length. */
export function Business() {
  const owner = useMe().data?.user.role === "owner";
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["account", "settings"], queryFn: () => unwrap(api.GET("/account/settings")) });
  const terms = useQuery({ queryKey: ["account", "terms"], queryFn: () => unwrap(api.GET("/account/terms")) });
  const [saved, setSaved] = useState(false);
  const { busy, error, run } = useAction();
  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setSaved(false);
    void run(async () => {
      const body = { name: String(f.get("name")).trim(), business_name: String(f.get("business_name")).trim() || null, max_call_s: Math.round(Number(f.get("max_call_min")) * 60) };
      qc.setQueryData(["account", "settings"], await unwrap(api.PUT("/account/settings", { body })));
      await qc.invalidateQueries({ queryKey: ["me"] });
      setSaved(true);
    });
  }
  const s = settings.data;
  return (
    <section aria-labelledby="business" className={card}>
      <h2 id="business" className="eyebrow">Business</h2>
      {settings.error ? <div className="mt-4"><ErrorState error={settings.error} retry={() => void settings.refetch()} /></div> : !s ? <Skeleton className="mt-4 h-48" /> : (
        <form onSubmit={save} className="mt-4 space-y-4">
          <fieldset disabled={!owner} className="space-y-4">
            <Field label="Account name" name="name" defaultValue={s.name} maxLength={200} required />
            <Field label="Business name on calls" name="business_name" defaultValue={s.business_name ?? ""} maxLength={200} hint="What your employees say they are calling from. Blank uses the account name." />
            <Field label="Longest call (minutes)" name="max_call_min" type="number" min={0.5} max={60} step={0.5} defaultValue={s.max_call_s / 60} required hint="Every call hangs up at this point, so one stuck call can't drain credits." />
          </fieldset>
          {owner ? <SubmitButton busy={busy} busyText="Saving…">{saved ? "Saved" : "Save"}</SubmitButton> : <p className="text-sm text-ink-muted">Only the account owner changes these.</p>}
          {error !== null && <ErrorState error={error} />}
        </form>
      )}
      <p className="mt-4 text-xs text-ink-muted">
        {terms.data?.accepted_at ? `Terms version ${terms.data.version} accepted ${new Date(terms.data.accepted_at).toLocaleDateString("en-IN")}.` : "Terms of service not accepted yet."}
      </p>
    </section>
  );
}

/** Changing the password signs out every other session; this one carries on with the new token. */
export function Password() {
  const [done, setDone] = useState(false);
  const { busy, error, run } = useAction();
  const wrong = error instanceof ApiError && error.status === 400 ? error.message : undefined;
  function change(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    setDone(false);
    void run(async () => {
      const token = await unwrap(api.POST("/auth/password", { body: { current_password: String(f.get("current")), new_password: String(f.get("new")) } }));
      form.reset();
      signIn(token.access_token);
      setDone(true);
    });
  }
  return (
    <section aria-labelledby="password" className={card}>
      <h2 id="password" className="eyebrow">Password</h2>
      <form onSubmit={change} className="mt-4 space-y-4">
        <Field label="Current password" name="current" type="password" autoComplete="current-password" required error={wrong} />
        <Field label="New password" name="new" type="password" autoComplete="new-password" minLength={8} maxLength={128} required hint="At least 8 characters. Other devices are signed out." />
        <SubmitButton busy={busy} busyText="Changing…">Change password</SubmitButton>
        {done && <p role="status" className="text-sm text-accent">Password changed. Other sessions are signed out.</p>}
        {error !== null && !wrong && <ErrorState error={error} />}
      </form>
    </section>
  );
}
