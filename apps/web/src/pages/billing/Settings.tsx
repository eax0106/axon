import { useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";

import { api, unwrap } from "../../lib/api";
import { useBillingSettings } from "../../lib/billing";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Field } from "../../ui/Field";
import { ErrorState, Skeleton } from "../../ui/states";

/** The hourly spend cap and the details printed on GST invoices. */
export function BillingSettings() {
  const settings = useBillingSettings();
  const qc = useQueryClient();
  const { busy, error, run } = useAction();
  const d = settings.data?.details ?? {};

  function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const text = (k: string) => String(f.get(k) ?? "").trim();
    void run(async () => {
      const saved = await unwrap(
        api.PUT("/billing/settings", {
          body: {
            spend_cap_per_hour: text("cap") === "" ? null : text("cap"),
            legal_name: text("legal_name"),
            gstin: text("gstin"),
            state_code: text("state_code") || null,
            address: text("address"),
          },
        }),
      );
      qc.setQueryData(["billing", "settings"], saved);
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    });
  }

  if (settings.error) return <ErrorState error={settings.error} retry={() => void settings.refetch()} />;
  if (!settings.data) return <Skeleton className="mt-6 h-48 rounded-card" />;
  return (
    <form onSubmit={save} aria-labelledby="billing-settings" className="mt-6 rounded-card border border-line bg-surface p-6">
      <h2 id="billing-settings" className="eyebrow">Limits and invoice details</h2>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field
          label="Hourly spend cap (credits)"
          name="cap"
          inputMode="decimal"
          defaultValue={settings.data.spend_cap_per_hour === null ? "" : String(Number(settings.data.spend_cap_per_hour))}
          hint="Calls wait when an hour's spending reaches this. Leave empty for no cap."
        />
        <Field label="Legal name on invoices" name="legal_name" defaultValue={d.legal_name ?? ""} maxLength={200} />
        <Field label="GSTIN" name="gstin" defaultValue={d.gstin ?? ""} maxLength={15} hint="Optional. 15 characters, starting with your state code." />
        <Field label="State code" name="state_code" inputMode="numeric" defaultValue={d.state_code ?? ""} maxLength={2} hint="Two digits, e.g. 36 for Telangana." />
      </div>
      <div className="mt-4">
        <Field label="Billing address" name="address" defaultValue={d.address ?? ""} maxLength={500} />
      </div>
      {error !== null && (
        <div className="mt-4">
          <ErrorState error={error} />
        </div>
      )}
      <button type="submit" className={`${btn.ghost} mt-5`} disabled={busy}>
        {busy ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
