import { type FormEvent, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { ApiError, api, unwrap } from "../lib/api";
import { signIn } from "../lib/queries";
import { Field, SubmitButton } from "../ui/Field";
import { AuthLayout } from "./AuthLayout";

function reason(error: unknown): string {
  if (!(error instanceof ApiError)) return "Couldn't reach Axon. Check your connection and try again.";
  if (error.status === 401) return "That email and password don't match an account.";
  if (error.status === 429) return "Too many tries. Wait 15 minutes, then sign in again.";
  if (error.status === 422) return "Enter your email and a password of at least 8 characters.";
  return error.message;
}

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
      const { access_token } = await unwrap(
        api.POST("/auth/login", {
          body: { email: String(form.get("email")), password: String(form.get("password")) },
        }),
      );
      signIn(access_token);
      navigate(from, { replace: true });
    } catch (err) {
      setError(reason(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout eyebrow="Sign in" title="Welcome back." sub="Your AI employees kept working while you were away.">
      <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
        <Field label="Email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required />
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <SubmitButton busy={busy} busyText="Signing in…">
          Sign in
        </SubmitButton>
      </form>
      <p className="mt-6 text-sm text-ink-muted">
        New to Axon?{" "}
        <Link to="/sign-up" className="text-accent underline-offset-4 hover:underline">
          Create an account
        </Link>
      </p>
    </AuthLayout>
  );
}
