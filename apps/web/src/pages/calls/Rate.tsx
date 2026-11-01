import { type FormEvent, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState } from "../../ui/states";

/** Rate how the employee did on this call; the rating and note go to the Axon team. */
export function Rate({ callId }: { callId: string }) {
  const [stars, setStars] = useState(0);
  const [sent, setSent] = useState(false);
  const { busy, error, run } = useAction();
  function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const body = String(new FormData(e.currentTarget).get("note")).trim();
    void run(async () => {
      await unwrap(api.POST("/support/rating", { body: { call_id: callId, rating: stars, body } }));
      setSent(true);
    });
  }
  return (
    <section aria-labelledby="rate">
      <h2 id="rate" className="eyebrow">Rate this call</h2>
      {sent ? <p role="status" className="mt-2 text-sm text-accent">Thanks. The Axon team sees it with the call.</p> : (
        <form onSubmit={send} className="mt-3 space-y-3">
          <div role="radiogroup" aria-label="Rating" className="flex gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" role="radio" aria-checked={stars === n} aria-label={`${n} of 5`} onClick={() => setStars(n)}
                className={`size-9 rounded-ctl text-lg transition-colors duration-150 ${n <= stars ? "text-warn" : "text-ink-muted hover:text-ink"}`}>★</button>
            ))}
          </div>
          {stars > 0 && (
            <>
              <label className="block">
                <span className="sr-only">What happened (optional)</span>
                <textarea name="note" rows={2} maxLength={4000} placeholder="What happened (optional)" className="block w-full rounded-ctl border border-line-accent bg-surface px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
              </label>
              <button type="submit" className={btn.ghost} disabled={busy}>Send rating</button>
            </>
          )}
          {error !== null && <ErrorState error={error} />}
        </form>
      )}
    </section>
  );
}
