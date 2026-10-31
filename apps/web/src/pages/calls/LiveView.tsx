import { useEffect, useRef } from "react";

import { type LiveState, STAGES, type Stage } from "../../lib/live";
import { Orb } from "../../ui/Orb";

const LABEL: Record<Stage, string> = {
  ringing: "Ringing",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  done: "Done",
};
// For calls with no audio in this browser, the orb breathes with the call's state instead.
const STATE_LEVEL: Record<Stage, number> = { ringing: 0.1, listening: 0.06, thinking: 0.18, speaking: 0.5, done: 0 };

/** One live call: the orb, where the call is, and what is being said, as it happens. */
export function LiveView({ state, level, who }: { state: LiveState; level?: () => number; who: string }) {
  const stage = useRef(state.stage);
  stage.current = state.stage;
  const orbLevel = useRef(level ?? (() => STATE_LEVEL[stage.current])).current;
  const live = state.stage !== "done" && state.connection !== "refused";
  const end = useRef<HTMLLIElement>(null);
  // Braces matter: newer browsers return a promise from scrollIntoView, which React would take
  // for a cleanup function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [state.turns]);

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(240px,320px)_1fr]">
      <div className="flex flex-col items-center">
        <div className="w-full max-w-[320px]">
          <Orb level={orbLevel} label={`${who}, ${LABEL[state.stage].toLowerCase()}`} />
        </div>
        <p className={`eyebrow mt-4 inline-flex items-center gap-2 ${live ? "" : "text-ink-muted"}`} aria-live="polite">
          {live && <span aria-hidden className="live-dot size-2 rounded-full bg-accent" />}
          {state.connection === "refused" ? "Not available" : live ? `On a call · ${LABEL[state.stage]}` : "Call ended"}
        </p>
        <Stepper stage={state.stage} />
      </div>

      <section aria-label="Transcript" className="flex min-h-[320px] flex-col rounded-card border border-line bg-surface">
        <ol className="flex-1 space-y-4 overflow-y-auto p-5" aria-live="polite">
          {state.turns.map((t, i) => (
            <li key={i} className={`flex ${t.who === "caller" ? "justify-end" : ""}`}>
              <p
                className={`max-w-[80%] rounded-card px-4 py-2.5 text-sm ${
                  t.who === "caller" ? "bg-accent-soft text-ink-strong" : "border border-line text-ink"
                }`}
              >
                <span className="eyebrow mb-1 block text-[10px] text-ink-muted">{t.who === "caller" ? "Caller" : who}</span>
                {t.text}
                {state.stage === "speaking" && t.who === "employee" && i === state.turns.length - 1 && (
                  <span aria-hidden className="live-caret ml-0.5 inline-block h-4 w-0.5 translate-y-0.5 bg-accent" />
                )}
              </p>
            </li>
          ))}
          {state.turns.length === 0 && (
            <li className="py-16 text-center text-sm text-ink-muted">
              {state.connection === "refused" ? "This call isn't on your account or has finished." : "Words appear here as they are spoken."}
            </li>
          )}
          <li ref={end} aria-hidden />
        </ol>
        {(state.notes.length > 0 || state.endedReason) && (
          <ul className="space-y-1 border-t border-line px-5 py-3 text-xs text-ink-muted">
            {state.notes.map((n, i) => (
              <li key={i}>· {n}</li>
            ))}
            {state.endedReason && <li>· Ended: {state.endedReason.replaceAll("_", " ")}</li>}
          </ul>
        )}
      </section>
    </div>
  );
}

/** RINGING · LISTENING · THINKING · SPEAKING · DONE, with the mint dot gliding to the current one. */
function Stepper({ stage }: { stage: Stage }) {
  const at = STAGES.indexOf(stage);
  return (
    <ol className="relative mt-6 grid w-full max-w-[340px] grid-cols-5" aria-label="Call stage">
      {/* Equal columns: dot i sits at the centre of column i, so the glide lands exactly on it. */}
      <span aria-hidden className="absolute top-[5px] right-[10%] left-[10%] h-px bg-line" />
      <span
        aria-hidden
        className="absolute top-0 z-10 size-[11px] rounded-full bg-accent shadow-[0_0_14px_var(--accent)] transition-[left] duration-300 ease-[var(--ease-panel)]"
        style={{ left: `calc(${((at + 0.5) / STAGES.length) * 100}% - 5.5px)` }}
      />
      {STAGES.map((s, i) => (
        <li key={s} className="relative flex flex-col items-center gap-2" aria-current={i === at ? "step" : undefined}>
          <span aria-hidden className={`size-[11px] rounded-full border ${i <= at ? "border-accent" : "border-line-accent"} bg-bg`} />
          <span className={`text-[10px] font-semibold tracking-[0.1em] uppercase ${i === at ? "text-accent" : "text-ink-muted"}`}>
            {LABEL[s]}
          </span>
        </li>
      ))}
    </ol>
  );
}
