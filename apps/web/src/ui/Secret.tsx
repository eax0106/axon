import { useState } from "react";

import { btn } from "./buttons";

/** A value shown exactly once (an API key, a signing secret), with a copy button and that warning. */
export function ShownOnce({ label, value, onDone }: { label: string; value: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  return (
    <div role="status" className="rounded-card border border-accent bg-accent-soft p-4">
      <p className="text-sm text-ink-strong">{label}</p>
      <p className="mt-1 text-xs text-ink-muted">Copy it now. It is shown this once and can't be seen again.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="num min-w-0 flex-1 rounded-ctl border border-line bg-bg px-3 py-2 text-sm break-all text-ink-strong" aria-label={label}>{value}</code>
        <button type="button" className={btn.ghost} onClick={() => void navigator.clipboard.writeText(value).then(() => setCopied(true))}>{copied ? "Copied" : "Copy"}</button>
        <button type="button" className={btn.quiet} onClick={onDone}>Done</button>
      </div>
    </div>
  );
}
