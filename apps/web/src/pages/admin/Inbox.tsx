import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import { queryClient } from "../../lib/queries";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { input, useWrite, when } from "./parts";

type Item = { id: string; account_id: string; account_name: string; kind: string; from_staff: boolean; body: string; rating: number | null; call_id: string | null; created_at: string };
const KINDS = [["", "All"], ["chat", "Chat"], ["feedback", "Feedback"], ["rating", "Ratings"]] as const;

/** Every account's chat, feedback and call ratings, newest first; reply to any account's chat. */
export function Inbox() {
  const [kind, setKind] = useState<(typeof KINDS)[number][0]>("");
  const list = useQuery({ queryKey: ["admin", "support", kind], queryFn: () => unwrap<{ items: Item[] }>(api.GET("/admin/support", { params: { query: { kind: kind || undefined, limit: 100 } } })) });
  return (
    <>
      <div role="radiogroup" aria-label="Kind" className="flex w-fit gap-1 rounded-ctl border border-line p-1">
        {KINDS.map(([k, label]) => (
          <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)} className="rounded-tag px-2.5 py-1 text-sm text-ink-muted aria-checked:bg-accent-soft aria-checked:text-ink-strong">{label}</button>
        ))}
      </div>
      {list.error ? <div className="mt-4"><ErrorState error={list.error} retry={() => void list.refetch()} /></div> : !list.data ? <Skeleton className="mt-4 h-64 rounded-card" /> : (
        <ul className="mt-4 space-y-2">
          {list.data.items.map((m) => <Message key={m.id} m={m} />)}
          {list.data.items.length === 0 && <li className="rounded-card border border-dashed border-line p-8 text-center text-sm text-ink-muted">Nothing here.</li>}
        </ul>
      )}
    </>
  );
}

function Message({ m }: { m: Item }) {
  const [open, setOpen] = useState(false);
  const { busy, write, outcome } = useWrite();
  function reply(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const body = String(new FormData(form).get("body")).trim();
    write(async () => {
      await unwrap(api.POST("/admin/support/{account_id}/reply", { params: { path: { account_id: m.account_id } }, body: { body } }));
      form.reset();
      setOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["admin", "support"] });
      return `Replied to ${m.account_name}; it shows in their chat and bell.`;
    });
  }
  return (
    <li className={`rounded-card border p-4 text-sm ${m.from_staff ? "border-line bg-bg" : "border-line bg-surface"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Link to={`/admin/accounts/${m.account_id}`} className="text-ink-strong hover:text-accent">{m.account_name}</Link>
        <span className="text-xs text-ink-muted">{m.from_staff ? "Staff reply" : m.kind}{m.rating !== null && ` · ${"★".repeat(m.rating)}${"☆".repeat(5 - m.rating)}`} · {when(m.created_at)}</span>
      </div>
      {m.body && <p className="mt-2 whitespace-pre-wrap text-ink">{m.body}</p>}
      {!m.from_staff && (open ? (
        <form onSubmit={reply} className="mt-3 flex gap-2">
          <input name="body" aria-label={`Reply to ${m.account_name}`} required maxLength={4000} autoFocus className={`${input} min-w-0 flex-1`} />
          <button type="submit" className={btn.primary} disabled={busy}>Send</button>
        </form>
      ) : <button type="button" className="mt-2 text-xs text-ink-muted hover:text-accent" onClick={() => setOpen(true)}>Reply</button>)}
      {outcome}
    </li>
  );
}
