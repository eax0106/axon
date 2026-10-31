import type { components } from "@axon/contracts";
import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "./api";

export type Dialer = components["schemas"]["DialerSettings"];
export type InstantInfo = {
  intake_path: string;
  secret_header: string;
  dialer: Required<Dialer>;
  meta: { form_id: string | null; token_set: boolean };
  sheets: { sheet_id: string | null; range: string | null; connected: boolean };
};
export type QueueItem = {
  call_id: string;
  phone: string | null;
  name: string | null;
  attempt: number;
  status: string;
  state: "waiting" | "held" | "ringing" | "in_progress" | string;
  scheduled_for: string | null;
  ended_at: string | null;
};
export type IntakeEntry = {
  id: number;
  at: string;
  source: string;
  status: "accepted" | "deduplicated" | "rejected";
  reason: string | null;
  phone: string | null;
  lead_id: string | null;
  call_id: string | null;
};

const path = (id: string) => ({ params: { path: { employee_id: id } } });

export const useInstant = (id: string) =>
  useQuery({ queryKey: ["instant", id], queryFn: () => unwrap<InstantInfo>(api.GET("/employees/{employee_id}/instant", path(id))) });

export const useQueue = (id: string) =>
  useQuery({
    queryKey: ["instant", id, "queue"],
    queryFn: () =>
      unwrap<{ active: QueueItem[]; recent: QueueItem[] }>(
        api.GET("/employees/{employee_id}/instant/queue", { ...path(id), params: { ...path(id).params, query: { recent: 20 } } }),
      ),
    refetchInterval: 5000,
  });

export const useIntakeLog = (id: string, outcome: string) =>
  useQuery({
    queryKey: ["instant", id, "log", outcome],
    queryFn: () =>
      unwrap<IntakeEntry[]>(
        api.GET("/employees/{employee_id}/instant/intake-log", {
          params: { path: { employee_id: id }, query: { outcome: (outcome || undefined) as never, limit: 50 } },
        }),
      ),
    refetchInterval: 10_000,
  });

/** "HH:MM" <-> minutes after midnight IST, as the dialer stores the window. */
export const toClock = (min: number) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
export const fromClock = (hhmm: string) => {
  const [h = "0", m = "0"] = hhmm.split(":");
  return Number(h) * 60 + Number(m);
};

/** A retry wait for people: "10 min", "3 h", "1 day 2 h". */
export function wait(min: number): string {
  if (min < 60) return `${min} min`;
  const days = Math.floor(min / 1440);
  const hours = Math.floor((min % 1440) / 60);
  const rest = min % 60;
  return [days && `${days} day${days > 1 ? "s" : ""}`, hours && `${hours} h`, rest && `${rest} min`].filter(Boolean).join(" ");
}
