/** Button looks, shared so every screen presses the same way (150 ms, scale 0.98). */
const base =
  "inline-flex h-9 items-center justify-center gap-2 rounded-ctl px-3.5 text-sm font-medium transition-[background-color,color,border-color,transform,opacity] duration-150 active:scale-[0.98] disabled:pointer-events-none disabled:opacity-50";
export const btn = {
  primary: `${base} bg-btn text-accent-ink hover:brightness-125`,
  ghost: `${base} border border-line text-ink hover:border-line-accent hover:text-ink-strong`,
  quiet: `${base} text-ink-muted hover:bg-accent-soft hover:text-ink`,
  danger: `${base} border border-danger/40 text-danger hover:bg-danger/10`,
};
