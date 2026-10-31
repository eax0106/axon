/** Every page in the rail and the command palette. Each phase adds its own entries. */
export const NAV = [
  { to: "/", label: "Overview", keywords: "home dashboard start" },
  { to: "/account", label: "Account", keywords: "profile phone verify settings me" },
] as const;
