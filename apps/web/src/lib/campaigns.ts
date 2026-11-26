import type { components } from "@axon/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./api";

type S = components["schemas"];
export type Campaign = S["app__campaigns__router__CampaignOut"];
export type CampaignSettings = Required<S["CampaignSettings"]>;
export type Contact = {
  id: string;
  phone: string;
  name: string | null;
  variables: Record<string, string>;
  status: "pending" | "calling" | "callback" | "done" | "exhausted" | "skipped" | "canceled";
  attempts: number;
  next_attempt_at: string | null;
  reason: string | null;
};
export type Live = {
  status: Campaign["status"];
  note: string | null;
  counts: Record<Contact["status"], number>;
  calling_now: { contact_id: string; phone: string; name: string | null; call_id: string; attempt: number; since: string | null }[];
  callbacks: { contact_id: string; phone: string; name: string | null; at: string | null }[];
  done: number;
  remaining: number;
};
export type Preview = { columns: string[]; rows: number; sample: Record<string, string>[]; variables_to_map: string[] };
export type ImportReport = {
  variables_left_empty: string[];
  added: number;
  already_in_campaign: number;
  skipped_do_not_call: number;
  skipped_excluded: number;
  duplicates_in_file: number;
  invalid: { row: number; phone: string; reason: string }[];
  invalid_count: number;
  list_id?: string | null;
};
export type Capacity = {
  remaining_contacts: number;
  number_channels: number;
  concurrency: number;
  parallel_calls: number;
  avg_talk_seconds: number;
  calls_per_open_day: number;
  open_days_per_week: number;
  working_days_needed: number | null;
  estimated_cost: string;
  credit_balance: string;
  enough_credits: boolean;
  queue_ahead: number;
};

export const STATUS_LABEL: Record<Contact["status"], string> = {
  pending: "Not called yet",
  calling: "On a call",
  callback: "Call back",
  done: "Done",
  exhausted: "No answer",
  skipped: "Skipped",
  canceled: "Cancelled",
};

const at = (id: string) => ({ params: { path: { campaign_id: id } } });

export const useCampaigns = () =>
  useQuery({ queryKey: ["campaigns"], queryFn: () => unwrap<Campaign[]>(api.GET("/campaigns")) });
export const useCampaign = (id: string) =>
  useQuery({ queryKey: ["campaigns", id], queryFn: () => unwrap<Campaign>(api.GET("/campaigns/{campaign_id}", at(id))) });
export const useLive = (id: string, on: boolean) =>
  useQuery({
    queryKey: ["campaigns", id, "live"],
    queryFn: () => unwrap<Live>(api.GET("/campaigns/{campaign_id}/live", at(id))),
    refetchInterval: on ? 4000 : false,
  });

const PAGE = 500;
/** Every contact, up to 2,000 (four pages fetched together), for the constellation and the list. */
export const useContacts = (id: string, refresh: boolean) =>
  useQuery({
    queryKey: ["campaigns", id, "contacts"],
    queryFn: async () => {
      const page = (offset: number) =>
        unwrap<{ total: number; contacts: Contact[] }>(
          api.GET("/campaigns/{campaign_id}/contacts", { params: { path: { campaign_id: id }, query: { limit: PAGE, offset } } }),
        );
      const first = await page(0);
      const more = Math.min(3, Math.ceil(first.total / PAGE) - 1);
      const rest = await Promise.all(Array.from({ length: Math.max(0, more) }, (_, i) => page((i + 1) * PAGE)));
      return { total: first.total, contacts: [...first.contacts, ...rest.flatMap((r) => r.contacts)] };
    },
    refetchInterval: refresh ? 8000 : false,
  });

/** Any campaign action: the campaign, its live panel and its contacts all refresh after it. */
export function useCampaignAction(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["campaigns", id] });
      void qc.invalidateQueries({ queryKey: ["campaigns"], exact: true });
    },
  });
}

/** Contacts per status, every status present (0 when none), for counters and the legend. */
export function tally(contacts: Pick<Contact, "status">[]): Record<Contact["status"], number> {
  const out = { pending: 0, calling: 0, callback: 0, done: 0, exhausted: 0, skipped: 0, canceled: 0 };
  for (const c of contacts) out[c.status] += 1;
  return out;
}

export type BulkAction = "call-now" | "cancel" | "retry";
export type BulkResult = { done: number; refused: { contact_id: string; reason: string }[]; campaign_status: Campaign["status"] };

/** What a bulk action did, in one line: how many it was done for, and why the rest were left. */
export function bulkSummary(r: BulkResult): string {
  const done = `Done for ${r.done} ${r.done === 1 ? "contact" : "contacts"}.`;
  if (r.refused.length === 0) return done;
  const why = [...new Set(r.refused.map((x) => x.reason))].join("; ");
  return `${done} ${r.refused.length} left as they were (${why}).`;
}

/** Who can be saved as a list without picking them one by one. */
export const SAVE_GROUPS = [
  { key: "callback", label: "Asked for a call-back", body: { outcome: "callback_requested" } },
  { key: "interested", label: "Interested", body: { outcome: "interested" } },
  { key: "not_interested", label: "Not interested", body: { outcome: "not_interested" } },
  { key: "exhausted", label: "Never answered", body: { state: "exhausted" } },
  { key: "done", label: "Answered", body: { state: "done" } },
  { key: "all", label: "Everyone in this campaign", body: {} },
] as const;

export type RetryStep = CampaignSettings["retry_ladder"][number];
export const MAX_LADDER_STEPS = 5;

/** The wait before each of `retries` retries: step n of the ladder, and the last step once it runs out. */
export function retryWaits(retries: number, ladder: RetryStep[]): RetryStep[] {
  return Array.from({ length: ladder.length ? retries : 0 }, (_, i) => ladder[Math.min(i, ladder.length - 1)] as RetryStep);
}

/** A ladder step in words. */
export const stepLabel = (step: RetryStep) => (step === "next_day" ? "the next open day" : step % 60 === 0 ? `${step / 60} h` : `${step} min`);

/** Columns for a grid of `n` dots that stays roughly 2.5 times wider than tall. */
export const gridColumns = (n: number) => Math.max(1, Math.ceil(Math.sqrt(n * 2.5)));
