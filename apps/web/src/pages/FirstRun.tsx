import { Link } from "react-router";

import { useNumbers } from "../lib/billing";
import { useEmployees } from "../lib/employees";
import { useMe } from "../lib/queries";

/** From sign-up to a working AI employee, as one checklist read from the account's real state. */
export function FirstRun() {
  const employees = useEmployees().data;
  const numbers = useNumbers().data;
  const me = useMe().data;
  if (!employees || !numbers || !me) return null;

  const first = employees[0];
  const steps = [
    { done: employees.length > 0, label: "Hire your first AI employee", to: "/employees/new" },
    { done: employees.some((e) => e.published_version !== null), label: "Review the script and apply it", to: first ? `/employees/${first.id}/script` : "/employees/new" },
    { done: me.account.owner_phone !== "", label: "Verify your phone for free test calls", to: "/account" },
    { done: numbers.some((n) => n.status === "active"), label: "Get a phone number", to: "/numbers" },
    { done: employees.some((e) => e.status === "live"), label: "Attach the number and go live", to: first ? `/employees/${first.id}/behaviour` : "/employees/new" },
  ];
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;
  const next = steps.find((s) => !s.done);

  return (
    <section aria-labelledby="first-run" className="reveal mt-10 max-w-2xl rounded-card border border-line-accent bg-surface p-6">
      <div className="flex items-baseline justify-between gap-4">
        <h2 id="first-run" className="display text-xl">Get your first employee on the phone</h2>
        <span className="num text-sm text-ink-muted">
          {steps.length - left}/{steps.length}
        </span>
      </div>
      <div className="mt-3 h-1 overflow-hidden rounded-full bg-line" aria-hidden>
        <div
          className="h-full origin-left rounded-full bg-accent transition-transform duration-700 ease-[var(--ease-reveal)]"
          style={{ transform: `scaleX(${(steps.length - left) / steps.length})` }}
        />
      </div>
      <ol className="mt-5 space-y-1">
        {steps.map((s, i) => (
          <li key={s.label}>
            <Link
              to={s.to}
              aria-current={s === next ? "step" : undefined}
              className="flex items-center gap-3 rounded-ctl px-2 py-2 text-sm transition-colors duration-150 hover:bg-accent-soft aria-[current=step]:bg-accent-soft"
            >
              <span
                aria-hidden
                className={`num grid size-6 shrink-0 place-items-center rounded-full border text-xs ${
                  s.done ? "border-accent bg-accent text-bg" : "border-line-accent text-ink-muted"
                }`}
              >
                {s.done ? "✓" : i + 1}
              </span>
              <span className={s.done ? "text-ink-muted line-through" : "text-ink-strong"}>{s.label}</span>
              <span className="sr-only">{s.done ? "(done)" : ""}</span>
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
