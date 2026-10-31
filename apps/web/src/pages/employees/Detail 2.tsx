import { useState } from "react";
import { createPortal } from "react-dom";
import { NavLink, Outlet, useOutletContext, useParams } from "react-router";

import { type Employee, LANGUAGES, type Language, useEmployee, useEmployeeWrite, writes } from "../../lib/employees";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Avatar, StatusTag, channelLabel } from "./parts";

export type DetailContext = {
  employee: Employee;
  write: ReturnType<typeof useEmployeeWrite>;
  /** Bumped when the draft is replaced from outside the editor (discard, restore), so it reloads. */
  draftKey: number;
  reloadDraft: () => void;
};
export const useDetail = () => useOutletContext<DetailContext>();

const TABS = [
  ["script", "Script"],
  ["voice", "Voice"],
  ["behaviour", "Behaviour"],
  ["versions", "Versions"],
] as const;

export default function EmployeeDetail() {
  const { id = "" } = useParams();
  const query = useEmployee(id);
  const write = useEmployeeWrite(id);
  const [draftKey, setDraftKey] = useState(0);
  const employee = query.data;

  if (query.error) return <ErrorState error={query.error} retry={() => void query.refetch()} />;
  if (!employee)
    return (
      <div className="space-y-4">
        <Skeleton className="h-14 w-72" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    );

  const reloadDraft = () => setDraftKey((k) => k + 1);
  const languages = [employee.language, ...employee.extra_languages].map((l) => LANGUAGES[l as Language] ?? l).join(" · ");

  return (
    <div className="pb-24">
      <header className="flex flex-wrap items-center gap-4">
        <Avatar employee={employee} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="display truncate text-3xl">{employee.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-muted">
            <span>{employee.role_title || `${channelLabel(employee)} employee`}</span>
            <span aria-hidden>·</span>
            <span>{channelLabel(employee)}</span>
            <span aria-hidden>·</span>
            <span>{languages}</span>
          </p>
        </div>
        <StatusTag status={employee.status} />
      </header>

      {employee.warnings.length > 0 && (
        <ul className="mt-6 space-y-1 rounded-card border border-warn/40 p-4 text-sm text-warn">
          {employee.warnings.map((w) => (
            <li key={w}>● {w}</li>
          ))}
        </ul>
      )}

      <nav aria-label="Employee sections" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `-mb-px border-b-2 px-3.5 py-2.5 text-sm whitespace-nowrap transition-colors duration-150 ${
                isActive ? "border-accent text-ink-strong" : "border-transparent text-ink-muted hover:text-ink"
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-8">
        <Outlet context={{ employee, write, draftKey, reloadDraft } satisfies DetailContext} />
      </div>

      {/* Portalled: the page's enter animation would otherwise make <main> the bar's containing block. */}
      {employee.has_pending_edits &&
        createPortal(<PublishBar employee={employee} write={write} onDiscard={reloadDraft} />, document.body)}
    </div>
  );
}

/** Script edits wait here until the owner applies them to live calls (or throws them away). */
function PublishBar({ employee, write, onDiscard }: { employee: Employee; write: DetailContext["write"]; onDiscard: () => void }) {
  return (
    <div className="pop-in fixed inset-x-0 bottom-0 z-20 border-t border-line-accent bg-bg-deep/95 backdrop-blur-md md:left-[232px]" data-state="open">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 md:px-8">
        <p className="mr-auto text-sm text-ink">
          <span className="text-warn">●</span> Script changes are saved as a draft.{" "}
          <span className="text-ink-muted">
            {employee.published_version ? `Live calls use version ${employee.published_version}.` : "Nothing is live yet."}
          </span>
        </p>
        {write.error && <span className="text-sm text-danger">{write.error.message}</span>}
        {employee.published_version !== null && (
          <button
            type="button"
            className={btn.quiet}
            disabled={write.isPending}
            onClick={() => write.mutate(writes.discard(), { onSuccess: onDiscard })}
          >
            Discard changes
          </button>
        )}
        <button type="button" className={btn.primary} disabled={write.isPending} onClick={() => write.mutate(writes.publish())}>
          Apply to live calls
        </button>
      </div>
    </div>
  );
}
