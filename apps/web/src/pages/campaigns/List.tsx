import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router";

import { api, unwrap } from "../../lib/api";
import { type Campaign, useCampaigns } from "../../lib/campaigns";
import { useEmployees } from "../../lib/employees";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Field, Select } from "../../ui/Field";
import { ErrorState, Skeleton } from "../../ui/states";

export const CAMPAIGN_STATUS: Record<Campaign["status"], { label: string; dot: string }> = {
  draft: { label: "Draft", dot: "bg-ink-muted" },
  scheduled: { label: "Scheduled", dot: "bg-info" },
  running: { label: "Running", dot: "live-dot bg-accent" },
  paused: { label: "Paused", dot: "bg-warn" },
  completed: { label: "Completed", dot: "bg-accent" },
  canceled: { label: "Cancelled", dot: "bg-ink-muted" },
};

export default function Campaigns() {
  const campaigns = useCampaigns();
  const employees = useEmployees().data ?? [];
  const nameOf = (id: string) => employees.find((e) => e.id === id)?.name ?? "Removed employee";
  return (
    <>
      <p className="eyebrow">Bulk</p>
      <h1 className="display mt-3 text-4xl">Campaigns</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">Work through a list at the hours and pace you set. Every number is checked against your do-not-call list before each dial.</p>
      <NewCampaign />
      <section aria-label="Campaigns" className="mt-10">
        {campaigns.error ? (
          <ErrorState error={campaigns.error} retry={() => void campaigns.refetch()} />
        ) : !campaigns.data ? (
          <Skeleton className="h-40 rounded-card" />
        ) : campaigns.data.length === 0 ? (
          <p className="rounded-card border border-dashed border-line p-10 text-center text-ink-muted">No campaigns yet.</p>
        ) : (
          <ul className="grid gap-3 md:grid-cols-2">
            {campaigns.data.map((c) => {
              const counts = c.contacts as Record<string, number>;
              const total = Object.values(counts).reduce((a, b) => a + b, 0);
              const done = (counts.done ?? 0) + (counts.exhausted ?? 0) + (counts.skipped ?? 0) + (counts.canceled ?? 0);
              return (
                <li key={c.id}>
                  <Link to={`/campaigns/${c.id}`} className="block rounded-card border border-line bg-surface p-5 transition-colors duration-150 hover:border-line-accent">
                    <div className="flex items-start justify-between gap-3">
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink-strong">{c.name}</span>
                        <span className="block text-sm text-ink-muted">{nameOf(c.employee_id)}</span>
                      </span>
                      <span className="eyebrow inline-flex items-center gap-1.5 text-ink-muted">
                        <span aria-hidden className={`size-1.5 rounded-full ${CAMPAIGN_STATUS[c.status].dot}`} />
                        {CAMPAIGN_STATUS[c.status].label}
                      </span>
                    </div>
                    <div className="mt-4 h-1 overflow-hidden rounded-full bg-line" aria-hidden>
                      <div className="h-full origin-left rounded-full bg-accent" style={{ transform: `scaleX(${total ? done / total : 0})` }} />
                    </div>
                    <p className="num mt-2 text-xs text-ink-muted">{done} of {total} contacts finished</p>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </>
  );
}

function NewCampaign() {
  const bulk = (useEmployees().data ?? []).filter((e) => e.channel === "bulk");
  const navigate = useNavigate();
  const [employee, setEmployee] = useState("");
  const { busy, error, run } = useAction();
  function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name")).trim();
    void run(async () => {
      const made = await unwrap<Campaign>(api.POST("/campaigns", { body: { employee_id: employee || bulk[0]?.id || "", name } }));
      navigate(`/campaigns/${made.id}`);
    });
  }
  if (bulk.length === 0)
    return (
      <p className="mt-8 text-sm text-ink-muted">
        Campaigns are run by a Bulk employee.{" "}
        <Link to="/employees/new" className="text-accent underline underline-offset-4">Hire one</Link> first.
      </p>
    );
  return (
    <form onSubmit={create} className="mt-8 grid max-w-3xl gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <Field label="New campaign" name="name" placeholder="Diwali offer, Kokapet enquiries" required maxLength={200} />
      <Select label="Run by" value={employee || bulk[0]?.id || ""} onChange={setEmployee} options={bulk.map((e) => [e.id, e.name])} />
      <button type="submit" className={`${btn.primary} h-12`} disabled={busy}>Create</button>
      {error !== null && <div className="sm:col-span-3"><ErrorState error={error} /></div>}
    </form>
  );
}
