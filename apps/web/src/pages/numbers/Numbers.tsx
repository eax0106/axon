import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { type Offer, type PhoneNumber, type Quote, useNumbers, useRates } from "../../lib/billing";
import { useEmployees } from "../../lib/employees";
import { credits } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";
import { Kyc } from "./Kyc";

const TYPE: Record<PhoneNumber["number_type"], string> = { regular: "10-digit", "140": "140 series", "1600": "1600 series" };
const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "");

export default function Numbers() {
  return (
    <>
      <p className="eyebrow">Numbers</p>
      <h1 className="display mt-3 text-4xl">Phone numbers</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">Each AI employee calls and answers from its own number. Rent is taken from credits every month.</p>
      <Mine />
      <Store />
    </>
  );
}

function Mine() {
  const numbers = useNumbers();
  const employees = useEmployees();
  const rates = useRates();
  const qc = useQueryClient();
  const { error, run } = useAction();
  const nameOf = (id: string | null) => employees.data?.find((e) => e.id === id)?.name;
  const at = (n: PhoneNumber) => ({ params: { path: { number_id: n.id } } });
  const setChannels = (n: PhoneNumber, channels: number) =>
    run(async () => {
      await unwrap(api.PUT("/numbers/{number_id}/channels", { ...at(n), body: { channels } }));
      void qc.invalidateQueries({ queryKey: ["numbers"] });
      void qc.invalidateQueries({ queryKey: ["wallet"] }); // a new channel is charged at once
    });
  const release = (n: PhoneNumber) =>
    run(async () => {
      await unwrap(api.DELETE("/numbers/{number_id}", at(n)));
      void qc.invalidateQueries({ queryKey: ["numbers"] });
      void qc.invalidateQueries({ queryKey: ["employees"] });
    });

  if (numbers.error) return <div className="mt-8"><ErrorState error={numbers.error} retry={() => void numbers.refetch()} /></div>;
  if (!numbers.data) return <Skeleton className="mt-8 h-32 rounded-card" />;
  if (numbers.data.length === 0) return null;
  return (
    <section aria-labelledby="mine" className="mt-10">
      <h2 id="mine" className="eyebrow">Yours</h2>
      <ul className="mt-3 grid gap-3 md:grid-cols-2">
        {numbers.data.map((n) => (
          <li key={n.id} className="rounded-card border border-line bg-surface p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="num text-lg text-ink-strong">{n.e164}</p>
                <p className="text-sm text-ink-muted">
                  {TYPE[n.number_type]} · {nameOf(n.employee_id) ?? "Not attached"}
                </p>
              </div>
              <span className={`eyebrow ${n.status === "active" ? "" : "text-warn"}`}>
                ● {n.status === "active" ? `Renews ${day(n.renews_on)}` : n.status === "grace" ? `Grace until ${day(n.grace_until)}` : "Being checked"}
              </span>
            </div>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="text-ink-muted">
                <span className="num text-ink">{credits(n.monthly_fee)}</span> credits a month
              </span>
              <span className="flex items-center gap-2">
                <span className="text-ink-muted">Calls at once</span>
                <button type="button" aria-label="Fewer channels" className={btn.quiet} disabled={n.channels <= 1} onClick={() => void setChannels(n, n.channels - 1)}>
                  −
                </button>
                <span className="num w-5 text-center text-ink-strong">{n.channels}</span>
                <Confirm
                  trigger={<button type="button" aria-label="More channels" className={btn.quiet} disabled={n.channels >= 20}>+</button>}
                  title="Add a channel?"
                  body={`One more call at a time on ${n.e164}. ${rates.data ? `${credits(rates.data.extra_channel_monthly_fee)} credits a month, ` : ""}charged now for the days left in this period and with the rent after that. Lowering it later is free but not refunded.`}
                  action="Add channel"
                  onConfirm={() => void setChannels(n, n.channels + 1)}
                />
              </span>
            </div>
            <div className="mt-4 border-t border-line pt-3">
              <Confirm
                danger
                trigger={<button type="button" className="text-xs text-ink-muted hover:text-danger">Release this number</button>}
                title={`Release ${n.e164}?`}
                body="It goes back to the carrier and its employee is detached (and paused if live). Rent already paid is not refunded. You may not get this number back."
                action="Release"
                onConfirm={() => void release(n)}
              />
            </div>
          </li>
        ))}
      </ul>
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}

/** Search the carrier's numbers, see the first charge, verify the holder once, and buy. */
function Store() {
  const qc = useQueryClient();
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [bought, setBought] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction();

  function search(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const q = String(new FormData(e.currentTarget).get("q") ?? "").replace(/\D/g, "");
    setQuote(null);
    void run(async () => setOffers(await unwrap<Offer[]>(api.GET("/numbers/inventory", { params: { query: { search: q || undefined } } }))));
  }
  const pick = (o: Offer) => run(async () => setQuote(await unwrap<Quote>(api.GET("/numbers/quote", { params: { query: { e164: o.e164 } } }))));
  const buy = (q: Quote, holder?: string) =>
    run(async () => {
      const n = await unwrap<PhoneNumber>(api.POST("/numbers/purchase", { body: { e164: q.e164, holder_id: holder ?? null } }));
      setBought(n.status === "reconcile" ? `${n.e164}: the carrier didn't confirm in time; we're checking with them and will tell you.` : `${n.e164} is yours.`);
      setQuote(null);
      setOffers(null);
      void qc.invalidateQueries({ queryKey: ["numbers"] });
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    });

  return (
    <section aria-labelledby="store" className="mt-12">
      <h2 id="store" className="eyebrow">Get a number</h2>
      <form onSubmit={search} className="mt-3 flex max-w-xl gap-2" role="search">
        <label htmlFor="q" className="sr-only">Digits to look for</label>
        <input id="q" name="q" inputMode="numeric" placeholder="Digits you'd like, e.g. 9000" className="num h-11 min-w-0 flex-1 rounded-ctl border border-line-accent bg-surface px-3.5 text-ink-strong outline-none focus:border-accent" />
        <button type="submit" className={`${btn.primary} h-11`} disabled={busy}>Search</button>
      </form>
      {bought && <p role="status" className="mt-4 text-sm text-accent">{bought}</p>}
      {error !== null && <div className="mt-4"><ErrorState error={error} retry={() => setError(null)} /></div>}
      {offers && !quote && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {offers.map((o) => (
            <li key={o.e164}>
              <button type="button" onClick={() => void pick(o)} className="w-full rounded-card border border-line bg-surface p-4 text-left transition-colors duration-150 hover:border-line-accent">
                <span className="num block text-ink-strong">{o.e164}</span>
                <span className="text-sm text-ink-muted">{TYPE[o.number_type]} · {credits(o.monthly_fee)}/month</span>
              </button>
            </li>
          ))}
          {offers.length === 0 && <li className="text-sm text-ink-muted">Nothing matches. Try fewer digits.</li>}
        </ul>
      )}
      {quote && (
        <div className="mt-4 max-w-xl rounded-card border border-line-accent bg-surface p-6">
          <p className="num text-2xl text-ink-strong">{quote.e164}</p>
          <dl className="mt-4 divide-y divide-line text-sm">
            <div className="flex justify-between py-2"><dt className="text-ink-muted">First charge (setup and month one)</dt><dd className="num">{credits(quote.first_charge)}</dd></div>
            <div className="flex justify-between py-2"><dt className="text-ink-muted">Then each month</dt><dd className="num">{credits(quote.monthly_fee)}</dd></div>
            <div className="flex justify-between py-2"><dt className="text-ink-muted">Your balance</dt><dd className="num">{credits(quote.balance)}</dd></div>
          </dl>
          <div className="mt-5">
            {quote.kyc_required ? (
              <Kyc onVerified={(h) => void buy(quote, h.id)} />
            ) : (
              <button type="button" className={btn.primary} disabled={busy} onClick={() => void buy(quote)}>
                {busy ? "Buying…" : `Buy for ${credits(quote.first_charge)} credits`}
              </button>
            )}
          </div>
          <button type="button" className={`${btn.quiet} mt-3`} onClick={() => setQuote(null)}>Back to results</button>
        </div>
      )}
    </section>
  );
}
