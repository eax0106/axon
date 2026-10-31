import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { dailySpend, runwayDays, useRates, useTransactions } from "../../lib/billing";
import { credits } from "../../lib/format";
import { useWallet } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Sparkline } from "../../ui/Sparkline";
import { ErrorState, Skeleton } from "../../ui/states";
import { Ledger } from "./Ledger";
import { BillingSettings } from "./Settings";

export default function Billing() {
  return (
    <>
      <p className="eyebrow">Billing</p>
      <h1 className="display mt-3 text-4xl">Credits</h1>
      <p className="mt-2 text-ink-muted">1 credit is ₹1. Credits never expire; calls are billed per second from pickup.</p>
      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Balance />
        <TopUp />
      </div>
      <BillingSettings />
      <Ledger />
    </>
  );
}

function Balance() {
  const wallet = useWallet();
  const spend = useTransactions();
  const daily = spend.data ? dailySpend(spend.data.items, 30) : null;
  const balance = Number(wallet.data?.balance ?? 0);
  const runway = daily ? runwayDays(balance, daily) : null;
  // The bar shows the runway against a month; it moves only when the balance or spend changes.
  const fill = runway === null ? 1 : Math.min(1, runway / 30);
  if (wallet.error) return <ErrorState error={wallet.error} retry={() => void wallet.refetch()} />;
  return (
    <section aria-labelledby="balance" className="glow rounded-card border border-line-accent bg-surface p-6">
      <h2 id="balance" className="eyebrow">Balance</h2>
      <p className="display num mt-3 text-5xl">
        {wallet.data ? credits(wallet.data.balance) : <Skeleton className="h-12 w-40" />}
        <span className="ml-2 text-lg text-ink-muted">credits</span>
      </p>
      {wallet.data?.low && <p className="eyebrow mt-2 text-warn">● Running low</p>}
      <div className="mt-6">
        <div className="flex justify-between text-sm">
          <span className="text-ink-muted">Runway</span>
          <span className="num text-ink">
            {runway === null ? "No spending yet" : `about ${runway} day${runway === 1 ? "" : "s"} at your recent pace`}
          </span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line" aria-hidden>
          <div
            className={`h-full origin-left rounded-full transition-transform duration-700 ease-[var(--ease-reveal)] ${fill < 0.25 ? "bg-warn" : "bg-accent"}`}
            style={{ transform: `scaleX(${fill})` }}
          />
        </div>
      </div>
      <div className="mt-6">
        <p className="text-sm text-ink-muted">Spend, last 30 days</p>
        {daily ? (
          <Sparkline values={daily} label={`Daily spend over 30 days, ${credits(String(daily.reduce((a, b) => a + b, 0)))} credits in total`} />
        ) : (
          <Skeleton className="mt-2 h-12" />
        )}
      </div>
    </section>
  );
}

type Checkout = { order_id: string; key_id: string; amount_paise: number; currency: string };
type RazorpayResponse = { razorpay_order_id: string; razorpay_payment_id: string; razorpay_signature: string };
declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

/** Razorpay's own checkout (card or UPI) is loaded only when the owner pays. */
function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Couldn't load the payment window. Check your connection and try again."));
    document.head.append(s);
  });
}

function TopUp() {
  const rates = useRates();
  const qc = useQueryClient();
  const [amount, setAmount] = useState("1000");
  const [done, setDone] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction();
  const limits = rates.data?.topup;

  function pay(e: FormEvent) {
    e.preventDefault();
    setDone(null);
    void run(async () => {
      const order = await unwrap<Checkout>(api.POST("/wallet/topup/order", { body: { amount_inr: amount } }));
      await loadCheckout();
      const Razorpay = window.Razorpay;
      if (!Razorpay) throw new Error("The payment window didn't load.");
      new Razorpay({
        key: order.key_id,
        order_id: order.order_id,
        amount: order.amount_paise,
        currency: order.currency,
        name: "Axon credits",
        handler: (paid: RazorpayResponse) =>
          void unwrap<{ status: string }>(api.POST("/wallet/topup/verify", { body: paid }))
            .then((r) => {
              setDone(r.status === "pending" ? "Payment received; credits arrive as soon as Razorpay confirms it." : "Credits added.");
              void qc.invalidateQueries({ queryKey: ["wallet"] });
              void qc.invalidateQueries({ queryKey: ["billing"] });
            })
            .catch(setError),
      }).open();
    });
  }

  return (
    <section aria-labelledby="topup" className="rounded-card border border-line bg-surface p-6">
      <h2 id="topup" className="eyebrow">Add credits</h2>
      <form onSubmit={pay} className="mt-4 space-y-4">
        <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="Amount">
          {(limits?.presets ?? ["500", "1000", "2500", "5000"]).map((p) => (
            <button
              key={p}
              type="button"
              role="radio"
              aria-checked={amount === p}
              onClick={() => setAmount(p)}
              className="num h-10 rounded-ctl border border-line text-sm text-ink transition-colors duration-150 aria-checked:border-accent aria-checked:bg-accent-soft aria-checked:text-ink-strong"
            >
              ₹{credits(p)}
            </button>
          ))}
        </div>
        <label className="block">
          <span className="text-sm text-ink">Or any amount</span>
          <span className="mt-1.5 flex h-11 items-center rounded-ctl border border-line-accent bg-bg px-3 focus-within:border-accent">
            <span className="text-ink-muted">₹</span>
            <input
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))}
              className="num h-full w-full bg-transparent px-2 text-ink-strong outline-none"
              aria-describedby="topup-hint"
            />
          </span>
          <span id="topup-hint" className="mt-1.5 block text-xs text-ink-muted">
            {limits ? `Between ₹${credits(limits.min)} and ₹${credits(limits.max)}. GST included; invoice issued automatically.` : " "}
          </span>
        </label>
        <button type="submit" className={`${btn.primary} h-11 w-full`} disabled={busy || !Number(amount)}>
          {busy ? "Opening payment…" : `Pay ₹${credits(amount || "0")} by card or UPI`}
        </button>
      </form>
      {done && <p role="status" className="mt-3 text-sm text-accent">{done}</p>}
      {error !== null && (
        <div className="mt-3">
          <ErrorState error={error} />
        </div>
      )}
    </section>
  );
}
