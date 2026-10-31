import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, session, unwrap } from "./api";

// Shapes the API returns as plain objects (app/calls/conversations.py, leads.py, stats.py).
export type CallRow = {
  id: string;
  created_at: string;
  employee_id: string | null;
  employee_name: string | null;
  lead_id: string | null;
  phone: string | null;
  name: string | null;
  direction: "inbound" | "outbound";
  channel: string;
  status: string;
  outcome: string | null;
  sentiment: string | null;
  duration_s: number | null;
  credits_charged: number;
  summary: string | null;
  is_test: boolean;
  analysis_status: string | null;
  miss_reason: string | null;
};
export type Note = { id: string; body: string; created_at: string; call_id: string | null; user_id: string };
export type CallDetail = CallRow & {
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  transcript: { role: string; text: string; at?: string }[];
  captured: Record<string, unknown>;
  analysis_error: string | null;
  has_recording: boolean;
  timeline: { at: string | null; type: string; data: Record<string, unknown> }[];
  notes: Note[];
};
export type LeadRow = {
  id: string;
  phone: string;
  name: string | null;
  created_at: string;
  last_outcome: string | null;
  last_call_at: string | null;
  calls: number;
  fields: Record<string, unknown>;
};
export type LeadDetail = {
  id: string;
  phone: string;
  name: string | null;
  fields: Record<string, unknown>;
  memory: string | null;
  created_at: string;
  calls: { id: string; created_at: string; outcome: string | null; summary: string | null }[];
  notes?: Note[];
};
export type Overview = {
  range: string;
  from: string;
  to: string;
  totals: { calls: number; placed: number; connected: number; qualified: number; converted: number };
  rates: { connect: number | null; qualify: number | null; conversion: number | null };
  channel_split: Record<string, number>;
  by_hour: { hour: number; placed: number; connected: number; connect_rate: number | null }[];
  best_hour: number | null;
  leaderboard: { employee_id: string; name: string; placed: number; connected: number; qualified: number; converted: number }[];
  speed: { accepted: number; within_60s: number; rate: number | null };
};

export const OUTCOME: Record<string, string> = {
  interested: "Interested",
  not_interested: "Not interested",
  callback_requested: "Call back",
  wrong_number: "Wrong number",
  do_not_call: "Do not call",
  no_conversation: "No conversation",
  other: "Other",
  no_outcome: "Not called yet",
};
export const SENTIMENT: Record<string, string> = { positive: "Positive", neutral: "Neutral", negative: "Negative" };

/** Conversation filters as the API names them; empty values are left out of the request. */
export type Filters = Partial<{
  q: string;
  outcome: string;
  sentiment: string;
  employee_id: string;
  channel: string;
  direction: string;
  date_from: string;
  date_to: string;
  min_duration: number;
  max_duration: number;
  min_credits: number;
  max_credits: number;
  include_test: boolean;
}>;
export function cleanFilters(f: Filters): Filters {
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v !== "" && v !== undefined && v !== null && v !== false)) as Filters;
}

export const useOverview = (range: string, from?: string, to?: string) =>
  useQuery({
    queryKey: ["stats", range, from, to],
    queryFn: () =>
      unwrap<Overview>(
        api.GET("/stats/overview", { params: { query: { range: range as "7d", date_from: from || undefined, date_to: to || undefined } } }),
      ),
    enabled: range !== "custom" || Boolean(from && to),
    placeholderData: keepPreviousData,
  });

export const useCalls = (filters: Filters, limit: number) =>
  useQuery({
    queryKey: ["calls", "list", filters, limit],
    queryFn: () =>
      unwrap<{ total: number; items: CallRow[] }>(api.GET("/calls", { params: { query: { ...cleanFilters(filters), limit } } })),
    placeholderData: keepPreviousData,
  });

export const useCall = (id: string) =>
  useQuery({ queryKey: ["calls", id], queryFn: () => unwrap<CallDetail>(api.GET("/calls/{call_id}", { params: { path: { call_id: id } } })) });

export const useLeads = (q: string, outcome: string) =>
  useQuery({
    queryKey: ["leads", "list", q, outcome],
    queryFn: () =>
      unwrap<{ total: number; items: LeadRow[] }>(
        api.GET("/leads", { params: { query: { q: q || undefined, outcome: outcome || undefined, limit: 200 } } }),
      ),
    placeholderData: keepPreviousData,
  });

export const useBoard = (q: string) =>
  useQuery({
    queryKey: ["leads", "board", q],
    queryFn: () =>
      unwrap<{ columns: Record<string, LeadRow[]>; counts: Record<string, number> }>(
        api.GET("/leads/board", { params: { query: { q: q || undefined } } }),
      ),
    placeholderData: keepPreviousData,
  });

export const useLead = (id: string) =>
  useQuery({ queryKey: ["leads", id], queryFn: () => unwrap<LeadDetail>(api.GET("/leads/{lead_id}", { params: { path: { lead_id: id } } })) });

/** Save a file the API makes (CSV exports): fetched with the session, handed to the browser. */
export async function download(path: string, name: string) {
  const res = await fetch(`/api${path}`, { headers: { Authorization: `Bearer ${session.token() ?? ""}` } });
  if (!res.ok) throw new Error(`The export failed (${res.status}).`);
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const duration = (s: number | null) => (s === null ? "–" : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
export const percent = (r: number | null) => (r === null ? "–" : `${Math.round(r * 100)}%`);
