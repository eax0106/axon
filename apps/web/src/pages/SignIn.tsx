import { type FormEvent, useState } from "react";
import { useLocation, useNavigate } from "react-router";

import { ApiError, api, session, unwrap } from "../lib/api";
import { queryClient } from "../lib/queries";

function reason(error: unknown): string {
  if (!(error instanceof ApiError)) return "Couldn't reach Axon. Check your connection and try again.";
  if (error.status === 401) return "That email and password don't match an account.";
  if (error.status === 429) return "Too many tries. Wait a few minutes, then sign in again.";
  if (error.status === 422) return "Enter your email and a password of at least 8 characters.";
  return error.message;
}

// ponytail: the plain sign-in the shell needs; F2 adds sign-up, terms and phone verification.
export default function SignIn() {
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await unwrap<{ access_token: string }>(
        api.POST("/auth/login", {
          body: { email: String(form.get("email")), password: String(form.get("password")) },
        }),
      );
      queryClient.clear();
      session.set(access_token);
      navigate(from, { replace: true });
    } catch (err) {
      setError(reason(err));
      setBusy(false);
    }
  }

  return (
    <main className="glow grid min-h-dvh place-items-center px-4">
      <div className="page-in w-full max-w-sm">
        <p className="eyebrow">Axon · Sign in</p>
        <h1 className="display mt-3 text-4xl">Welcome back.</h1>
        <p className="mt-2 text-ink-muted">Your AI employees kept working while you were away.</p>
        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field label="Email" name="email" type="email" autoComplete="email" />
          <Field label="Password" name="password" type="password" autoComplete="current-password" />
          {error && (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="h-12 w-full rounded-ctl bg-btn font-medium text-accent-ink transition-[transform,opacity] duration-150 active:scale-[0.98] disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}

function Field(props: { label: string; name: string; type: string; autoComplete: string }) {
  return (
    <label className="block">
      <span className="text-sm text-ink">{props.label}</span>
      <input
        required
        name={props.name}
        type={props.type}
        autoComplete={props.autoComplete}
        className="mt-1.5 h-12 w-full rounded-ctl border border-line-accent bg-surface px-3.5 text-ink-strong transition-colors duration-150 outline-none focus:border-accent"
      />
    </label>
  );
}
