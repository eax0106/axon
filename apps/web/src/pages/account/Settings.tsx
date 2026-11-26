import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ApiError, api, unwrap } from "../../lib/api";
import { btn } from "../../ui/buttons";
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

type Started = { secret: string; otpauth_uri: string };

/** An optional authenticator-app code at every sign-in. Staff always have one (set at sign-in);
 *  a support session cannot change it. Turning it off needs a current code from the app. */
export function TwoFactor() {
  const qc = useQueryClient();
  const me = useMe().data;
  const [started, setStarted] = useState<Started | null>(null);
  const [codes, setCodes] = useState<string[] | null>(null);
  const { busy, error, run } = useAction();
  if (!me) return <Skeleton className="h-40 rounded-card" />;
  const on = me.user.two_factor;
  const wrong = error instanceof ApiError && error.status === 401 ? "That code isn't right. Use the newest code in your app." : error instanceof ApiError && error.status === 429 ? "Too many tries. Wait 15 minutes." : undefined;
  const refresh = () => qc.invalidateQueries({ queryKey: ["me"] });
  const code = (form: HTMLFormElement) => String(new FormData(form).get("code")).trim();

  function start() {
    void run(async () => setStarted(await unwrap(api.POST("/auth/second-factor/setup"))));
  }
  function confirm(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const typed = code(e.currentTarget);
    void run(async () => {
      const r = await unwrap(api.POST("/auth/second-factor/setup/confirm", { body: { code: typed } }));
      setStarted(null);
      setCodes(r.recovery_codes);
      await refresh();
    });
  }
  function disable(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const typed = code(e.currentTarget);
    void run(async () => {
      await unwrap(api.POST("/auth/second-factor/disable", { body: { code: typed } }));
      setCodes(null);
      await refresh();
    });
  }

  return (
    <section aria-labelledby="two-factor" className={card}>
      <h2 id="two-factor" className="eyebrow">Two-step sign-in</h2>
      {me.user.staff ? (
        <p className="mt-2 text-sm text-ink-muted">Staff accounts always ask for an authenticator code. It is set up at sign-in.</p>
      ) : me.user.support_session ? (
        <p className="mt-2 text-sm text-ink-muted">Only the account's own people change this, not a support session.</p>
      ) : codes ? (
        <div role="status" className="mt-4 rounded-card border border-accent bg-accent-soft p-4">
          <p className="text-sm text-ink-strong">Two-step sign-in is on. Recovery codes</p>
          <p className="mt-1 text-xs text-ink-muted">Each signs you in once if you lose your phone. They are shown this once: store them somewhere safe now.</p>
          <ul aria-label="Recovery codes" className="num mt-3 grid grid-cols-2 gap-1.5 text-sm text-ink-strong">
            {codes.map((c) => (
              <li key={c} className="rounded-ctl border border-line bg-bg px-2 py-1 text-center">{c}</li>
            ))}
          </ul>
          <button type="button" className={`${btn.ghost} mt-3`} onClick={() => void navigator.clipboard.writeText(codes.join("\n"))}>Copy all</button>
        </div>
      ) : on ? (
        <form onSubmit={disable} className="mt-4 space-y-4">
          <p className="text-sm text-ink">On. Every sign-in asks for a code from your authenticator app. Developer API keys are not affected.</p>
          <Field label="Code from the app" name="code" autoComplete="one-time-code" inputMode="numeric" required error={wrong} hint="To turn it off, type the code your app shows now." />
          <SubmitButton busy={busy} busyText="Checking…">Turn off</SubmitButton>
        </form>
      ) : started ? (
        <form onSubmit={confirm} className="mt-4 space-y-4">
          <p className="text-sm text-ink">Add Axon to an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password and the like), then type the code it shows.</p>
          <a href={started.otpauth_uri} className="text-sm text-accent underline underline-offset-4">Add to my authenticator app</a>
          <code aria-label="Setup key" className="num block rounded-ctl border border-line bg-bg px-3 py-2 text-sm break-all text-ink-strong">
            {started.secret.replace(/(.{4})/g, "$1 ").trim()}
          </code>
          <Field label="Code from the app" name="code" autoComplete="one-time-code" inputMode="numeric" required error={wrong} />
          <SubmitButton busy={busy} busyText="Checking…">Turn on</SubmitButton>
        </form>
      ) : (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-ink">Off. Turn it on to ask for a code from an authenticator app at every sign-in, on top of your password.</p>
          <button type="button" className={btn.primary} disabled={busy} onClick={start}>Set up</button>
        </div>
      )}
      {error !== null && !wrong && <div className="mt-4"><ErrorState error={error} /></div>}
    </section>
  );
}
