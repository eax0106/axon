import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

// Shapes the API returns as plain objects (services/api/app/billing/router.py, numbers/router.py).
export type Entry = { id: number; at: string; kind: string; amount: string; balance_after: string; note: string | null };
export type Rates = {
  per_minute: Record<"value" | "standard" | "premium", string>;
  ai_use_fee: string;
  number_monthly_fee: string;
  extra_channel_monthly_fee: string;
  free_signup_credits: string;
  topup: { min: string; max: string; presets: string[] };
};
export type Statement = { month: string; opening_balance: string; closing_balance: string; by_kind: Record<string, { total: string; entries: number }> };
export type Usage = { employees: { employee_id: string | null; name: string | null; calls: number; talk_seconds: number; credits: string }[] };
export type Invoice = { id: string; number: string; issued_at: string; total: string; taxable: string; cgst: string; sgst: string; igst: string };
export type BillingDetails = { details: Record<string, string | null> | null; spend_cap_per_hour: string | null };
export type PhoneNumber = {
  id: string;
  e164: string;
  number_type: "regular" | "140" | "1600";
  status: "active" | "grace" | "released" | "reconcile";
  channels: number;
  monthly_fee: string;
  renews_on: string | null;
  grace_until: string | null;
  employee_id: string | null;
};
export type Offer = { e164: string; number_type: PhoneNumber["number_type"]; setup_fee: string; monthly_fee: string };
export type Quote = Offer & { first_charge: string; balance: string; kyc_required: boolean };
export type Holder = { id: string; name: string; pan_last4: string; status: "pan_verified" | "verified" | string };

export const KIND: Record<string, string> = {
  topup: "Top-up",
  call: "Calls",
  number: "Numbers",
  refund: "Refunds",
  bonus: "Free credits",
  adjustment: "Adjustments",
  ai_use: "AI help",
};

export const useRates = () =>
  useQuery({ queryKey: ["billing", "rates"], queryFn: () => unwrap<Rates>(api.GET("/billing/rates")), staleTime: 5 * 60_000 });
export const useTransactions = (limit = 200) =>
  useQuery({
    queryKey: ["billing", "transactions", limit],
    queryFn: () => unwrap<{ items: Entry[] }>(api.GET("/billing/transactions", { params: { query: { limit } } })),
  });
export const useStatement = (month: "this" | "last") =>
  useQuery({
    queryKey: ["billing", "statement", month],
    queryFn: () => unwrap<Statement>(api.GET("/billing/statement", { params: { query: { month } } })),
  });
export const useUsage = (month: "this" | "last") =>
  useQuery({
    queryKey: ["billing", "usage", month],
    queryFn: () => unwrap<Usage>(api.GET("/billing/usage", { params: { query: { month } } })),
  });
export const useInvoices = () =>
  useQuery({ queryKey: ["billing", "invoices"], queryFn: () => unwrap<Invoice[]>(api.GET("/billing/invoices")) });
export const useBillingSettings = () =>
  useQuery({ queryKey: ["billing", "settings"], queryFn: () => unwrap<BillingDetails>(api.GET("/billing/settings")) });
export const useNumbers = () =>
  useQuery({ queryKey: ["numbers"], queryFn: () => unwrap<PhoneNumber[]>(api.GET("/numbers")) });
export const useHolders = () =>
  useQuery({ queryKey: ["numbers", "holders"], queryFn: () => unwrap<Holder[]>(api.GET("/numbers/holders")) });

const DAY = 86_400_000;
const IST = 330 * 60_000;
const istDay = (t: number) => Math.floor((t + IST) / DAY);

/** Credits spent per Indian day for the last `days` days, oldest first (spending is a negative entry). */
export function dailySpend(entries: Entry[], days: number, now = Date.now()): number[] {
  const today = istDay(now);
  const out = new Array<number>(days).fill(0);
  for (const e of entries) {
    const amount = Number(e.amount);
    if (amount >= 0 || e.kind === "refund") continue;
    const slot = days - 1 - (today - istDay(Date.parse(e.at)));
    if (slot >= 0 && slot < days) out[slot] = (out[slot] ?? 0) - amount;
  }
  return out.map((v) => Math.round(v * 100) / 100);
}

/** Days the balance lasts at the recent average daily spend; null when nothing is being spent. */
export function runwayDays(balance: number, daily: number[]): number | null {
  const average = daily.reduce((a, b) => a + b, 0) / Math.max(daily.length, 1);
  return average > 0 ? Math.floor(balance / average) : null;
}
