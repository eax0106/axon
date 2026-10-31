import { type Contact, STATUS_LABEL, gridColumns, tally } from "../../lib/campaigns";

const DOT: Record<Contact["status"], string> = {
  pending: "fill-[var(--line-accent)]",
  calling: "fill-[var(--accent)] constellation-live",
  callback: "fill-[var(--info)]",
  done: "fill-[var(--accent)]",
  exhausted: "fill-[var(--chart-3)]",
  skipped: "fill-[var(--line)]",
  canceled: "fill-[var(--line)]",
};

/**
 * Every contact as one dot: mint once reached, sage when nobody answered, faint when skipped,
 * pulsing while on a call. Static SVG; only the few calling dots animate, so 2,000 stay cheap.
 */
export function Constellation({ contacts, total }: { contacts: Contact[]; total: number }) {
  const cols = gridColumns(contacts.length);
  const rows = Math.ceil(contacts.length / cols);
  const counts = tally(contacts);
  const finished = counts.done + counts.exhausted + counts.skipped + counts.canceled;
  return (
    <figure className="rounded-card border border-line bg-surface p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="display num text-4xl" aria-live="polite">
          {finished}<span className="text-lg text-ink-muted"> / {total} finished</span>
        </p>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
          {(Object.keys(DOT) as Contact["status"][]).filter((k) => counts[k]).map((k) => (
            <li key={k} className="flex items-center gap-1.5">
              <svg viewBox="0 0 10 10" className="size-2.5" aria-hidden><circle cx="5" cy="5" r="4" className={DOT[k].split(" ")[0]} /></svg>
              {STATUS_LABEL[k]} <span className="num text-ink">{counts[k]}</span>
            </li>
          ))}
        </ul>
      </div>
      {contacts.length > 0 ? (
        <svg viewBox={`0 0 ${cols * 10} ${rows * 10}`} className="mt-5 max-h-[420px] w-full" role="img" aria-label={`${total} contacts: ${finished} finished, ${counts.calling} on a call now`}>
          {contacts.map((c, i) => (
            <circle key={c.id} cx={(i % cols) * 10 + 5} cy={Math.floor(i / cols) * 10 + 5} r="3.2" className={DOT[c.status]}>
              <title>{`${c.name || c.phone}: ${STATUS_LABEL[c.status]}`}</title>
            </circle>
          ))}
        </svg>
      ) : (
        <p className="mt-5 text-sm text-ink-muted">Add contacts and each one appears here as a dot.</p>
      )}
      {total > contacts.length && <figcaption className="mt-2 text-xs text-ink-muted">Showing the first {contacts.length}.</figcaption>}
    </figure>
  );
}
