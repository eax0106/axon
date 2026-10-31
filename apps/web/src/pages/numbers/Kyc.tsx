import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Holder, useHolders } from "../../lib/billing";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Field } from "../../ui/Field";
import { ErrorState } from "../../ui/states";

/**
 * The number holder's identity, needed once before the first number: PAN, then Aadhaar through
 * DigiLocker (the holder gives consent on DigiLocker's own site and comes back here).
 */
export function Kyc({ onVerified }: { onVerified: (holder: Holder) => void }) {
  const holders = useHolders();
  const qc = useQueryClient();
  const { busy, error, run } = useAction();
  const [pending, setPending] = useState<Holder | null>(null);
  const holder = pending ?? holders.data?.find((h) => h.status === "pan_verified") ?? null;

  function verifyPan(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    void run(async () => {
      const made = await unwrap<Holder>(
        api.POST("/numbers/kyc/verify-pan", { body: { name: String(f.get("name")), pan: String(f.get("pan")).toUpperCase() } }),
      );
      setPending(made);
      void qc.invalidateQueries({ queryKey: ["numbers", "holders"] });
    });
  }

  const openDigilocker = (h: Holder) =>
    run(async () => {
      const { url } = await unwrap<{ url: string }>(
        api.POST("/numbers/kyc/digilocker/initiate", { body: { holder_id: h.id, redirect_url: `${location.origin}/numbers?kyc=${h.id}` } }),
      );
      window.open(url, "_blank", "noopener");
    });

  const checkDigilocker = (h: Holder) =>
    run(async () => {
      const done = await unwrap<Holder>(api.POST("/numbers/kyc/digilocker/verify", { body: { holder_id: h.id } }));
      void qc.invalidateQueries({ queryKey: ["numbers", "holders"] });
      if (done.status === "verified") onVerified(done);
    });

  return (
    <div className="space-y-4">
      <ol className="flex gap-6 text-sm">
        <li className={holder ? "text-accent" : "text-ink-strong"}>1 · PAN {holder && "✓"}</li>
        <li className={holder ? "text-ink-strong" : "text-ink-muted"}>2 · Aadhaar on DigiLocker</li>
      </ol>
      {!holder ? (
        <form onSubmit={verifyPan} className="space-y-3" noValidate>
          <Field label="Name as on PAN" name="name" autoComplete="name" required maxLength={200} />
          <Field label="PAN" name="pan" autoComplete="off" maxLength={10} hint="10 characters, like ABCDE1234F. Only the last four are kept." />
          <button type="submit" className={btn.primary} disabled={busy}>
            {busy ? "Checking…" : "Verify PAN"}
          </button>
        </form>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-ink">
            PAN ending <span className="num">{holder.pan_last4}</span> verified for {holder.name}. Next, confirm Aadhaar on DigiLocker; it
            opens in a new tab and nothing from Aadhaar is stored here beyond the result.
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={btn.primary} disabled={busy} onClick={() => void openDigilocker(holder)}>
              Open DigiLocker
            </button>
            <button type="button" className={btn.ghost} disabled={busy} onClick={() => void checkDigilocker(holder)}>
              I've finished on DigiLocker
            </button>
          </div>
        </div>
      )}
      {error !== null && <ErrorState error={error} />}
    </div>
  );
}
