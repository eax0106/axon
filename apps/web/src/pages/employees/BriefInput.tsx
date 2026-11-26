import { useEffect, useRef, useState } from "react";

import { api, unwrap } from "../../lib/api";
import type { Language } from "../../lib/employees";
import { record } from "../../lib/recorder";
import { btn } from "../../ui/buttons";
import { Waveform } from "../../ui/Waveform";

type Recording = Awaited<ReturnType<typeof record>>;

/** One-tap starting points for an empty brief. Our own examples; the owner edits them freely. */
export const STARTERS: { label: string; brief: string }[] = [
  {
    label: "Property leads",
    brief:
      "We sell 2 and 3 BHK flats in Kokapet, Hyderabad. Call people who fill our website or Facebook form within a minute, find their budget, preferred locality and when they want to move, and book a site visit on a day that suits them.",
  },
  {
    label: "Clinic appointments",
    brief:
      "We are a dental clinic in Vijayawada. Call patients who asked for an appointment, confirm the problem in a few words, offer the next free slots between 10 AM and 7 PM, and book one. Remind them to bring old reports.",
  },
  {
    label: "Insurance renewals",
    brief:
      "We are an insurance agency. Call customers whose motor or health policy expires this month, remind them of the expiry date, tell them renewal takes five minutes, and ask whether they want the renewal link on WhatsApp or a call back from an advisor.",
  },
  {
    label: "Test drive booking",
    brief:
      "We are a car dealership in Pune. Call people who enquired about a car online, ask which model and variant they like, petrol or EV, and their budget, then book a test drive at the showroom or at their home.",
  },
  {
    label: "Old list revival",
    brief:
      "Call people who enquired with us in the last six months but never bought. Remind them who we are and what they asked about, ask if they still need it, and if yes, note their need and book a call back with our sales team.",
  },
  {
    label: "Course admissions",
    brief:
      "We run coaching classes for competitive exams. Call students or parents who left their number, ask which exam and year they are preparing for, explain batch timings and fees briefly, and book a free demo class.",
  },
];

/** The brief, typed or spoken. Speech arrives in chunks; each chunk's text is appended in order. */
export function BriefInput(props: {
  value: string;
  onChange: (v: string) => void;
  language: Language;
  onError: (e: unknown) => void;
}) {
  const [rec, setRec] = useState<Recording | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [pending, setPending] = useState(0);
  const latest = useRef(props.value);
  latest.current = props.value;
  const queue = useRef(Promise.resolve());

  useEffect(() => {
    if (!rec) return;
    const id = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [rec]);
  useEffect(() => () => rec?.stop(), [rec]);

  function transcribe(wav: Blob) {
    setPending((n) => n + 1);
    // One at a time, so the text lands in the order it was spoken.
    queue.current = queue.current.then(async () => {
      try {
        const { text } = await unwrap(
          api.POST("/ai/transcribe-chunk", {
            params: { query: { language: props.language } },
            body: wav as never,
            bodySerializer: (b: unknown) => b as Blob,
            headers: { "Content-Type": "audio/wav" },
          }),
        );
        if (text) props.onChange([latest.current.trim(), text].filter(Boolean).join(" "));
      } catch (err) {
        props.onError(err);
      } finally {
        setPending((n) => n - 1);
      }
    });
  }

  async function start() {
    try {
      setSeconds(0);
      setRec(await record(transcribe));
    } catch (err) {
      props.onError(err instanceof DOMException ? new Error("Allow the microphone to speak your brief.") : err);
    }
  }

  return (
    <>
      {!props.value.trim() && (
        <div className="mt-6">
          <p className="text-sm text-ink-muted">Start from an example, then change it to fit your business:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {STARTERS.map((s) => (
              <button key={s.label} type="button" className={btn.ghost} onClick={() => props.onChange(s.brief)}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="mt-6 rounded-card border border-line-accent bg-surface focus-within:border-accent">
        <label className="sr-only" htmlFor="brief">
          Brief
        </label>
        <textarea
          id="brief"
          rows={7}
          maxLength={6000}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          placeholder="We sell 2 and 3 BHK flats in Kokapet. Call people who fill our website form, find their budget and preferred locality, and book a site visit."
          className="block w-full resize-y rounded-t-card bg-transparent px-4 py-3.5 text-ink-strong outline-none placeholder:text-ink-muted"
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-line px-3 py-2.5">
          {rec ? (
            <>
              <button
                type="button"
                className={btn.danger}
                onClick={() => {
                  rec.stop();
                  setRec(null);
                }}
              >
                <span aria-hidden className="live-dot size-2 rounded-full bg-danger" /> Stop
              </button>
              <span className="num text-sm text-ink-muted" aria-live="polite">
                {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1">
                <Waveform analyser={rec.analyser} />
              </div>
            </>
          ) : (
            <button type="button" className={btn.ghost} onClick={() => void start()}>
              Speak instead
            </button>
          )}
          {pending > 0 && <span className="text-sm text-ink-muted">Writing down what you said…</span>}
          <span className="num ml-auto text-xs text-ink-muted">{props.value.length}/6000</span>
        </div>
      </div>
    </>
  );
}
