import type { ReactNode } from "react";

import { type Version, useVersions, writes } from "../../lib/employees";
import { btn } from "../../ui/buttons";
import { Confirm } from "../../ui/Confirm";
import { ErrorState, Skeleton } from "../../ui/states";
import { useDetail } from "./Detail";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

/** The last three published scripts as a perspective deck; hover or focus fans it out. */
export default function VersionsTab() {
  const { employee, write, reloadDraft } = useDetail();
  const versions = useVersions(employee.id);
  const list = [...(versions.data ?? [])].sort((a, b) => b.version - a.version);

  if (versions.error) return <ErrorState error={versions.error} retry={() => void versions.refetch()} />;
  if (!versions.data) return <Skeleton className="h-72 rounded-card" />;
  if (list.length === 0)
    return (
      <div className="rounded-card border border-dashed border-line p-10 text-center">
        <p className="display text-2xl">Nothing published yet.</p>
        <p className="mt-2 text-sm text-ink-muted">Each time you apply changes to live calls, a version lands here. The last three are kept.</p>
      </div>
    );

  return (
    <div>
      <p className="text-sm text-ink-muted">The last three published scripts. Restoring one puts it live on the next call.</p>
      <ol className="group relative mt-8 [perspective:1400px]" style={{ height: 210 + (list.length - 1) * 164 }}>
        {list.map((v, i) => (
          <li
            key={v.version}
            style={{ zIndex: list.length - i, ["--i" as string]: i }}
            className="absolute inset-x-0 top-0 mx-auto w-full max-w-xl origin-top transition-transform duration-300 ease-[var(--ease-panel)] [transform:translateY(calc(var(--i)*14px))_scale(calc(1-var(--i)*0.04))_rotateX(calc(var(--i)*-4deg))] group-focus-within:[transform:translateY(calc(var(--i)*164px))] group-hover:[transform:translateY(calc(var(--i)*164px))] motion-reduce:[transform:translateY(calc(var(--i)*164px))]"
          >
            <Card version={v} current={v.version === employee.published_version}>
              {v.version !== employee.published_version && (
                <Confirm
                  trigger={<button type="button" className={btn.ghost}>Restore</button>}
                  title={`Restore version ${v.version}?`}
                  body="It becomes the live script on the next call, as a new version. Unapplied changes in the editor are replaced."
                  action="Restore and go live"
                  onConfirm={() => write.mutate(writes.restore(v.version), { onSuccess: reloadDraft })}
                />
              )}
            </Card>
          </li>
        ))}
      </ol>
      {write.error && <ErrorState error={write.error} />}
    </div>
  );
}

function Card({ version: v, current, children }: { version: Version; current: boolean; children: ReactNode }) {
  const sections = v.script.sections ?? [];
  return (
    <article className={`rounded-card border bg-surface p-5 ${current ? "border-accent" : "border-line-accent"}`}>
      <header className="flex items-center justify-between gap-3">
        <p>
          <span className="display text-lg">Version {v.version}</span>
          {current && <span className="eyebrow ml-3">● Live</span>}
        </p>
        <span className="text-xs text-ink-muted">{when(v.published_at)}</span>
      </header>
      <p className="mt-3 line-clamp-2 text-sm text-ink">{v.script.welcome_message || "No welcome line."}</p>
      <p className="mt-2 truncate text-xs text-ink-muted">
        {sections.length} step{sections.length === 1 ? "" : "s"}
        {sections.length > 0 && `: ${sections.map((s) => s.title).join(" · ")}`}
      </p>
      <div className="mt-4 flex justify-end">{children}</div>
    </article>
  );
}
