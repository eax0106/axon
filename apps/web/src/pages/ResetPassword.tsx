import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { ApiError, api, unwrap } from "../lib/api";
import { Field, SubmitButton } from "../ui/Field";
import { AuthLayout } from "./AuthLayout";
import { linkToken } from "./Join";

/** The emailed reset link: choose a new password. Every session is signed out; sign in again. */
export default function ResetPassword() {
  const token = linkToken();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const password = String(new FormData(e.currentTarget).get("password"));
    setBusy(true);
    setError(null);
    try {
      await unwrap(api.POST("/auth/password-reset/confirm", { body: { token, password } }));
      setDone(true);
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setError(status === 410 ? "This link was used or has expired. Ask for a new one." : status === 422 ? "Choose a password of at least 8 characters." : err instanceof Error ? err.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout eyebrow="Password" title="Choose a new password." sub="Every device is signed out once it is set.">
      {done ? (
        <p role="status" className="mt-8 text-sm text-ink">
          Password changed.{" "}
          <Link to="/sign-in" className="text-accent underline underline-offset-4">Sign in</Link>
        </p>
      ) : (
        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field label="New password" name="password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required hint="At least 8 characters." />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <SubmitButton busy={busy} busyText="Saving…">Set password</SubmitButton>
        </form>
      )}
    </AuthLayout>
  );
}
