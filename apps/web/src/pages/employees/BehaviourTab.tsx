import { useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";

import { api, unwrap } from "../../lib/api";
import { CHANNELS, type Channel, type Settings, writes } from "../../lib/employees";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { Field } from "../../ui/Field";
import { ErrorState } from "../../ui/states";
import { useDetail } from "./Detail";

const TOGGLES: [keyof Settings, string, string][] = [
  ["ai_acknowledgement", "Say it's an AI up front", "Early in every call the employee says it is an AI assistant. It always tells the truth if asked, either way."],
  ["style_pack", "Warm, natural style", "Small acknowledgements such as \"okay\" or \"I see\", and varied phrasing."],
  ["power_prompting", "Follow \"About your business\" word for word", "That text is treated as your own instructions, not just background facts."],
];

export default function BehaviourTab() {
  const { employee, write } = useDetail();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { error, run: act } = useAction();
  const settings = employee.settings;

  const path = { params: { path: { employee_id: employee.id } } };

  function rename(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    write.mutate(writes.update({ name: String(form.get("name")).trim(), role_title: String(form.get("role")).trim() || null }));
  }

  return (
    <div className="max-w-2xl space-y-12">
      <form onSubmit={rename} className="space-y-4" aria-labelledby="identity">
        <h2 id="identity" className="eyebrow">Name and role</h2>
        <Field label="Name" name="name" defaultValue={employee.name} maxLength={100} required />
        <Field label="Role" name="role" defaultValue={employee.role_title ?? ""} maxLength={100} hint="How the employee describes their job, e.g. Sales assistant." />
        <button type="submit" className={btn.ghost} disabled={write.isPending}>
          Save name and role
        </button>
      </form>

      <section aria-labelledby="style" className="space-y-1">
        <h2 id="style" className="eyebrow mb-3">How they talk</h2>
        {TOGGLES.map(([key, label, hint]) => (
          <label key={key} className="flex cursor-pointer items-start justify-between gap-6 border-b border-line py-4">
            <span>
              <span className="block text-ink">{label}</span>
              <span className="mt-0.5 block text-sm text-ink-muted">{hint}</span>
            </span>
            <input
              type="checkbox"
              role="switch"
              checked={Boolean(settings[key])}
              onChange={(e) => write.mutate(writes.settings({ ...settings, [key]: e.target.checked }))}
              className="mt-1 size-5 shrink-0 accent-[var(--accent)]"
            />
          </label>
        ))}
        <p className="pt-2 text-xs text-ink-muted">These apply to the next call at once.</p>
      </section>

      <section aria-labelledby="status" className="space-y-3">
        <h2 id="status" className="eyebrow">On or off</h2>
        <p className="text-sm text-ink-muted">
          An employee goes live once it has a published script and a phone number, and you switch it on.
        </p>
        {employee.status === "live" ? (
          <button type="button" className={btn.ghost} onClick={() => write.mutate(writes.pause())}>
            Pause calls
          </button>
        ) : (
          <button type="button" className={btn.primary} onClick={() => write.mutate(writes.activate())}>
            Go live
          </button>
        )}
      </section>

      {(write.error ?? error) !== null && <ErrorState error={write.error ?? error} />}

      <section aria-labelledby="more" className="space-y-4">
        <h2 id="more" className="eyebrow">More</h2>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={btn.ghost}
            onClick={() =>
              void act(async () => {
                const copy = await unwrap(api.POST("/employees/{employee_id}/duplicate", path));
                await qc.invalidateQueries({ queryKey: ["employees"] });
                navigate(`/employees/${copy.id}`);
              })
            }
          >
            Duplicate
          </button>
          {(Object.keys(CHANNELS) as Channel[])
            .filter((c) => c !== employee.channel)
            .map((c) => (
              <Confirm
                key={c}
                trigger={<button type="button" className={btn.ghost}>Move to {CHANNELS[c].label}</button>}
                title={`Move ${employee.name} to ${CHANNELS[c].label}?`}
                body="Their call history is detached (calls stay on your account for billing), and a live employee is paused until you switch it on again. The script is kept; you may want to rewrite it for the new job."
                action={`Move to ${CHANNELS[c].label}`}
                onConfirm={() => write.mutate(writes.switchChannel(c))}
              />
            ))}
        </div>
        <div className="flex flex-wrap gap-2 border-t border-line pt-4">
          <Confirm
            danger
            trigger={<button type="button" className={btn.danger}>Start over</button>}
            title="Start over?"
            body="This wipes the script, published versions, what the employee was taught, its settings and call history, and sets it back to draft."
            action="Wipe and start over"
            onConfirm={() => write.mutate(writes.reset())}
          />
          <Confirm
            danger
            trigger={<button type="button" className={btn.danger}>Delete employee</button>}
            title={`Delete ${employee.name}?`}
            body="The employee stops taking and making calls and is removed. This cannot be undone."
            action="Delete"
            onConfirm={() =>
              void act(async () => {
                await unwrap(api.DELETE("/employees/{employee_id}", path));
                qc.removeQueries({ queryKey: ["employee", employee.id] });
                await qc.invalidateQueries({ queryKey: ["employees"] });
                navigate("/employees", { replace: true });
              })
            }
          />
        </div>
      </section>
    </div>
  );
}
