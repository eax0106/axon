/** A small area line of values, drawn in the accent token. Values are oldest first. */
export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const w = 240;
  const h = 48;
  const max = Math.max(...values, 1);
  const x = (i: number) => (i / Math.max(values.length - 1, 1)) * w;
  const y = (v: number) => h - 2 - (v / max) * (h - 6);
  const line = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label={label} className="h-12 w-full text-accent">
      <path d={`${line}L${w},${h}L0,${h}Z`} fill="currentColor" opacity="0.12" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
