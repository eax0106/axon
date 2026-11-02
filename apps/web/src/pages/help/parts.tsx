import { useState } from "react";
import { Link } from "react-router";

import { useEmployees } from "../../lib/employees";
import { useInstant } from "../../lib/instant";
import { btn } from "../../ui/buttons";

export const origin = () => location.origin;

export function Code({ children }: { children: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative my-3">
      <pre tabIndex={0} className="num overflow-x-auto rounded-ctl border border-line bg-bg p-3 pr-20 text-xs leading-relaxed text-ink">{children}</pre>
      <button type="button" className={`${btn.quiet} absolute top-1.5 right-1.5 h-7 px-2 text-xs`} onClick={() => void navigator.clipboard.writeText(children).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</button>
    </div>
  );
}

export function Steps({ children }: { children: React.ReactNode }) {
  return <ol className="my-3 list-decimal space-y-2 pl-5 marker:text-ink-muted">{children}</ol>;
}

/** The lead URL of one of the reader's own Instant employees, so a guide shows real values. */
export function LeadUrl() {
  const instant = (useEmployees().data ?? []).filter((e) => e.channel === "instant");
  const [picked, setPicked] = useState("");
  const id = picked || instant[0]?.id || "";
  const info = useInstant(id);
  if (instant.length === 0)
    return (
      <p className="my-3 rounded-ctl border border-dashed border-line p-4 text-sm text-ink-muted">
        You have no Instant employee yet, so there is no lead URL to show. <Link to="/employees/new" className="text-accent underline">Hire one</Link> and this guide fills in its address.
      </p>
    );
  return (
    <div className="my-3 rounded-ctl border border-line-accent bg-surface p-4 text-sm">
      {instant.length > 1 && (
        <label className="mb-3 flex items-center gap-2 text-ink-muted">
          Employee
          <select value={id} onChange={(e) => setPicked(e.target.value)} className="h-8 rounded-ctl border border-line bg-bg px-2 text-ink">
            {instant.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
        </label>
      )}
      <dl className="space-y-2">
        <div><dt className="text-ink-muted">Lead URL</dt><dd className="num break-all text-ink-strong">{info.data ? `${origin()}/api${info.data.intake_path}` : "…"}</dd></div>
        <div><dt className="text-ink-muted">Secret header</dt><dd className="num text-ink-strong">{info.data?.secret_header ?? "…"}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-ink-muted">The secret itself is on the employee's <Link to={`/employees/${id}/instant`} className="text-accent underline">Instant tab</Link> (Reveal). Treat it like a password.</p>
    </div>
  );
}

export const A = ({ to, children }: { to: string; children: React.ReactNode }) => <Link to={to} className="text-accent underline">{children}</Link>;
