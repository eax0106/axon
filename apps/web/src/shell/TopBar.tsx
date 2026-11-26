import * as Popover from "@radix-ui/react-popover";
import { Link } from "react-router";

import { runwayWords, useTransactions } from "../lib/billing";
import { ago, credits } from "../lib/format";
import { type Notification, useLiveCalls, useMarkRead, useNotifications, useWallet } from "../lib/queries";
import { Skeleton } from "../ui/states";


export function CreditChip() {
  const wallet = useWallet();
  const low = wallet.data?.low ?? false;
  const spend = useTransactions(200, low); // only fetched when the balance is low
  if (!wallet.data) return <Skeleton className="h-8 w-24 rounded-ctl" />;
  const { balance } = wallet.data;
  const left = low && spend.data ? runwayWords(Number(balance), spend.data.items) : null;
  return (
    <Link
      to="/billing"
      title={low ? `Credits are running low${left ? `: ${left}` : ""}` : "Credit balance (1 credit = ₹1)"}
      className={`inline-flex h-8 items-center gap-2 rounded-ctl border px-3 text-sm transition-colors duration-150 hover:border-line-accent ${
        low ? "border-warn/40 text-warn" : "border-line text-ink"
      }`}
    >
      {low && <span aria-hidden className="size-1.5 rounded-full bg-warn" />}
      <span className="num">{credits(balance)}</span>
      <span className="text-ink-muted">credits</span>
      {low && <span className="sr-only">, running low{left ? `, ${left}` : ""}</span>}
    </Link>
  );
}

export function LiveIndicator() {
  const live = useLiveCalls().data;
  if (!live?.total) return null;
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={`${live.total} live ${live.total === 1 ? "call" : "calls"}, show them`}
        className="eyebrow inline-flex h-8 items-center gap-2 rounded-ctl px-2 transition-colors duration-150 hover:bg-accent-soft"
      >
        <span aria-hidden className="live-dot size-2 rounded-full bg-accent" />
        <span className="num" aria-live="polite">{live.total}</span> live
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={16}
          className="pop-in z-30 w-[min(340px,calc(100vw-32px))] rounded-card border border-line-accent bg-surface"
        >
          <p className="eyebrow border-b border-line px-4 py-3">On a call now</p>
          <ul className="max-h-96 overflow-y-auto">
            {live.items.map((c) => (
              <li key={c.id} className="border-b border-line last:border-0">
                <Popover.Close asChild>
                  <Link
                    to={`/calls/${c.id}/live`}
                    className="flex items-center justify-between gap-3 px-4 py-3 text-sm transition-colors duration-150 hover:bg-accent-soft"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-ink-strong">{c.employee_name ?? "Employee"}</span>
                      <span className="num block truncate text-ink-muted">{c.name || c.phone || "Unknown caller"}</span>
                    </span>
                    <span className="shrink-0 text-xs text-ink-muted">{c.status === "ringing" ? "ringing" : ago(c.created_at)}</span>
                  </Link>
                </Popover.Close>
              </li>
            ))}
          </ul>
          {live.total > live.items.length && (
            <Popover.Close asChild>
              <Link to="/calls" className="block px-4 py-3 text-center text-xs text-ink-muted hover:text-accent">
                {live.total - live.items.length} more in Conversations
              </Link>
            </Popover.Close>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function Bell() {
  const list = useNotifications();
  const mark = useMarkRead();
  const unread = list.data?.unread_count ?? 0;
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}
        className="relative grid size-8 place-items-center rounded-ctl text-ink-muted transition-colors duration-150 hover:bg-accent-soft hover:text-ink-strong"
      >
        <svg aria-hidden viewBox="0 0 20 20" className="size-[18px]" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M5 8a5 5 0 0 1 10 0c0 4 1.5 5.5 1.5 5.5h-13S5 12 5 8ZM8.5 16.5a1.6 1.6 0 0 0 3 0" />
        </svg>
        {unread > 0 && (
          <span className="num absolute -top-0.5 -right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] font-semibold text-bg">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="end"
          sideOffset={8}
          collisionPadding={16}
          className="pop-in z-30 w-[min(380px,calc(100vw-32px))] rounded-card border border-line-accent bg-surface"
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <p className="eyebrow">Notifications</p>
            {unread > 0 && (
              <button
                type="button"
                onClick={() => mark.mutate(null)}
                className="text-xs text-ink-muted transition-colors duration-150 hover:text-accent"
              >
                Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-96 overflow-y-auto">
            {list.data?.items.map((n) => <Item key={n.id} n={n} onRead={() => mark.mutate(n.id)} />)}
            {list.data?.items.length === 0 && (
              <li className="px-4 py-10 text-center text-sm text-ink-muted">
                You're all caught up. Call results, callbacks and billing alerts land here.
              </li>
            )}
            {!list.data && (
              <li className="space-y-2 p-4">
                <Skeleton className="w-3/4" />
                <Skeleton className="w-1/2" />
              </li>
            )}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function Item({ n, onRead }: { n: Notification; onRead: () => void }) {
  return (
    <li className="border-b border-line last:border-0">
      <button
        type="button"
        onClick={onRead}
        disabled={n.read}
        className="flex w-full gap-3 px-4 py-3 text-left transition-colors duration-150 enabled:hover:bg-accent-soft"
      >
        <span
          aria-hidden
          className={`mt-1.5 size-1.5 shrink-0 rounded-full ${n.read ? "bg-transparent" : "bg-accent"}`}
        />
        <span className="min-w-0">
          <span className={`block text-sm ${n.read ? "text-ink-muted" : "text-ink-strong"}`}>{n.title}</span>
          {n.body && <span className="mt-0.5 block text-sm text-ink-muted">{n.body}</span>}
          <span className="mt-1 block text-xs text-ink-muted">
            {ago(n.created_at)}
            {!n.read && <span className="sr-only">, unread, select to mark read</span>}
          </span>
        </span>
      </button>
    </li>
  );
}
