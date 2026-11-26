import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { ApiError, api, unwrap } from "../lib/api";
import { Field, SubmitButton } from "../ui/Field";
import { AuthLayout } from "./AuthLayout";

/** Ask for a reset link. The answer is the same whether or not the email has a sign-in. */
export default function ForgotPassword() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const email = String(new FormData(e.currentTarget).get("email"));
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/auth/password-reset", { body: { email } }));
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429 ? "Too many tries. Wait 15 minutes." : err instanceof ApiError && err.status === 422 ? "Enter your email address." : err instanceof Error ? err.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout eyebrow="Password" title="Forgot your password?" sub="We'll email you a link to choose a new one.">
      {sent ? (
        <p role="status" className="mt-8 text-sm text-ink">
          If that email has an Axon sign-in, a link is on its way. It works once, for 1 hour.
        </p>
      ) : (
        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field label="Email" name="email" type="email" autoComplete="email" required />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <SubmitButton busy={busy} busyText="Sending…">Email me a link</SubmitButton>
        </form>
      )}
      <p className="mt-6 text-sm text-ink-muted">
        <Link to="/sign-in" className="text-accent underline underline-offset-4">Back to sign in</Link>
      </p>
    </AuthLayout>
  );
}
