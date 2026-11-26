import { type FormEvent, useEffect, useState } from "react";

import { ApiError, api, unwrap } from "../lib/api";
import { btn } from "../ui/buttons";
import { Field, SubmitButton } from "../ui/Field";

function reason(error: unknown): string {
  if (!(error instanceof ApiError)) return "Couldn't reach Axon. Check your connection and try again.";
  if (error.status === 401) return "That code isn't right. Use the newest code in your authenticator app.";
  if (error.status === 429) return "Too many tries. Wait 15 minutes, then sign in again.";
  if (error.status === 422) return "Enter the six-digit code from your authenticator app.";
  return error.message;
}

/** The staff sign-in step after the password: a code from the authenticator app, or a recovery code. */
export function VerifyCode({ challenge, onSession }: { challenge: string; onSession: (token: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code")).trim();
    setBusy(true);
    setError(null);
    try {
      const r = await unwrap(api.POST("/auth/second-factor/verify", { body: { challenge, code } }));
      onSession(r.access_token);
    } catch (err) {
      setError(reason(err));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
      <Field
        label="Code"
        name="code"
        autoComplete="one-time-code"
        inputMode="text"
        required
        autoFocus
        hint="Six digits from your authenticator app, or one of your recovery codes."
      />
      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}
      <SubmitButton busy={busy} busyText="Checking…">
        Sign in
      </SubmitButton>
    </form>
  );
}

type Started = { secret: string; otpauth_uri: string };

/** First staff sign-in: set up an authenticator app, prove it with one code, keep the recovery codes. */
export function EnrolCode({ challenge, onSession }: { challenge: string; onSession: (token: string) => void }) {
  const [started, setStarted] = useState<Started | null>(null);
  const [done, setDone] = useState<{ token: string; codes: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    let live = true;
    unwrap(api.POST("/auth/second-factor/enrol", { body: { challenge } }))
      .then((r) => live && setStarted(r))
      .catch((err: unknown) => live && setError(err instanceof ApiError && err.status === 401 ? "This sign-in expired. Go back and sign in again." : reason(err)));
    return () => {
      live = false;
    };
  }, [challenge]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code")).trim();
    setBusy(true);
    setError(null);
    try {
      const r = await unwrap(api.POST("/auth/second-factor/confirm", { body: { challenge, code } }));
      setDone({ token: r.access_token, codes: r.recovery_codes });
    } catch (err) {
      setError(reason(err));
      setBusy(false);
    }
  }

  const copy = (what: string, value: string) => void navigator.clipboard.writeText(value).then(() => setCopied(what));

  if (done) {
    return (
      <div className="mt-8 space-y-4">
        <div role="status" className="rounded-card border border-accent bg-accent-soft p-4">
          <p className="text-sm text-ink-strong">Recovery codes</p>
          <p className="mt-1 text-xs text-ink-muted">
            Each one signs you in once if you lose your phone. Store them somewhere safe now: they are shown this once.
          </p>
          <ul aria-label="Recovery codes" className="num mt-3 grid grid-cols-2 gap-1.5 text-sm text-ink-strong">
            {done.codes.map((c) => (
              <li key={c} className="rounded-ctl border border-line bg-bg px-2 py-1 text-center">
                {c}
              </li>
            ))}
          </ul>
          <button type="button" className={`${btn.ghost} mt-3`} onClick={() => copy("codes", done.codes.join("\n"))}>
            {copied === "codes" ? "Copied" : "Copy all"}
          </button>
        </div>
        <button type="button" className={`${btn.primary} w-full`} onClick={() => onSession(done.token)}>
          I've saved them. Continue
        </button>
      </div>
    );
  }

  return (
    <div className="mt-8 space-y-4">
      <p className="text-sm text-ink">
        Staff accounts need a second factor. Add Axon to an authenticator app (Google Authenticator, Microsoft
        Authenticator, 1Password and the like), then type the code it shows.
      </p>
      {started && (
        <div className="space-y-3 rounded-card border border-line p-4">
          <p className="text-xs text-ink-muted">On this phone? Open the link. Otherwise type the key into the app.</p>
          <a href={started.otpauth_uri} className="text-sm text-accent underline underline-offset-4">
            Add to my authenticator app
          </a>
          <div className="flex flex-wrap items-center gap-2">
            <code aria-label="Setup key" className="num min-w-0 flex-1 rounded-ctl border border-line bg-bg px-3 py-2 text-sm break-all text-ink-strong">
              {started.secret.replace(/(.{4})/g, "$1 ").trim()}
            </code>
            <button type="button" className={btn.ghost} onClick={() => copy("key", started.secret)}>
              {copied === "key" ? "Copied" : "Copy key"}
            </button>
          </div>
          <p className="text-xs text-ink-muted">Time-based, six digits, every 30 seconds.</p>
        </div>
      )}
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Code from the app" name="code" autoComplete="one-time-code" inputMode="numeric" required />
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <SubmitButton busy={busy || !started} busyText={started ? "Checking…" : "Preparing…"}>
          Turn on and sign in
        </SubmitButton>
      </form>
    </div>
  );
}
