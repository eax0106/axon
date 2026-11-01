import { useState } from "react";

import { useAction } from "../../lib/useAction";
import { ErrorState } from "../../ui/states";

export const card = "rounded-card border border-line bg-surface p-5";
export const input = "h-10 rounded-ctl border border-line-accent bg-bg px-3 text-sm text-ink-strong outline-none focus:border-accent";
export const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "never");

/** An admin write: busy while it runs, then says exactly what it changed (or why it was refused). */
export function useWrite() {
  const action = useAction();
  const [done, setDone] = useState("");
  const write = (go: () => Promise<string>) => {
    setDone("");
    void action.run(async () => setDone(await go()));
  };
  const outcome = (
    <>
      {done && <p role="status" className="mt-2 text-sm text-accent">{done}</p>}
      {action.error !== null && <div className="mt-2"><ErrorState error={action.error} /></div>}
    </>
  );
  return { busy: action.busy, write, outcome };
}

export function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className={card}>
      <h2 id={id} className="eyebrow">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}
