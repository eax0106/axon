import type { ReactNode } from "react";

import { CyclingLine } from "../ui/CyclingLine";

const WORDS = ["sleeps.", "forgets a lead.", "keeps a caller waiting."];
const FACTS = [
  ["Calls new leads", "within seconds"],
  ["Speaks", "Telugu · Hindi · English"],
  ["Billed", "from pickup, per second"],
] as const;

/** Sign-in and sign-up: the brand story on the left, the form on the right (stacked on a phone). */
export function AuthLayout({ eyebrow, title, sub, children }: { eyebrow: string; title: string; sub: string; children: ReactNode }) {
  return (
    <div className="glow min-h-dvh lg:grid lg:grid-cols-[1.1fr_1fr]">
      <section className="flex flex-col justify-between border-line px-6 pt-10 lg:border-r lg:px-14 lg:py-14">
        <p className="flex items-center gap-2.5">
          <span aria-hidden className="size-2.5 rounded-full bg-accent shadow-[0_0_12px_var(--accent)]" />
          <span className="display text-lg">Axon</span>
          <span className="text-xs text-ink-muted">by ALTERX</span>
        </p>
        <div className="hidden lg:block">
          <p className="eyebrow">AI phone employees</p>
          <p className="display mt-4 max-w-xl text-[60px] leading-[1.05] tracking-[-0.03em]">
            <CyclingLine lead="Your AI employee never" words={WORDS} sentence="Your AI employee never sleeps, forgets a lead or keeps a caller waiting." />
          </p>
          <dl className="mt-12 max-w-md divide-y divide-line border-y border-line">
            {FACTS.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 py-3.5 text-sm">
                <dt className="text-ink-muted">{label}</dt>
                <dd className="text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <p className="hidden text-xs text-ink-muted lg:block">Built for Indian businesses.</p>
      </section>

      <main className="grid place-items-center px-6 py-12 lg:px-14">
        <div className="page-in w-full max-w-sm">
          <p className="eyebrow">{eyebrow}</p>
          <h1 className="display mt-3 text-4xl">{title}</h1>
          <p className="mt-2 text-ink-muted">{sub}</p>
          {children}
        </div>
      </main>
    </div>
  );
}
