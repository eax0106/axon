import { credits } from "../lib/format";
import { useMe, useWallet } from "../lib/queries";
import { ErrorState, Skeleton } from "../ui/states";

function greeting(hour = new Date().getHours()) {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function Overview() {
  const me = useMe();
  const wallet = useWallet();
  const error = me.error ?? wallet.error;

  return (
    <div className="glow -mx-4 -mt-8 px-4 pt-8 md:-mx-8 md:-mt-12 md:px-8 md:pt-12">
      <p className="eyebrow">Overview</p>
      <h1 className="display mt-3 text-4xl md:text-[44px]">
        {me.data ? (
          <>
            {greeting()}, <span className="text-accent">{me.data.account.name}.</span>
          </>
        ) : (
          <Skeleton className="h-11 w-80 max-w-full" />
        )}
      </h1>
      <p className="mt-2 max-w-xl text-ink-muted">Your account at a glance.</p>

      <section aria-label="Account" className="mt-10 max-w-2xl">
        {error ? (
          <ErrorState
            error={error}
            retry={() => {
              void me.refetch();
              void wallet.refetch();
            }}
          />
        ) : (
          <dl className="divide-y divide-line border-y border-line">
            <Row label="Credit balance" value={wallet.data && `${credits(wallet.data.balance)} credits`} tag={wallet.data?.low ? "LOW" : undefined} />
            <Row
              label="Hourly spend cap"
              value={wallet.data && (wallet.data.spend_cap_per_hour ? `${credits(wallet.data.spend_cap_per_hour)} credits` : "No cap")}
            />
            <Row label="Low-balance warning at" value={wallet.data && `${credits(wallet.data.low_balance_threshold)} credits`} />
            <Row label="Signed in as" value={me.data && `${me.data.user.email} · ${me.data.user.role}`} />
          </dl>
        )}
      </section>
    </div>
  );
}

function Row({ label, value, tag }: { label: string; value: string | undefined | null | false; tag?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 py-4">
      <dt className="text-sm text-ink-muted">{label}</dt>
      <dd className="flex items-center gap-3 text-right text-ink">
        {tag && <span className="eyebrow rounded-tag bg-accent-soft px-1.5 py-0.5 text-warn">● {tag}</span>}
        {value ? <span className="num">{value}</span> : <Skeleton className="w-28" />}
      </dd>
    </div>
  );
}
