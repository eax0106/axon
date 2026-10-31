import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { ApiError, api, unwrap } from "../lib/api";
import { signIn } from "../lib/queries";
import { Field, SubmitButton } from "../ui/Field";
import { AuthLayout } from "./AuthLayout";

type Errors = Partial<Record<"account_name" | "email" | "password" | "form", string>>;

/** Checked here so the owner hears about a short password before a round trip; the API checks again. */
function check(form: FormData): Errors {
  const errors: Errors = {};
  if (!String(form.get("account_name")).trim()) errors.account_name = "Enter your business name.";
  if (!/^\S+@\S+\.\S+$/.test(String(form.get("email")))) errors.email = "Enter a valid email address.";
  if (String(form.get("password")).length < 8) errors.password = "Use at least 8 characters.";
  return errors;
}

function reason(error: unknown): Errors {
  if (!(error instanceof ApiError)) return { form: "Couldn't reach Axon. Check your connection and try again." };
  if (error.status === 409) return { email: "This email already has an account. Sign in instead." };
  if (error.status === 429) return { form: "Too many sign-ups from this network. Try again in an hour." };
  return { form: error.message };
}

export default function SignUp() {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const found = check(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const { access_token } = await unwrap(
        api.POST("/auth/signup", {
          body: {
            account_name: String(form.get("account_name")).trim(),
            email: String(form.get("email")).trim(),
            password: String(form.get("password")),
          },
        }),
      );
      signIn(access_token);
      navigate("/", { replace: true });
    } catch (err) {
      setErrors(reason(err));
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      eyebrow="Create your account"
      title="Hire your first AI employee."
      sub="Free credits to start. No card needed."
    >
      <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
        <Field
          label="Business name"
          name="account_name"
          autoComplete="organization"
          maxLength={200}
          error={errors.account_name}
          hint="Any language. Your AI employees introduce your business by this name."
        />
        <Field label="Email" name="email" type="email" autoComplete="email" maxLength={320} error={errors.email} />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="new-password"
          maxLength={128}
          error={errors.password}
          hint="At least 8 characters."
        />
        {errors.form && (
          <p role="alert" className="text-sm text-danger">
            {errors.form}
          </p>
        )}
        <SubmitButton busy={busy} busyText="Creating your account…">
          Create account
        </SubmitButton>
      </form>
      <p className="mt-6 text-sm text-ink-muted">
        Already have an account?{" "}
        <Link to="/sign-in" className="text-accent underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
