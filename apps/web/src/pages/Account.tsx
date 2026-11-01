import { type FormEvent, useState } from "react";

import { ApiError, api, unwrap } from "../lib/api";
import { queryClient, useMe } from "../lib/queries";
import { useAction } from "../lib/useAction";
import { Field, SubmitButton } from "../ui/Field";
import { ErrorState, Skeleton } from "../ui/states";
import { Dnc } from "./account/Dnc";
import { Business, Password } from "./account/Settings";

export default function Account() {
  const me = useMe();
  return (
    <>
      <p className="eyebrow">Account</p>
      <h1 className="display mt-3 text-4xl">Your account</h1>
      <p className="mt-2 max-w-xl text-ink-muted">Who you are to Axon, your business details, your password and the numbers nobody calls.</p>

      <div className="mt-10 grid max-w-4xl gap-6 lg:grid-cols-2">
        <section aria-labelledby="who" className="rounded-card border border-line bg-surface p-6">
          <h2 id="who" className="eyebrow">
            Signed in
          </h2>
          {me.error ? (
            <div className="mt-4">
              <ErrorState error={me.error} retry={() => void me.refetch()} />
            </div>
          ) : (
            <dl className="mt-4 divide-y divide-line">
              {[
                ["Business", me.data?.account.name],
                ["Email", me.data?.user.email],
                ["Role", me.data?.user.role],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4 py-3 text-sm">
                  <dt className="text-ink-muted">{label}</dt>
                  <dd className="min-w-0 truncate text-ink">{value ?? <Skeleton className="w-32" />}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>

        <section aria-labelledby="phone" className="rounded-card border border-line bg-surface p-6">
          <h2 id="phone" className="eyebrow">
            Your phone
          </h2>
          <p className="mt-2 text-sm text-ink-muted">
            Free test calls ring only this number. We prove it's yours by calling it and reading out a 6-digit code.
          </p>
          {me.data ? <OwnerPhone verified={me.data.account.owner_phone} /> : <Skeleton className="mt-6 h-12" />}
        </section>
        <Business />
        <Password />
      </div>
      <div className="mt-6 max-w-4xl">
        <Dnc />
      </div>
    </>
  );
}

const MOBILE = /^[6-9]\d{9}$/; // the API's own rule: +91 and a 10-digit Indian mobile

function OwnerPhone({ verified }: { verified: string }) {
  const [step, setStep] = useState<"show" | "number" | "code">(verified ? "show" : "number");
  const [phone, setPhone] = useState("");
  const [minutes, setMinutes] = useState(10);
  const { busy, error: failure, run } = useAction();
  const [invalid, setInvalid] = useState<string>();
  // A refusal the owner can act on (wrong code, buy a number first) belongs next to the field.
  const inline = failure instanceof ApiError && [400, 409, 429].includes(failure.status);
  const fieldError = invalid ?? (inline ? failure.message : undefined);
  const check = (ok: boolean, message: string) => {
    setInvalid(ok ? undefined : message);
    return ok;
  };

  function sendCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const digits = String(new FormData(e.currentTarget).get("phone")).replace(/\D/g, "").slice(-10);
    if (!check(MOBILE.test(digits), "Enter a 10-digit Indian mobile number.")) return;
    setPhone(digits);
    void run(async () => {
      const sent = await unwrap(api.POST("/accounts/owner-phone", { body: { phone: `+91${digits}` } }));
      setMinutes(Math.round((sent.expires_in ?? 600) / 60));
      setStep("code");
    });
  }

  function verify(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code")).trim();
    if (!check(/^\d{6}$/.test(code), "The code is 6 digits.")) return;
    void run(async () => {
      await unwrap(api.POST("/accounts/owner-phone/verify", { body: { code } }));
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      setStep("show");
    });
  }

  if (step === "show")
    return (
      <div className="mt-6 flex items-center justify-between gap-4">
        <p>
          <span className="num text-lg text-ink-strong">{verified}</span>
          <span className="eyebrow ml-3 rounded-tag bg-accent-soft px-1.5 py-0.5">● Verified</span>
        </p>
        <button type="button" onClick={() => setStep("number")} className="text-sm text-ink-muted hover:text-accent">
          Change
        </button>
      </div>
    );

  return (
    <div className="mt-6 space-y-4">
      {step === "number" ? (
        <form onSubmit={sendCode} className="space-y-4" noValidate>
          <Field
            label="Mobile number"
            name="phone"
            type="tel"
            inputMode="numeric"
            autoComplete="tel-national"
            prefix="+91"
            defaultValue={phone}
            error={fieldError}
          />
          <SubmitButton busy={busy} busyText="Calling…">
            Call me with a code
          </SubmitButton>
        </form>
      ) : (
        <form onSubmit={verify} className="space-y-4" noValidate>
          <Field
            label={`Code we read out to +91 ${phone}`}
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            autoFocus
            error={fieldError}
            hint={`Pick up the call; the code is read twice. It works for ${minutes} minutes.`}
          />
          <SubmitButton busy={busy} busyText="Checking…">
            Verify
          </SubmitButton>
          <button type="button" onClick={() => setStep("number")} className="text-sm text-ink-muted hover:text-accent">
            Use a different number or call again
          </button>
        </form>
      )}
      {failure !== null && !inline && <ErrorState error={failure} />}
    </div>
  );
}
