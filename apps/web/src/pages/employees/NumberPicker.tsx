import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { api, unwrap } from "../../lib/api";
import { useNumbers } from "../../lib/billing";
import { useAction } from "../../lib/useAction";
import { ErrorState } from "../../ui/states";
import { useDetail } from "./Detail";

/** Which of the account's numbers this employee calls and answers from. */
export function NumberPicker() {
  const { employee } = useDetail();
  const numbers = useNumbers();
  const qc = useQueryClient();
  const { busy, error, run } = useAction();
  const p = { params: { path: { employee_id: employee.id } } };
  const free = (numbers.data ?? []).filter((n) => n.status !== "released" && (!n.employee_id || n.employee_id === employee.id));
  const current = numbers.data?.find((n) => n.id === employee.number_id);
  const after = async () => {
    await qc.invalidateQueries({ queryKey: ["employee", employee.id] });
    void qc.invalidateQueries({ queryKey: ["numbers"] });
  };

  return (
    <section aria-labelledby="number" className="space-y-3">
      <h2 id="number" className="eyebrow">Phone number</h2>
      {numbers.data && free.length === 0 && !current ? (
        <p className="text-sm text-ink-muted">
          No free number on your account.{" "}
          <Link to="/numbers" className="text-accent underline underline-offset-4">
            Get a number
          </Link>
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="pick-number" className="sr-only">
            Number
          </label>
          <select
            id="pick-number"
            value={employee.number_id ?? ""}
            disabled={busy || !numbers.data}
            onChange={(e) =>
              void run(async () => {
                if (e.target.value) await unwrap(api.PUT("/employees/{employee_id}/number", { ...p, body: { number_id: e.target.value } }));
                else await unwrap(api.DELETE("/employees/{employee_id}/number", p));
                await after();
              })
            }
            className="num h-10 min-w-56 rounded-ctl border border-line-accent bg-surface px-3 text-ink-strong outline-none focus:border-accent"
          >
            <option value="">No number</option>
            {free.map((n) => (
              <option key={n.id} value={n.id}>
                {n.e164}
              </option>
            ))}
          </select>
          {current && current.status !== "active" && <span className="text-sm text-warn">This number's rent is overdue.</span>}
        </div>
      )}
      {error !== null && <ErrorState error={error} />}
    </section>
  );
}
