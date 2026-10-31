import type { components } from "@axon/contracts";

export type InboundSettings = Required<components["schemas"]["InboundSettings"]>;
export type OpenWindow = { days: number[]; start_min: number; end_min: number };
export type Message = {
  id: string;
  call_id: string | null;
  employee_id: string | null;
  employee_name: string | null;
  lead_id: string | null;
  phone: string | null;
  name: string | null;
  body: string;
  callback_at: string | null;
  done: boolean;
  done_at: string | null;
  created_at: string;
};
export type Missed = {
  call_id: string;
  at: string;
  employee_id: string | null;
  employee_name: string | null;
  phone: string | null;
  name: string | null;
  reason: string | null;
  code: string | null;
  auto_callback: { state: string; at: string | null; call_id: string | null; not_made_because: string | null };
};

/**
 * Opening hours as the API stores them: a window cannot cross midnight, so "10 PM to 2 AM" on
 * the chosen days becomes 22:00–24:00 on those days and 00:00–02:00 on each following day.
 */
export function toWindows(days: number[], start: number, end: number): OpenWindow[] {
  if (end > start) return [{ days, start_min: start, end_min: end }];
  const late = { days, start_min: start, end_min: 24 * 60 };
  const early = { days: [...new Set(days.map((d) => (d + 1) % 7))].sort(), start_min: 0, end_min: end };
  return early.end_min > 0 ? [late, early] : [late];
}
