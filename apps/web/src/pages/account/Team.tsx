import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { ApiError, api, unwrap } from "../../lib/api";
import { useMe } from "../../lib/queries";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { Field, SubmitButton } from "../../ui/Field";
import { ErrorState, Skeleton } from "../../ui/states";

const card = "rounded-card border border-line bg-surface p-6";
const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

/** The owner invites colleagues by email. Members see calls, leads and campaigns; billing, numbers,
 *  API keys and account settings stay with the owner. Removing a member signs them out at once. */
export function Team() {
  const me = useMe().data;
  const owner = me?.user.role === "owner";
  const qc = useQueryClient();
  const team = useQuery({ queryKey: ["team"], queryFn: () => unwrap(api.GET("/team")), enabled: owner });
  const [sent, setSent] = useState("");
  const { busy, error, run } = useAction();
  const taken = error instanceof ApiError && error.status === 409 ? error.message : undefined;
  const refresh = () => qc.invalidateQueries({ queryKey: ["team"] });

  function invite(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const email = String(new FormData(form).get("email")).trim();
    setSent("");
    void run(async () => {
      await unwrap(api.POST("/team/invites", { body: { email } }));
      form.reset();
      setSent(email);
      await refresh();
    });
  }
  const remove = (id: string) =>
    void run(async () => {
      await unwrap(api.DELETE("/team/members/{user_id}", { params: { path: { user_id: id } } }));
      await refresh();
    });
  const revoke = (id: string) =>
    void run(async () => {
      await unwrap(api.DELETE("/team/invites/{invite_id}", { params: { path: { invite_id: id } } }));
      await refresh();
    });

  return (
    <section aria-labelledby="team" className={card}>
      <h2 id="team" className="eyebrow">Team</h2>
      {!me ? (
        <Skeleton className="mt-4 h-24" />
      ) : !owner ? (
        <p className="mt-2 text-sm text-ink-muted">You are a member of this account. Only the owner invites or removes people.</p>
      ) : team.error ? (
        <div className="mt-4"><ErrorState error={team.error} retry={() => void team.refetch()} /></div>
      ) : !team.data ? (
        <Skeleton className="mt-4 h-24" />
      ) : (
        <>
          <ul className="mt-4 divide-y divide-line text-sm">
            {team.data.members.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate text-ink">{m.email}</span>
                <span className="flex items-center gap-3 text-xs text-ink-muted">
                  {m.role === "owner" ? "Owner" : "Member"}
                  {m.two_factor && " · two-step on"}
                  {m.role === "member" && (
                    <Confirm
                      trigger={<button type="button" className={btn.quiet} disabled={busy}>Remove</button>}
                      title={`Remove ${m.email}?`}
                      body="They are signed out at once and can no longer sign in to this account. Their notes stay."
                      action="Remove"
                      danger
                      onConfirm={() => remove(m.id)}
                    />
                  )}
                </span>
              </li>
            ))}
            {team.data.invites.map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-3 py-2">
                <span className="min-w-0 truncate text-ink-muted">{i.email}</span>
                <span className="flex items-center gap-3 text-xs text-ink-muted">
                  Invited {day(i.sent_at)}, open until {day(i.expires_at)}
                  <button type="button" className={btn.quiet} disabled={busy} onClick={() => revoke(i.id)}>Cancel</button>
                </span>
              </li>
            ))}
          </ul>
          <form onSubmit={invite} className="mt-4 space-y-3">
            <Field label="Invite a colleague" name="email" type="email" autoComplete="off" required error={taken} hint="They get an email link to set a password. It works once, for 7 days." />
            <SubmitButton busy={busy} busyText="Sending…">Send invite</SubmitButton>
            {sent && <p role="status" className="text-sm text-accent">Invite sent to {sent}.</p>}
          </form>
        </>
      )}
      {error !== null && !taken && <div className="mt-4"><ErrorState error={error} /></div>}
    </section>
  );
}
