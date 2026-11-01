import { NavLink, Navigate, Route, Routes } from "react-router";

import { AccountDetail, Accounts } from "./Accounts";
import { Inbox } from "./Inbox";
import { Providers } from "./Providers";
import { Rules } from "./Rules";
import { System } from "./System";
import { Voices } from "./Voices";

const TABS = [
  ["accounts", "Accounts"],
  ["support", "Support inbox"],
  ["system", "System"],
  ["providers", "Providers"],
  ["voices", "Voices"],
  ["rules", "Dialing rules"],
] as const;

/** The ALTERX staff console. Only reached through StaffOnly in App.tsx; the API checks again. */
export default function Admin() {
  return (
    <>
      <p className="eyebrow">Staff console</p>
      <h1 className="display mt-3 text-4xl">Run the platform</h1>
      <nav aria-label="Staff console" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(([to, label]) => (
          <NavLink key={to} to={`/admin/${to}`} className={({ isActive }) => `-mb-px border-b-2 px-3.5 py-2.5 text-sm whitespace-nowrap transition-colors duration-150 ${isActive ? "border-accent text-ink-strong" : "border-transparent text-ink-muted hover:text-ink"}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-8">
        <Routes>
          <Route index element={<Navigate to="accounts" replace />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="accounts/:id" element={<AccountDetail />} />
          <Route path="support" element={<Inbox />} />
          <Route path="system" element={<System />} />
          <Route path="providers" element={<Providers />} />
          <Route path="voices" element={<Voices />} />
          <Route path="rules" element={<Rules />} />
        </Routes>
      </div>
    </>
  );
}
