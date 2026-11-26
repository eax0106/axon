import { type FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, api, unwrap } from "../lib/api";
import { signIn } from "../lib/queries";
import { Field, SubmitButton } from "../ui/Field";
import { AuthLayout } from "./AuthLayout";

/** The token rides after `#` in emailed links, so it never reaches a server log. */
export const linkToken = () => window.location.hash.slice(1);

const gone = (error: unknown) => error instanceof ApiError && error.status === 410;

/** An invited colleague opens the emailed link, chooses a password and is signed in as a member. */
export default function Join() {
  const navigate = useNavigate();
  const token = linkToken();
  const [invite, setInvite] = useState<{ email: string; account_name: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    unwrap(api.POST("/auth/invites/check", { body: { token } }))
      .then((r) => live && setInvite(r))
      .catch((err: unknown) => live && setError(gone(err) || !token ? "This invite was used, cancelled or has expired. Ask for a new one." : "Couldn't reach Axon. Try again."));
    return () => {
      live = false;
    };
  }, [token]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const password = String(new FormData(e.currentTarget).get("password"));
    setBusy(true);
    setError(null);
    try {
      const r = await unwrap(api.POST("/auth/invites/accept", { body: { token, password } }));
      signIn(r.access_token);
      navigate("/", { replace: true });
    } catch (err) {
      setError(gone(err) ? "This invite was used, cancelled or has expired. Ask for a new one." : err instanceof ApiError && err.status === 422 ? "Choose a password of at least 8 characters." : err instanceof Error ? err.message : "Try again.");
      setBusy(false);
    }
  }

  return (
    <AuthLayout eyebrow="Join your team" title={invite ? `Join ${invite.account_name}.` : "Join your team."} sub={invite ? `You'll sign in as ${invite.email}.` : "Checking your invite…"}>
      {invite && (
        <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
          <Field label="Choose a password" name="password" type="password" autoComplete="new-password" minLength={8} maxLength={128} required hint="At least 8 characters." />
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <SubmitButton busy={busy} busyText="Joining…">Join and sign in</SubmitButton>
        </form>
      )}
      {!invite && error && (
        <p role="alert" className="mt-8 text-sm text-danger">
          {error}{" "}
          <Link to="/sign-in" className="text-accent underline underline-offset-4">Sign in</Link>
        </p>
      )}
    </AuthLayout>
  );
}
