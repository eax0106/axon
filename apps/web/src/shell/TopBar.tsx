import * as Popover from "@radix-ui/react-popover";
import { Link } from "react-router";

import { ago, credits } from "../lib/format";
import { type Notification, useLiveCalls, useMarkRead, useNotifications, useWallet } from "../lib/queries";
import { Skeleton } from "../ui/states";


export function CreditChip() {
  const wallet = useWallet();
  if (!wallet.data) return <Skeleton className="h-8 w-24 rounded-ctl" />;
  const { balance, low } = wallet.data;
  return (
    <Link
      to="/billing"
      title={low ? "Credits are running low" : "Credit balance (1 credit = ₹1)"}
      className={`inline-flex h-8 items-center gap-2 rounded-ctl border px-3 text-sm transition-colors duration-150 hover:border-line-accent ${
        low ? "border-warn/40 text-warn" : "border-line text-ink"
      }`}
    >
      {low && <span aria-hidden className="size-1.5 rounded-full bg-warn" />}
      <span className="num">{credits(balance)}</span>
      <span className="text-ink-muted">credits</span>
      {low && <span className="sr-only">, running low</span>}
    </Link>
  );
}

export function LiveIndicator() {
  const live = useLiveCalls().data ?? 0;
  if (live === 0) return null;
  return (
    <span className="eyebrow inline-flex items-center gap-2" aria-live="polite">
      <span aria-hidden className="live-dot size-2 rounded-full bg-accent" />
      <span className="num">{live}</span> live
    </span>
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
