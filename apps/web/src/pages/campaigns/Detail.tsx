import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";

import { api, unwrap } from "../../lib/api";
import { type Campaign, type Capacity, useCampaign, useCampaignAction, useContacts, useLive } from "../../lib/campaigns";
import { download } from "../../lib/data";
import { useEmployees } from "../../lib/employees";
import { credits } from "../../lib/format";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";
import { Analytics } from "./Analytics";
import { Constellation } from "./Constellation";
import { AddContacts, ContactTable } from "./Contacts";
import { CAMPAIGN_STATUS } from "./List";
import { CampaignSettingsForm } from "./Settings";

const EDITABLE = new Set(["draft", "scheduled", "paused"]);
const TABS = ["Live", "Contacts", "Settings", "Analytics"] as const;

export default function CampaignDetail() {
  const { id = "" } = useParams();
  const campaign = useCampaign(id);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Live");
  const employees = useEmployees().data ?? [];
  const c = campaign.data;
  if (campaign.error) return <ErrorState error={campaign.error} retry={() => void campaign.refetch()} />;
  if (!c) return <Skeleton className="h-96 rounded-card" />;
  const editable = EDITABLE.has(c.status);

  return (
    <div>
      <p className="eyebrow">Campaign</p>
      <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-4xl">{c.name}</h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink-muted">
            <span aria-hidden className={`size-1.5 rounded-full ${CAMPAIGN_STATUS[c.status].dot}`} />
            {CAMPAIGN_STATUS[c.status].label} · run by {employees.find((e) => e.id === c.employee_id)?.name ?? "a removed employee"}
            {c.scheduled_at && c.status === "scheduled" && ` · starts ${new Date(c.scheduled_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`}
          </p>
          {c.note && <p className="mt-2 text-sm text-warn">● {c.note}</p>}
        </div>
        <Actions campaign={c} />
      </div>

      <div role="tablist" aria-label="Campaign" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className="-mb-px border-b-2 border-transparent px-3.5 py-2.5 text-sm whitespace-nowrap text-ink-muted transition-colors duration-150 hover:text-ink aria-selected:border-accent aria-selected:text-ink-strong">
            {t}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="mt-8">
        {tab === "Live" && <LiveTab campaign={c} />}
        {tab === "Contacts" && (
          <div className="space-y-10">
            <AddContacts campaignId={c.id} editable={editable} />
            <ContactTable campaignId={c.id} live={c.status === "running"} />
          </div>
        )}
        {tab === "Settings" && <CampaignSettingsForm campaign={c} editable={editable} />}
        {tab === "Analytics" && <Analytics campaignId={c.id} />}
      </div>
    </div>
  );
}

function LiveTab({ campaign: c }: { campaign: Campaign }) {
  const running = c.status === "running";
  const live = useLive(c.id, running);
  const contacts = useContacts(c.id, running);
  return (
    <div className="space-y-6">
      {contacts.data ? <Constellation contacts={contacts.data.contacts} total={contacts.data.total} /> : <Skeleton className="h-64 rounded-card" />}
      {live.data && (
        <div className="grid gap-6 md:grid-cols-2">
          <section aria-labelledby="calling-now" className="rounded-card border border-line bg-surface p-6">
            <h2 id="calling-now" className="eyebrow">Calling now · {live.data.calling_now.length}</h2>
            <ul className="mt-3 divide-y divide-line">
              {live.data.calling_now.map((x) => (
                <li key={x.call_id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                  <span className="flex items-center gap-2"><span aria-hidden className="live-dot size-2 rounded-full bg-accent" />{x.name || x.phone}</span>
                  <Link to={`/calls/${x.call_id}/live`} className="text-xs text-accent">Listen in</Link>
                </li>
              ))}
              {live.data.calling_now.length === 0 && <li className="py-3 text-sm text-ink-muted">{running ? "Between calls." : "Nobody right now."}</li>}
            </ul>
          </section>
          <section aria-labelledby="callbacks" className="rounded-card border border-line bg-surface p-6">
            <h2 id="callbacks" className="eyebrow">Call-backs asked for · {live.data.callbacks.length}</h2>
            <ul className="mt-3 divide-y divide-line">
              {live.data.callbacks.map((x) => (
                <li key={x.contact_id} className="flex justify-between gap-3 py-2.5 text-sm">
                  <span className="text-ink">{x.name || x.phone}</span>
                  <span className="text-ink-muted">{x.at ? new Date(x.at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : ""}</span>
                </li>
              ))}
              {live.data.callbacks.length === 0 && <li className="py-3 text-sm text-ink-muted">None waiting.</li>}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}

/** What can be done to the campaign as a whole, shown only when it applies. */
function Actions({ campaign: c }: { campaign: Campaign }) {
  const action = useCampaignAction(c.id);
  const at = { params: { path: { campaign_id: c.id } } };
  const counts = c.contacts as Record<string, number>;
  const closed = c.status === "completed" || c.status === "canceled";
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="flex flex-wrap justify-end gap-2">
        {(c.status === "draft" || c.status === "scheduled") && <Start campaign={c} />}
        {c.status === "running" && <button type="button" className={btn.ghost} onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/pause", at)))}>Pause</button>}
        {c.status === "paused" && (c.consent_given ? (
          <button type="button" className={btn.primary} onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/resume", at)))}>Resume</button>
        ) : <Start campaign={c} label="Confirm and resume" />)}
        <button type="button" className={btn.quiet} onClick={() => action.mutate(() => download(`/campaigns/${c.id}/export.csv`, `${c.name}.csv`))}>Export CSV</button>
        {!closed && (
          <Confirm danger trigger={<button type="button" className={btn.danger}>Cancel campaign</button>} title={`Cancel ${c.name}?`}
            body="No more calls are placed for it. Calls already on the line finish. This cannot be undone." action="Cancel campaign"
            onConfirm={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/cancel", at)))} />
        )}
      </div>
      <div className="flex flex-wrap justify-end gap-x-4 text-xs">
        {(counts.exhausted ?? 0) > 0 && <button type="button" className="text-ink-muted hover:text-accent" onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/retry-exhausted", at)))}>Retry {counts.exhausted} unanswered</button>}
        {(counts.callback ?? 0) > 0 && <button type="button" className="text-ink-muted hover:text-danger" onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/cancel-callbacks", at)))}>Cancel {counts.callback} call-backs</button>}
        {((counts.canceled ?? 0) > 0 || (counts.skipped ?? 0) > 0) && !closed && <button type="button" className="text-ink-muted hover:text-accent" onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/restore-not-called", at)))}>Restore not called</button>}
      </div>
      {action.error && <div className="max-w-md"><ErrorState error={action.error} /></div>}
    </div>
  );
}

/** Consent first (the exact words are stored with who and when), then start now or at a time. */
function Start({ campaign: c, label = "Start" }: { campaign: Campaign; label?: string }) {
  const [open, setOpen] = useState(false);
  const [agree, setAgree] = useState(c.consent_given);
  const [later, setLater] = useState("");
  const action = useCampaignAction(c.id);
  const at = { params: { path: { campaign_id: c.id } } };
  const capacity = useQuery({ queryKey: ["campaigns", c.id, "capacity"], enabled: open, queryFn: () => unwrap<Capacity>(api.GET("/campaigns/{campaign_id}/capacity", at)) });
  const go = () =>
    action.mutate(async () => {
      if (!c.consent_given) await unwrap(api.POST("/campaigns/{campaign_id}/consent", { ...at, body: { confirm: true } }));
      if (c.status === "paused") await unwrap(api.POST("/campaigns/{campaign_id}/resume", at));
      else await unwrap(api.POST("/campaigns/{campaign_id}/start", { ...at, body: later ? { start_at: new Date(later).toISOString() } : null }));
      setOpen(false);
    });
  const k = capacity.data;
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger className={btn.primary}>{label}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-deep/70 backdrop-blur-sm" />
        <Dialog.Content className="pop-in fixed top-1/2 left-1/2 z-50 max-h-[90dvh] w-[min(520px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-line-accent bg-surface p-6">
          <Dialog.Title className="display text-xl">Start {c.name}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink-muted">Check the estimate, confirm the list may be called, and go.</Dialog.Description>
          {k && (
            <dl className="mt-4 divide-y divide-line text-sm">
              <div className="flex justify-between py-2"><dt className="text-ink-muted">Contacts to call</dt><dd className="num">{k.remaining_contacts}</dd></div>
              <div className="flex justify-between py-2"><dt className="text-ink-muted">Calls at once</dt><dd className="num">{k.parallel_calls} <span className="text-ink-muted">({k.number_channels} line{k.number_channels === 1 ? "" : "s"} on the number)</span></dd></div>
              <div className="flex justify-between py-2"><dt className="text-ink-muted">Working days needed</dt><dd className="num">{k.working_days_needed ?? "–"}</dd></div>
              <div className="flex justify-between py-2"><dt className="text-ink-muted">Cost if everyone answers</dt><dd className={`num ${k.enough_credits ? "" : "text-warn"}`}>{credits(k.estimated_cost)} of {credits(k.credit_balance)}</dd></div>
              {k.queue_ahead > 0 && <p className="py-2 text-xs text-ink-muted">{k.queue_ahead} older campaign{k.queue_ahead === 1 ? "" : "s"} on this number go first.</p>}
            </dl>
          )}
          {capacity.error && <div className="mt-4"><ErrorState error={capacity.error} /></div>}
          <label className="mt-5 flex items-start gap-3 rounded-ctl border border-line-accent bg-bg p-4 text-sm">
            <input type="checkbox" checked={agree} disabled={c.consent_given} onChange={(e) => setAgree(e.target.checked)} className="mt-0.5 accent-[var(--accent)]" />
            <span className="text-ink">{c.consent_statement}</span>
          </label>
          <p className="mt-2 text-xs text-ink-muted">Your confirmation is kept with your name and the time, as the law expects.</p>
          {c.status !== "paused" && (
            <label className="mt-4 block text-sm">
              <span className="text-ink">Start later (optional)</span>
              <input type="datetime-local" value={later} onChange={(e) => setLater(e.target.value)} className="num mt-1.5 h-10 w-full rounded-ctl border border-line bg-bg px-3 text-ink-strong" />
            </label>
          )}
          {action.error && <div className="mt-4"><ErrorState error={action.error} /></div>}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className={btn.quiet}>Not now</Dialog.Close>
            <button type="button" className={btn.primary} disabled={!agree || action.isPending} onClick={go}>
              {c.status === "paused" ? "Confirm and resume" : later ? "Schedule" : "Start calling"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
