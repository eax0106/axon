import { Suspense, lazy } from "react";

export type OrbProps = { level: () => number };

const OrbCanvas = lazy(() => import("./OrbCanvas"));
const reduced = () => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The voice of the call. WebGL loads only where an orb is shown; reduced motion gets a still glow. */
export function Orb({ level, label }: OrbProps & { label: string }) {
  const still = <div className="size-full rounded-full bg-[radial-gradient(circle_at_40%_35%,var(--accent),var(--accent-soft)_55%,transparent_70%)] opacity-70" />;
  return (
    <div role="img" aria-label={label} className="aspect-square w-full">
      {reduced() ? still : <Suspense fallback={still}><OrbCanvas level={level} /></Suspense>}
    </div>
  );
}
