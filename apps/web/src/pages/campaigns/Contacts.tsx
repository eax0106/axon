import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type BulkAction, type BulkResult, bulkSummary, type Contact, type ImportReport, type Preview, SAVE_GROUPS, STATUS_LABEL, useCampaignAction, useContacts } from "../../lib/campaigns";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Field } from "../../ui/Field";
import { ErrorState } from "../../ui/states";

const at = (id: string) => ({ params: { path: { campaign_id: id } } });

/** Getting people onto the list: a file or pasted rows (mapped, never guessed), one by hand, or a saved list. */
export function AddContacts({ campaignId, editable }: { campaignId: string; editable: boolean }) {
  if (!editable) return <p className="text-sm text-ink-muted">Contacts can be added while the campaign is a draft, scheduled or paused.</p>;
  return (
    <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
      <Importer campaignId={campaignId} />
      <div className="space-y-6">
        <ByHand campaignId={campaignId} />
        <FromList campaignId={campaignId} />
        <Exclusions campaignId={campaignId} />
      </div>
    </div>
  );
}

function Importer({ campaignId }: { campaignId: string }) {
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [phone, setPhone] = useState("");
  const [name, setName] = useState("");
  const [vars, setVars] = useState<Record<string, string>>({});
  const [listName, setListName] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const action = useCampaignAction(campaignId);
  const { busy, error, run } = useAction();

  const look = () =>
    run(async () => {
      setReport(null);
      const p = await unwrap<Preview>(api.POST("/campaigns/{campaign_id}/contacts/preview", { ...at(campaignId), body: { text } }));
      setPreview(p);
      // Only an exact column name is pre-selected; anything else the owner picks.
      setPhone(p.columns.find((c) => c.toLowerCase() === "phone") ?? "");
      setName(p.columns.find((c) => c.toLowerCase() === "name") ?? "");
      setVars(Object.fromEntries(p.variables_to_map.map((v) => [v, p.columns.includes(v) ? v : ""])));
    });
  const commit = () =>
    run(async () => {
      const r = await unwrap<ImportReport>(
        api.POST("/campaigns/{campaign_id}/contacts/import", {
          ...at(campaignId),
          body: { text, format: "csv", mapping: { phone, name: name || null, variables: Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, v || null])) }, save_as_list: listName || null },
        }),
      );
      setReport(r);
      setPreview(null);
      setText("");
      action.mutate(async () => undefined);
    });

  return (
    <section aria-labelledby="import" className="rounded-card border border-line bg-surface p-6">
      <h2 id="import" className="eyebrow">Import a list</h2>
      <p className="mt-2 text-sm text-ink-muted">A CSV with a header row, or rows pasted from a spreadsheet. Up to the API's limits; a number on your do-not-call list is skipped.</p>
      {!preview ? (
        <>
          <label className="mt-4 block">
            <span className="text-sm text-ink">Choose a CSV file</span>
            <input type="file" accept=".csv,text/csv" className="mt-1.5 block w-full text-sm text-ink-muted file:mr-3 file:rounded-ctl file:border file:border-line file:bg-bg file:px-3 file:py-1.5 file:text-ink"
              onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); }} />
          </label>
          <label className="mt-4 block">
            <span className="text-sm text-ink">Or paste</span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} placeholder={"phone,name,project\n+919876543210,రవి,Kokapet"}
              className="num mt-1.5 w-full resize-y rounded-ctl border border-line-accent bg-bg px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
          </label>
          <button type="button" className={`${btn.primary} mt-3`} disabled={busy || !text.trim()} onClick={() => void look()}>Check the columns</button>
        </>
      ) : (
        <div className="mt-4 space-y-4">
          <p className="text-sm text-ink"><span className="num">{preview.rows}</span> rows, columns: <span className="num text-ink-muted">{preview.columns.join(", ")}</span></p>
          <div className="overflow-x-auto rounded-ctl border border-line" tabIndex={0} role="region" aria-label="First rows">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-line">{preview.columns.map((c) => <th key={c} className="px-3 py-2 text-left font-medium text-ink-muted">{c}</th>)}</tr></thead>
              <tbody>{preview.sample.map((r, i) => <tr key={i} className="border-b border-line last:border-0">{preview.columns.map((c) => <td key={c} className="px-3 py-1.5 text-ink">{r[c]}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Pick label="Phone column" value={phone} onChange={setPhone} columns={preview.columns} required />
            <Pick label="Name column" value={name} onChange={setName} columns={preview.columns} />
            {preview.variables_to_map.map((v) => (
              <Pick key={v} label={`Script detail: ${v}`} value={vars[v] ?? ""} onChange={(c) => setVars({ ...vars, [v]: c })} columns={preview.columns} />
            ))}
          </div>
          <Field label="Save as a reusable list (optional)" name="list" value={listName} onChange={(e) => setListName(e.target.value)} maxLength={200} />
          <div className="flex gap-2">
            <button type="button" className={btn.primary} disabled={busy || !phone} onClick={() => void commit()}>Add {preview.rows} contacts</button>
            <button type="button" className={btn.quiet} onClick={() => setPreview(null)}>Back</button>
          </div>
        </div>
      )}
      {report && (
        <div role="status">
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
          {[["Added", report.added], ["Already in this campaign", report.already_in_campaign], ["Skipped: do not call", report.skipped_do_not_call], ["Skipped: excluded", report.skipped_excluded], ["Repeated in the file", report.duplicates_in_file], ["Invalid numbers", report.invalid_count]].map(([k, v]) => (
            <div key={k as string} className="flex justify-between border-b border-line py-1"><dt className="text-ink-muted">{k}</dt><dd className="num text-ink">{v}</dd></div>
          ))}
        </dl>
        {report.variables_left_empty.length > 0 && <p className="mt-2 text-xs text-warn">Left empty: {report.variables_left_empty.join(", ")}</p>}
        </div>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

function Pick(props: { label: string; value: string; onChange: (v: string) => void; columns: string[]; required?: boolean }) {
  return (
    <label className="block">
      <span className="text-sm text-ink">{props.label}</span>
      <select value={props.value} onChange={(e) => props.onChange(e.target.value)} className="mt-1.5 h-10 w-full rounded-ctl border border-line-accent bg-bg px-2 text-sm text-ink-strong">
        <option value="">{props.required ? "Choose a column" : "None"}</option>
        {props.columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>
  );
}

function ByHand({ campaignId }: { campaignId: string }) {
  const action = useCampaignAction(campaignId);
  function add(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const f = new FormData(form);
    action.mutate(async () => {
      await unwrap(api.POST("/campaigns/{campaign_id}/contacts", { ...at(campaignId), body: [{ phone: String(f.get("phone")).trim(), name: String(f.get("name")).trim() || null, variables: {} }] }));
      form.reset();
    });
  }
  return (
    <form onSubmit={add} className="rounded-card border border-line bg-surface p-6" aria-labelledby="by-hand">
      <h2 id="by-hand" className="eyebrow">Add one</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Phone" name="phone" type="tel" required />
        <Field label="Name" name="name" />
      </div>
      <button type="submit" className={`${btn.ghost} mt-3`} disabled={action.isPending}>Add contact</button>
      {action.error && <div className="mt-3"><ErrorState error={action.error} /></div>}
    </form>
  );
}

function FromList({ campaignId }: { campaignId: string }) {
  const lists = useQuery({ queryKey: ["contact-lists"], queryFn: () => unwrap<{ id: string; name: string; contacts: number }[]>(api.GET("/contact-lists")) });
  const action = useCampaignAction(campaignId);
  if (!lists.data?.length) return null;
  return (
    <section aria-labelledby="from-list" className="rounded-card border border-line bg-surface p-6">
      <h2 id="from-list" className="eyebrow">From a saved list</h2>
      <ul className="mt-3 space-y-2">
        {lists.data.map((l) => (
          <li key={l.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="text-ink">{l.name} <span className="num text-ink-muted">· {l.contacts}</span></span>
            <button type="button" className={btn.quiet} disabled={action.isPending}
              onClick={() => action.mutate(() => unwrap(api.POST("/campaigns/{campaign_id}/contacts/from-list", { ...at(campaignId), body: { list_id: l.id } })))}>Add</button>
          </li>
        ))}
      </ul>
      {action.error && <div className="mt-3"><ErrorState error={action.error} /></div>}
    </section>
  );
}

function Exclusions({ campaignId }: { campaignId: string }) {
  const list = useQuery({ queryKey: ["campaigns", campaignId, "exclusions"], queryFn: () => unwrap<string[]>(api.GET("/campaigns/{campaign_id}/exclusions", at(campaignId))) });
  const action = useCampaignAction(campaignId);
  const [text, setText] = useState("");
  return (
    <section aria-labelledby="exclusions" className="rounded-card border border-line bg-surface p-6">
      <h2 id="exclusions" className="eyebrow">Never call in this campaign</h2>
      <textarea aria-label="Numbers to exclude" value={text} onChange={(e) => setText(e.target.value)} rows={2} placeholder="One number per line"
        className="num mt-3 w-full rounded-ctl border border-line bg-bg px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
      <button type="button" className={`${btn.ghost} mt-2`} disabled={action.isPending || !text.trim()}
        onClick={() => action.mutate(async () => { await unwrap(api.POST("/campaigns/{campaign_id}/exclusions", { ...at(campaignId), body: { text } })); setText(""); })}>Exclude</button>
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {list.data?.map((p) => (
          <li key={p} className="num inline-flex items-center gap-1 rounded-full border border-line-accent px-2.5 py-0.5 text-xs text-ink">
            {p}
            <button type="button" aria-label={`Stop excluding ${p}`} className="text-ink-muted hover:text-danger"
              onClick={() => action.mutate(() => unwrap(api.DELETE("/campaigns/{campaign_id}/exclusions/{phone}", { params: { path: { campaign_id: campaignId, phone: p } } })))}>×</button>
          </li>
        ))}
      </ul>
      {action.error && <div className="mt-3"><ErrorState error={action.error} /></div>}
    </section>
  );
}

/** The list itself, with what can be done to each person, or to several picked at once. */
export function ContactTable({ campaignId, live }: { campaignId: string; live: boolean }) {
  const contacts = useContacts(campaignId, live);
  const action = useCampaignAction(campaignId);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [note, setNote] = useState<string | null>(null);
  const one = (c: Contact, what: BulkAction) => {
    const p = { params: { path: { campaign_id: campaignId, contact_id: c.id } } };
    action.mutate(() =>
      unwrap(
        what === "call-now"
          ? api.POST("/campaigns/{campaign_id}/contacts/{contact_id}/call-now", p)
          : what === "cancel"
            ? api.POST("/campaigns/{campaign_id}/contacts/{contact_id}/cancel", p)
            : api.POST("/campaigns/{campaign_id}/contacts/{contact_id}/retry", p),
      ),
    );
  };
  const many = (what: BulkAction) =>
    action.mutate(async () => {
      const r = await unwrap<BulkResult>(api.POST("/campaigns/{campaign_id}/contacts/bulk", { ...at(campaignId), body: { contact_ids: [...selected], action: what } }));
      setNote(bulkSummary(r));
      setSelected(new Set());
    });
  const pick = (id: string, on: boolean) =>
    setSelected((x) => {
      const next = new Set(x);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const rows = contacts.data?.contacts.slice(0, 200) ?? [];
  const allPicked = rows.length > 0 && rows.every((c) => selected.has(c.id));
  return (
    <section aria-labelledby="contact-list">
      <h2 id="contact-list" className="eyebrow">Contacts {contacts.data && <span className="num text-ink-muted">· {contacts.data.total}</span>}</h2>
      {selected.size > 0 && (
        <div role="toolbar" aria-label="Selected contacts" className="mt-3 flex flex-wrap items-center gap-2 rounded-ctl border border-line-accent bg-accent-soft px-4 py-2 text-sm">
          <span className="num text-ink-strong">{selected.size} selected</span>
          {live && <button type="button" className={btn.quiet} disabled={action.isPending} onClick={() => many("call-now")}>Call now</button>}
          <button type="button" className={btn.quiet} disabled={action.isPending} onClick={() => many("retry")}>Retry</button>
          <button type="button" className={btn.quiet} disabled={action.isPending} onClick={() => many("cancel")}>Cancel calls</button>
          <button type="button" className="ml-auto text-xs text-ink-muted hover:text-ink" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}
      {note && <p role="status" className="mt-2 text-sm text-ink-muted">{note}</p>}
      <div className="mt-3 overflow-x-auto rounded-card border border-line" tabIndex={0} role="region" aria-label="Contacts table">
        <table className="w-full min-w-[560px] text-sm">
          {rows.length > 0 && (
            <thead className="border-b border-line">
              <tr>
                <th className="w-10 px-4 py-2 text-left">
                  <input type="checkbox" aria-label="Select every contact shown" checked={allPicked} onChange={(e) => setSelected(e.target.checked ? new Set(rows.map((c) => c.id)) : new Set())} className="accent-[var(--accent)]" />
                </th>
                <th className="px-4 py-2 text-left text-xs font-medium text-ink-muted">Name</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-ink-muted">Phone</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-ink-muted">Status</th>
                <th><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
          )}
          <tbody className="divide-y divide-line">
            {rows.map((c) => (
              <tr key={c.id} className={selected.has(c.id) ? "bg-accent-soft/40" : undefined}>
                <td className="w-10 px-4 py-2.5">
                  <input type="checkbox" aria-label={`Select ${c.name || c.phone}`} checked={selected.has(c.id)} onChange={(e) => pick(c.id, e.target.checked)} className="accent-[var(--accent)]" />
                </td>
                <td className="px-4 py-2.5 text-ink-strong">{c.name || "–"}</td>
                <td className="num px-4 py-2.5 text-ink-muted">{c.phone}</td>
                <td className="px-4 py-2.5 text-ink">{STATUS_LABEL[c.status]}{c.reason && <span className="text-ink-muted"> · {c.reason}</span>}</td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  {(c.status === "pending" || c.status === "callback") && <button type="button" className="text-xs text-accent" onClick={() => one(c, "call-now")}>Call now</button>}
                  {(c.status === "pending" || c.status === "callback") && <button type="button" className="ml-3 text-xs text-ink-muted hover:text-danger" onClick={() => one(c, "cancel")}>Cancel</button>}
                  {(c.status === "exhausted" || c.status === "canceled") && <button type="button" className="text-xs text-ink-muted hover:text-accent" onClick={() => one(c, "retry")}>Retry</button>}
                </td>
              </tr>
            ))}
            {contacts.data && rows.length === 0 && <tr><td className="p-6 text-center text-ink-muted">No contacts yet.</td></tr>}
          </tbody>
        </table>
      </div>
      {contacts.data && contacts.data.total > rows.length && <p className="mt-2 text-xs text-ink-muted">Showing the first {rows.length}; export the CSV for all.</p>}
      {action.error && <div className="mt-3"><ErrorState error={action.error} /></div>}
      {rows.length > 0 && <SaveAsList campaignId={campaignId} selected={[...selected]} />}
    </section>
  );
}

/** Keep some of these people as a saved list (the ones picked, or a group such as everyone who asked for a call-back) to start another campaign from. */
function SaveAsList({ campaignId, selected }: { campaignId: string; selected: string[] }) {
  const qc = useQueryClient();
  const [who, setWho] = useState<string>("callback");
  const [name, setName] = useState("");
  const [saved, setSaved] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const group = who === "selected" ? null : SAVE_GROUPS.find((g) => g.key === who);
  const save = () =>
    run(async () => {
      const body = group ? { name, ...group.body } : { name, contact_ids: selected };
      const r = await unwrap<{ name: string; contacts: number }>(api.POST("/campaigns/{campaign_id}/contacts/save-as-list", { ...at(campaignId), body }));
      setSaved(`Saved ${r.contacts} ${r.contacts === 1 ? "contact" : "contacts"} to the list ${r.name}.`);
      setName("");
      void qc.invalidateQueries({ queryKey: ["contact-lists"] });
    });
  const choice = who === "selected" && selected.length === 0 ? "callback" : who;
  return (
    <div className="mt-6 rounded-card border border-line bg-surface p-6">
      <h3 className="eyebrow">Save as a list</h3>
      <p className="mt-2 text-sm text-ink-muted">Keep these people, with their details, to start another campaign from. The do-not-call list is checked again then.</p>
      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="block"><span className="text-sm text-ink">Who</span>
          <select value={choice} onChange={(e) => { setWho(e.target.value); setSaved(null); }} className="mt-1.5 h-10 rounded-ctl border border-line-accent bg-bg px-2 text-sm text-ink-strong">
            {selected.length > 0 && <option value="selected">The {selected.length} selected</option>}
            {SAVE_GROUPS.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
          </select></label>
        <div className="min-w-56 flex-1"><Field label="List name" name="save-list" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></div>
        <button type="button" className={btn.ghost} disabled={busy || !name.trim()} onClick={() => void save()}>Save list</button>
      </div>
      {saved && <p role="status" className="mt-3 text-sm text-accent">{saved}</p>}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </div>
  );
}
