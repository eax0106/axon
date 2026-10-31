/** Paired bars per label (total and the part that succeeded), hand-drawn SVG with a table for screen readers. */
export function Bars(props: {
  data: { label: string; total: number; part: number }[];
  highlight?: string;
  caption: string;
  totalName: string;
  partName: string;
}) {
  const max = Math.max(1, ...props.data.map((d) => d.total));
  const w = 100 / props.data.length;
  return (
    <figure>
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden className="h-36 w-full">
        {props.data.map((d, i) => {
          const th = (d.total / max) * 38;
          const ph = (d.part / max) * 38;
          const on = d.label === props.highlight;
          return (
            <g key={d.label}>
              <rect x={i * w + w * 0.18} y={40 - th} width={w * 0.64} height={th} rx="0.4" className="fill-[var(--line-accent)]" />
              <rect x={i * w + w * 0.18} y={40 - ph} width={w * 0.64} height={ph} rx="0.4" className={on ? "fill-[var(--accent)]" : "fill-[var(--chart-2)]"} />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-ink-muted" aria-hidden>
        {props.data.filter((_, i) => i % 3 === 0).map((d) => (
          <span key={d.label}>{d.label}</span>
        ))}
      </div>
      <table className="sr-only">
        <caption>{props.caption}</caption>
        <thead>
          <tr>
            <th>Hour</th>
            <th>{props.totalName}</th>
            <th>{props.partName}</th>
          </tr>
        </thead>
        <tbody>
          {props.data.map((d) => (
            <tr key={d.label}>
              <td>{d.label}</td>
              <td>{d.total}</td>
              <td>{d.part}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
