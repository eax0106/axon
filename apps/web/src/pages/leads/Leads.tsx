import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import { type LeadRow, OUTCOME, download, useBoard, useLeads } from "../../lib/data";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";

type View = "table" | "cards" | "board";
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "–");
const BASE = ["phone", "name", "created_at", "calls", "last_call_at", "last_outcome", "summary", "memory"];

export default function Leads() {
  const [view, setView] = useState<View>(() => {
    try {
      return (localStorage.getItem("axon.leads.view") as View) || "table";
    } catch {
      return "table";
    }
  });
  const [q, setQ] = useState("");
  const [outcome, setOutcome] = useState("");
  const pick = (v: View) => {
    setView(v);
    try {
      localStorage.setItem("axon.leads.view", v);
    } catch {
      /* remembered for this visit only */
    }
  };

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow">Leads</p>
          <h1 className="display mt-3 text-4xl">Everyone you've talked to</h1>
          <p className="mt-2 text-ink-muted">One lead per phone number, across every channel.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ExportLeads q={q} outcome={outcome} />
          <CallerMemory />
        </div>
      </div>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <label htmlFor="lead-q" className="sr-only">Search leads</label>
        <input id="lead-q" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or phone"
          className="h-10 min-w-0 flex-1 rounded-ctl border border-line-accent bg-surface px-3 text-sm text-ink-strong outline-none focus:border-accent sm:max-w-72" />
        {view !== "board" && (
          <select aria-label="Latest outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)}
            className="h-10 rounded-ctl border border-line bg-surface px-2 text-sm text-ink">
            <option value="">Any outcome</option>
            {Object.entries(OUTCOME).filter(([k]) => k !== "no_outcome").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        )}
        <div role="radiogroup" aria-label="View" className="ml-auto flex gap-1 rounded-ctl border border-line p-1">
          {(["table", "cards", "board"] as const).map((v) => (
            <button key={v} type="button" role="radio" aria-checked={view === v} onClick={() => pick(v)}
              className="rounded-tag px-2.5 py-1 text-sm text-ink-muted capitalize aria-checked:bg-accent-soft aria-checked:text-ink-strong">
              {v === "board" ? "By outcome" : v}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-6">{view === "board" ? <Board q={q} /> : <List q={q} outcome={outcome} cards={view === "cards"} />}</div>
    </>
  );
}

function List({ q, outcome, cards }: { q: string; outcome: string; cards: boolean }) {
  const leads = useLeads(q, outcome);
  if (leads.error) return <ErrorState error={leads.error} retry={() => void leads.refetch()} />;
  if (!leads.data) return <Skeleton className="h-64 rounded-card" />;
  const items = leads.data.items;
  if (items.length === 0) return <p className="rounded-card border border-dashed border-line p-10 text-center text-sm text-ink-muted">No leads yet. They appear after your employees' first calls.</p>;
  if (cards)
    return (
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((l) => (
          <li key={l.id}><LeadCard lead={l} /></li>
        ))}
      </ul>
    );
  return (
    <div className="overflow-x-auto rounded-card border border-line" tabIndex={0} role="region" aria-label="Leads table">
      <table className="w-full min-w-[600px] text-sm">
        <thead className="text-left text-xs text-ink-muted">
          <tr className="border-b border-line">
            <th className="px-4 py-3 font-medium">Lead</th>
            <th className="px-4 py-3 font-medium">Latest outcome</th>
            <th className="px-4 py-3 text-right font-medium">Calls</th>
            <th className="px-4 py-3 text-right font-medium">Last call</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.map((l) => (
            <tr key={l.id} className="transition-colors duration-150 hover:bg-accent-soft">
              <td className="px-4 py-3">
                <Link to={`/leads/${l.id}`} className="block text-ink-strong hover:text-accent">{l.name || l.phone}</Link>
                {l.name && <span className="num text-xs text-ink-muted">{l.phone}</span>}
              </td>
              <td className="px-4 py-3 text-ink">{l.last_outcome ? OUTCOME[l.last_outcome] ?? l.last_outcome : "–"}</td>
              <td className="num px-4 py-3 text-right text-ink">{l.calls}</td>
              <td className="px-4 py-3 text-right text-ink-muted">{when(l.last_call_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LeadCard({ lead: l }: { lead: LeadRow }) {
  return (
    <Link to={`/leads/${l.id}`} className="block rounded-card border border-line bg-surface p-4 transition-colors duration-150 hover:border-line-accent">
      <p className="truncate font-medium text-ink-strong">{l.name || l.phone}</p>
      <p className="num text-xs text-ink-muted">{l.phone}</p>
      <p className="mt-3 flex justify-between text-sm">
        <span className="text-ink">{l.last_outcome ? OUTCOME[l.last_outcome] ?? l.last_outcome : "Not called yet"}</span>
        <span className="text-ink-muted">{l.calls} call{l.calls === 1 ? "" : "s"}</span>
      </p>
    </Link>
  );
}

/** Columns by the outcome of each lead's latest call. Read-only: an outcome comes from a call. */
function Board({ q }: { q: string }) {
  const board = useBoard(q);
  if (board.error) return <ErrorState error={board.error} retry={() => void board.refetch()} />;
  if (!board.data) return <Skeleton className="h-64 rounded-card" />;
  const keys = Object.keys(OUTCOME).filter((k) => board.data.counts[k]);
  if (keys.length === 0) return <p className="rounded-card border border-dashed border-line p-10 text-center text-sm text-ink-muted">No leads yet.</p>;
  return (
    <div className="flex gap-4 overflow-x-auto pb-2" tabIndex={0} role="region" aria-label="Leads by outcome">
      {keys.map((k) => (
        <section key={k} aria-label={OUTCOME[k]} className="w-72 shrink-0">
          <h2 className="eyebrow flex justify-between px-1"><span>{OUTCOME[k]}</span><span className="num text-ink-muted">{board.data.counts[k]}</span></h2>
          <ul className="mt-3 space-y-2">
            {(board.data.columns[k] ?? []).map((l) => <li key={l.id}><LeadCard lead={l} /></li>)}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** CSV with only the columns the owner ticks, including any field their calls captured. */
function ExportLeads({ q, outcome }: { q: string; outcome: string }) {
  const leads = useLeads(q, outcome);
  const custom = [...new Set((leads.data?.items ?? []).flatMap((l) => Object.keys(l.fields)))].map((f) => `field:${f}`);
  const [chosen, setChosen] = useState<string[]>(["phone", "name", "last_outcome", "calls"]);
  const { busy, error, run } = useAction();
  const toggle = (f: string) => setChosen((c) => (c.includes(f) ? c.filter((x) => x !== f) : [...c, f]));
  const query = new URLSearchParams({ fields: chosen.join(","), ...(q ? { q } : {}), ...(outcome ? { outcome } : {}) }).toString();
  return (
    <Dialog.Root>
      <Dialog.Trigger className={btn.ghost}>Export CSV</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-deep/70 backdrop-blur-sm" />
        <Dialog.Content className="pop-in fixed top-1/2 left-1/2 z-50 w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-card border border-line-accent bg-surface p-6">
          <Dialog.Title className="display text-xl">Export leads</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-ink-muted">Choose the columns. The search and outcome filter on the page apply.</Dialog.Description>
          <fieldset className="mt-4 grid grid-cols-2 gap-2">
            <legend className="sr-only">Columns</legend>
            {[...BASE, ...custom].map((f) => (
              <label key={f} className="flex items-center gap-2 text-sm text-ink">
                <input type="checkbox" checked={chosen.includes(f)} onChange={() => toggle(f)} className="accent-[var(--accent)]" />
                <span className="num truncate">{f.replace("field:", "")}</span>
              </label>
            ))}
          </fieldset>
          {error !== null && <p className="mt-3 text-sm text-danger">{(error as Error).message}</p>}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className={btn.quiet}>Cancel</Dialog.Close>
            <button type="button" className={btn.primary} disabled={busy || chosen.length === 0} onClick={() => void run(() => download(`/leads/export.csv?${query}`, "leads.csv"))}>
              {busy ? "Exporting…" : "Download"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** The account switch: remember callers across calls, and forget everyone at once. */
function CallerMemory() {
  const qc = useQueryClient();
  const setting = useQuery({ queryKey: ["caller-memory"], queryFn: () => unwrap(api.GET("/account/caller-memory")) });
  const { error, run } = useAction();
  const on = setting.data?.enabled ?? false;
  return (
    <div className="flex items-center gap-2">
      <label className="flex items-center gap-2 rounded-ctl border border-line px-3 py-1.5 text-sm text-ink">
        <input type="checkbox" role="switch" checked={on} disabled={!setting.data}
          onChange={(e) => void run(async () => { qc.setQueryData(["caller-memory"], await unwrap(api.PUT("/account/caller-memory", { body: { enabled: e.target.checked } }))); })}
          className="accent-[var(--accent)]" />
        Caller memory
      </label>
      <Confirm danger trigger={<button type="button" className={btn.quiet}>Forget everyone</button>}
        title="Forget every caller?" body="What your employees remember about each caller is deleted. Calls, transcripts and leads stay." action="Forget"
        onConfirm={() => void run(async () => { await unwrap(api.DELETE("/account/caller-memory/data")); await qc.invalidateQueries({ queryKey: ["leads"] }); })} />
      {error !== null && <span className="text-xs text-danger">{(error as Error).message}</span>}
    </div>
  );
}
