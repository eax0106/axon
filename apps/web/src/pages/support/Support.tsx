import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, unwrap } from "../../lib/api";
import { ago } from "../../lib/format";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { ErrorState, Skeleton } from "../../ui/states";

/** A chat with the Axon team, and a box for product feedback. */
export default function Support() {
  const qc = useQueryClient();
  const chat = useQuery({ queryKey: ["support"], queryFn: () => unwrap(api.GET("/support/chat")), refetchInterval: 30_000 });
  const end = useRef<HTMLLIElement>(null);
  const count = chat.data?.length ?? 0;
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [count]);
  const send = useAction();
  const feedback = useAction();
  const [thanks, setThanks] = useState(false);

  function post(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const body = String(new FormData(form).get("body")).trim();
    if (!body) return;
    void send.run(async () => {
      await unwrap(api.POST("/support/chat", { body: { body } }));
      form.reset();
      await qc.invalidateQueries({ queryKey: ["support"] });
    });
  }
  function give(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const body = String(new FormData(form).get("feedback")).trim();
    if (!body) return;
    setThanks(false);
    void feedback.run(async () => {
      await unwrap(api.POST("/support/feedback", { body: { body } }));
      form.reset();
      setThanks(true);
    });
  }
  return (
    <>
      <p className="eyebrow">Support</p>
      <h1 className="display mt-3 text-4xl">Talk to the Axon team</h1>
      <p className="mt-2 max-w-xl text-ink-muted">Real people read this, usually within a working day. For a call that went wrong, rate it on the call's page and say what happened.</p>
      <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <section aria-labelledby="chat" className="flex flex-col rounded-card border border-line bg-surface">
          <h2 id="chat" className="eyebrow border-b border-line px-5 py-3">Chat</h2>
          {chat.error ? <div className="p-5"><ErrorState error={chat.error} retry={() => void chat.refetch()} /></div> : !chat.data ? <Skeleton className="m-5 h-40" /> : (
            <ol tabIndex={0} aria-label="Messages" className="max-h-[50vh] min-h-48 space-y-3 overflow-y-auto p-5">
              {chat.data.map((m) => (
                <li key={m.id} className={`max-w-[85%] rounded-card px-4 py-2.5 text-sm ${m.from_staff ? "bg-accent-soft text-ink" : "ml-auto border border-line text-ink-strong"}`}>
                  <p className="whitespace-pre-wrap">{m.body}</p>
                  <p className="mt-1 text-xs text-ink-muted">{m.from_staff ? "Axon team" : "You"} · {ago(m.created_at)}</p>
                </li>
              ))}
              {chat.data.length === 0 && <li className="py-10 text-center text-sm text-ink-muted">No messages yet. Ask anything.</li>}
              <li ref={end} aria-hidden />
            </ol>
          )}
          <form onSubmit={post} className="flex gap-2 border-t border-line p-3">
            <label className="sr-only" htmlFor="support-body">Message</label>
            <textarea id="support-body" name="body" rows={2} maxLength={4000} required placeholder="Write to the team"
              onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) e.currentTarget.form?.requestSubmit(); }}
              className="min-w-0 flex-1 resize-none rounded-ctl border border-line-accent bg-bg px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
            <button type="submit" className={`${btn.primary} self-end`} disabled={send.busy}>Send</button>
          </form>
          {send.error !== null && <div className="px-3 pb-3"><ErrorState error={send.error} /></div>}
        </section>
        <section aria-labelledby="feedback" className="rounded-card border border-line bg-surface p-5">
          <h2 id="feedback" className="eyebrow">Product feedback</h2>
          <form onSubmit={give} className="mt-3 space-y-3">
            <label className="block">
              <span className="text-sm text-ink">What should Axon do better?</span>
              <textarea name="feedback" rows={5} maxLength={4000} required className="mt-1.5 block w-full rounded-ctl border border-line-accent bg-bg px-3 py-2 text-sm text-ink-strong outline-none focus:border-accent" />
            </label>
            <button type="submit" className={btn.ghost} disabled={feedback.busy}>Send feedback</button>
            {thanks && <p role="status" className="text-sm text-accent">Thanks, the team reads every note.</p>}
            {feedback.error !== null && <ErrorState error={feedback.error} />}
          </form>
        </section>
      </div>
    </>
  );
}
