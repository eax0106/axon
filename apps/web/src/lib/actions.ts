import type { components } from "@axon/contracts";

type S = components["schemas"];
export type Action = S["HttpApi"] | S["CalendarBooking"] | S["SheetRead"] | S["SheetWrite"] | S["WhatsApp"];
export type Kind = NonNullable<Action["kind"]>;

export const KINDS: Record<Kind, { label: string; blurb: string; google?: "calendar" | "sheets" }> = {
  calendar_booking: { label: "Book a slot in Google Calendar", blurb: "Offers free times in working hours and books one.", google: "calendar" },
  sheet_read: { label: "Look something up in a Google Sheet", blurb: "Reads matching rows, e.g. stock or prices.", google: "sheets" },
  sheet_write: { label: "Write a row to a Google Sheet", blurb: "Adds what the caller said as plain text.", google: "sheets" },
  http_api: { label: "Call your own API", blurb: "A request to your system with details from the call." },
  whatsapp: { label: "Send a WhatsApp message", blurb: "An approved template, only to the person on the call." },
};

/** A new action of a kind with the API's defaults and a name the model can call (lowercase, unique). */
export function blank(kind: Kind, taken: string[]): Action {
  const base = { calendar_booking: "book_visit", sheet_read: "look_up", sheet_write: "save_details", http_api: "check_system", whatsapp: "send_whatsapp" }[kind];
  let name = base;
  for (let i = 2; taken.includes(name); i++) name = `${base}_${i}`;
  const description = "";
  switch (kind) {
    case "calendar_booking":
      return { kind, name, description, calendar_id: "primary", title: "Appointment", duration_min: 30, days_ahead: 14, start_hour: 10, end_hour: 18, days: [0, 1, 2, 3, 4, 5], min_notice_min: 60 };
    case "sheet_read":
      return { kind, name, description, sheet_id: "", range: "A:Z", max_rows: 5 };
    case "sheet_write":
      return { kind, name, description, sheet_id: "", range: "A:Z", columns: [], include_call_details: true };
    case "http_api":
      return { kind, name, description, url: "https://", method: "POST", params: [], headers: {}, timeout_s: 8, auth: { kind: "none", header: "", secret: "" } };
    case "whatsapp":
      return { kind, name, description, template: "", language: "en", params: [] };
  }
}

/** What stops the API accepting an action, said before it is sent; empty when ready. */
export function problems(a: Action): string[] {
  const out: string[] = [];
  if (!/^[a-z][a-z0-9_]{0,39}$/.test(a.name)) out.push("The name is lowercase letters, digits and underscores, starting with a letter.");
  if (!a.description.trim()) out.push("Say when the employee should use it.");
  if (a.kind === "http_api" && !/^https:\/\/[^/@:]+(\/|$)/.test(a.url)) out.push("The address must start with https:// and use the standard port.");
  if ((a.kind === "sheet_read" || a.kind === "sheet_write") && !a.sheet_id.trim()) out.push("Pick the sheet.");
  if (a.kind === "whatsapp" && !a.template.trim()) out.push("Name the approved template.");
  return out;
}
