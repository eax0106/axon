/** Every page in the rail and the command palette. Each phase adds its own entries. */
export const NAV = [
  { to: "/", label: "Overview", keywords: "home dashboard start" },
  { to: "/employees", label: "Employees", keywords: "agents team ai staff hire script voice" },
  { to: "/employees/new", label: "Hire", keywords: "new employee create agent brief" },
  { to: "/campaigns", label: "Campaigns", keywords: "bulk list csv dialer outbound" },
  { to: "/calls", label: "Conversations", keywords: "calls history transcripts recordings log" },
  { to: "/leads", label: "Leads", keywords: "contacts customers crm kanban export" },
  { to: "/numbers", label: "Numbers", keywords: "phone number buy kyc channels rent" },
  { to: "/billing", label: "Billing", keywords: "credits wallet top up invoice gst statement spend" },
  { to: "/account", label: "Account", keywords: "profile phone verify settings me" },
] as const;
