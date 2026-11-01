import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, unwrap } from "../../../lib/api";
import type { Language } from "../../../lib/employees";
import { record } from "../../../lib/recorder";
import { MAX_ITEM, type NewItem, type Proposal, raw } from "../../../lib/training";
import { useAction } from "../../../lib/useAction";
import { btn } from "../../../ui/buttons";
import { ErrorState } from "../../../ui/states";
import { Waveform } from "../../../ui/Waveform";

type Recording = Awaited<ReturnType<typeof record>>;

/**
 * Teach by typing, speaking or a photo of a price list. The AI only proposes facts and rules;
 * nothing is saved until the owner has read the list, fixed it and pressed Save.
 */
export function Teach({ employeeId, language }: { employeeId: string; language: Language }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<(NewItem & { key: number })[] | null>(null);
  const [dropped, setDropped] = useState(0);
  const [rec, setRec] = useState<Recording | null>(null);
  const current = useRef<Recording | null>(null);
  const { busy, error, setError, run } = useAction();
  const p = { params: { path: { employee_id: employeeId } } };

  const show = (r: Proposal) => {
    setProposal(r.items.map((it, key) => ({ ...it, key })));
    setDropped(r.dropped);
  };
  const fromText = () => run(async () => show(await unwrap(api.POST("/employees/{employee_id}/training/propose", { ...p, body: { text } }))));
  const fromPhoto = (file: File) =>
    run(async () => show(await unwrap(api.POST("/employees/{employee_id}/training/propose-photo", { ...p, ...raw(file, file.type) }))));
  async function speak() {
    if (rec) {
      rec.stop();
      setRec(null);
      return;
    }
    let sent = false;
    try {
      // One WAV per teaching: sent when the owner stops, or after 25 s, when recording also stops.
      const r = await record((wav) => {
        if (sent) return;
        sent = true;
        current.current?.stop();
        setRec(null);
        void run(async () =>
            show(
              await unwrap(
                api.POST("/employees/{employee_id}/training/propose-voice", {
                  params: { path: { employee_id: employeeId }, query: { language } },
                  ...raw(wav, "audio/wav"),
                }),
              ),
          ),
        );
      });
      current.current = r;
      setRec(r);
    } catch (err) {
      setError(err instanceof DOMException ? new Error("Allow the microphone to teach by voice.") : err);
    }
  }
  const save = () =>
    run(async () => {
      if (!proposal) return;
      await unwrap(api.POST("/employees/{employee_id}/training/items", { ...p, body: { items: proposal.map(({ key: _k, ...it }) => it) } }));
      setProposal(null);
      setText("");
      await qc.invalidateQueries({ queryKey: ["training", employeeId] });
    });

  return (
    <section aria-labelledby="teach" className="rounded-card border border-line-accent bg-surface p-6">
      <h2 id="teach" className="eyebrow">Teach something new</h2>
      <p className="mt-2 text-sm text-ink-muted">A price, an offer, a rule for how to talk. It applies to the next call; nothing is saved before you check it.</p>
      {!proposal ? (
        <>
          <label className="sr-only" htmlFor="teach-text">What to teach</label>
          <textarea id="teach-text" rows={4} maxLength={6000} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="3 BHK in Tower B is now ₹1.35 crore. Never promise a discount; offer a site visit instead."
            className="mt-4 w-full resize-y rounded-ctl border border-line-accent bg-bg px-3.5 py-2.5 text-ink-strong outline-none focus:border-accent" />
          {rec && <Waveform analyser={rec.analyser} />}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={btn.primary} disabled={busy || text.trim().length < 3} onClick={() => void fromText()}>{busy ? "Reading…" : "Turn into facts and rules"}</button>
            <button type="button" className={rec ? btn.danger : btn.ghost} disabled={busy && !rec} onClick={() => void speak()}>{rec ? "Stop and read it" : "Say it"}</button>
            <label className={`${btn.ghost} cursor-pointer`}>
              From a photo
              <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void fromPhoto(f); }} />
            </label>
          </div>
        </>
      ) : (
        <div className="mt-4 space-y-3">
          <p className="text-sm text-ink">Check each one. Edit, switch between fact and rule, or remove it.{dropped > 0 && <span className="text-warn"> {dropped} part{dropped === 1 ? " was" : "s were"} too long or unclear and left out.</span>}</p>
          <ul className="space-y-2">
            {proposal.map((it, i) => (
              <li key={it.key} className="flex flex-wrap items-start gap-2 rounded-ctl border border-line bg-bg p-3">
                <select aria-label={`Item ${i + 1} kind`} value={it.kind} onChange={(e) => setProposal(proposal.map((x) => (x.key === it.key ? { ...x, kind: e.target.value as NewItem["kind"] } : x)))}
                  className="h-8 rounded-ctl border border-line bg-surface px-2 text-xs text-ink">
                  <option value="fact">Fact</option><option value="rule">Rule</option>
                </select>
                <textarea aria-label={`Item ${i + 1}`} rows={2} maxLength={MAX_ITEM} value={it.text} onChange={(e) => setProposal(proposal.map((x) => (x.key === it.key ? { ...x, text: e.target.value } : x)))}
                  className="min-w-0 flex-1 resize-y bg-transparent text-sm text-ink-strong outline-none" />
                <button type="button" aria-label={`Remove item ${i + 1}`} className="text-ink-muted hover:text-danger" onClick={() => setProposal(proposal.filter((x) => x.key !== it.key))}>×</button>
              </li>
            ))}
            {proposal.length === 0 && <li className="text-sm text-ink-muted">Nothing left to save.</li>}
          </ul>
          <div className="flex gap-2">
            <button type="button" className={btn.primary} disabled={busy || proposal.length === 0} onClick={() => void save()}>Save {proposal.length}</button>
            <button type="button" className={btn.quiet} onClick={() => setProposal(null)}>Discard</button>
          </div>
        </div>
      )}
      {error !== null && <div className="mt-3"><ErrorState error={error} /></div>}
    </section>
  );
}
