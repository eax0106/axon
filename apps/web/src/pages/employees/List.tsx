import { Link } from "react-router";

import { type Employee, LANGUAGES, type Language, useEmployees } from "../../lib/employees";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";
import { Avatar, StatusTag, channelLabel } from "./parts";

export default function EmployeesList() {
  const list = useEmployees();
  const employees = list.data ?? [];

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">Employees</p>
          <h1 className="display mt-3 text-4xl">Your AI team</h1>
        </div>
        {employees.length > 0 && (
          <Link to="/employees/new" className={btn.primary}>
            Hire an employee
          </Link>
        )}
      </div>

      <div className="mt-10">
        {list.error ? (
          <ErrorState error={list.error} retry={() => void list.refetch()} />
        ) : !list.data ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-36 rounded-card" />
            ))}
          </div>
        ) : employees.length === 0 ? (
          <Empty />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {employees.map((e) => (
              <li key={e.id}>
                <Card employee={e} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Card({ employee: e }: { employee: Employee }) {
  const languages = [e.language, ...e.extra_languages].map((l) => LANGUAGES[l as Language] ?? l).join(" · ");
  return (
    <Link
      to={`/employees/${e.id}`}
      className="group block h-full rounded-card border border-line bg-surface p-5 transition-colors duration-200 hover:border-line-accent"
    >
      <div className="flex items-start gap-3.5">
        <Avatar employee={e} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-ink-strong">{e.name}</p>
          <p className="truncate text-sm text-ink-muted">{e.role_title || `${channelLabel(e)} employee`}</p>
        </div>
        <StatusTag status={e.status} />
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-y-1 text-sm">
        <dt className="text-ink-muted">Channel</dt>
        <dd className="text-right text-ink">{channelLabel(e)}</dd>
        <dt className="text-ink-muted">Speaks</dt>
        <dd className="truncate text-right text-ink">{languages}</dd>
      </dl>
      {e.has_pending_edits && (
        <p className="eyebrow mt-4 text-warn">● Unpublished changes</p>
      )}
    </Link>
  );
}

/** The one showpiece on this screen: only when there is nobody yet. */
function Empty() {
  return (
    <div className="glow relative overflow-hidden rounded-card border border-line-accent bg-surface px-6 py-16 text-center md:py-24">
      <p className="eyebrow">Your first hire</p>
      <h2 className="display mx-auto mt-4 max-w-xl text-4xl md:text-5xl">
        Describe the job. <span className="text-accent">Axon drafts the employee.</span>
      </h2>
      <p className="mx-auto mt-4 max-w-md text-ink-muted">
        Tell it what your business does and who it should call, in your own words or out loud. You review every line
        before it speaks to anyone.
      </p>
      <Link to="/employees/new" className={`${btn.primary} mt-8 h-11 px-6`}>
        Hire your first AI employee
      </Link>
    </div>
  );
}
