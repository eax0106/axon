import { useRef, useState } from "react";
import { useNavigate } from "react-router";

import type { components } from "@axon/contracts";

import { api, unwrap } from "../../lib/api";
import { CHANNELS, type Channel, type Employee, LANGUAGES, type Language } from "../../lib/employees";
import { useAction } from "../../lib/useAction";
import { btn } from "../../ui/buttons";
import { Select } from "../../ui/Field";
import { ErrorState } from "../../ui/states";
import { BriefInput } from "./BriefInput";

type Draft = components["schemas"]["Draft"];
type Setup = { channel: Channel; language: Language; second: Language | "" };
type Step = { at: "setup" } | { at: "brief" } | { at: "questions"; questions: string[] } | { at: "draft"; draft: Draft };

/** English is always on; one more language may be added (parity with the builder rules). */
function languagesOf(s: Setup) {
  const extra = [...new Set([s.language === "en" ? "" : "en", s.second].filter((l) => l && l !== s.language))];
  return { language: s.language, extra_languages: extra };
}

export default function Hire() {
  const navigate = useNavigate();
  const [setup, setSetup] = useState<Setup>({ channel: "instant", language: "te", second: "" });
  const [step, setStep] = useState<Step>({ at: "setup" });
  const [brief, setBrief] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const { busy, error, setError, run } = useAction();
  // Kept across retries: if filling the script fails, trying again must not hire a second employee.
  const created = useRef<Employee | null>(null);

  const ask = () =>
    run(async () => {
      const { questions } = await unwrap(
        api.POST("/ai/brief-questions", { body: { brief, channel: setup.channel, language: setup.language } }),
      );
      setStep({ at: "questions", questions });
    });

  const draft = () =>
    run(async () => {
      const given = Object.entries(answers)
        .filter(([, a]) => a.trim())
        .map(([question, answer]) => ({ question, answer }));
      const made = await unwrap(
        api.POST("/ai/draft-agent", { body: { brief, channel: setup.channel, language: setup.language, answers: given } }),
      );
      setStep({ at: "draft", draft: made });
    });

  /** Create the employee; with a draft, its script and capture fields go in alongside. */
  const hire = (from?: Draft) =>
    run(async () => {
      let employee = created.current;
      if (!employee) {
        employee = await unwrap(
          api.POST("/employees", {
            body: {
              channel: setup.channel,
              ...languagesOf(setup),
              name: from?.name ?? "New employee",
              role_title: from?.role_title ?? null,
            },
          }),
        );
        created.current = employee;
      }
      const p = { params: { path: { employee_id: employee.id } } };
      if (from)
        await Promise.all([
          unwrap(api.PUT("/employees/{employee_id}/script", { ...p, body: from.script })),
          unwrap(api.PUT("/employees/{employee_id}/settings", { ...p, body: { ...employee.settings, capture: from.capture } })),
        ]);
      navigate(`/employees/${employee.id}`, { replace: true });
    });

  return (
    <div className="mx-auto max-w-3xl">
      <p className="eyebrow">Hire · step {["setup", "brief", "questions", "draft"].indexOf(step.at) + 1} of 4</p>

      {step.at === "setup" && (
        <section className="page-in">
          <h1 className="display mt-3 text-4xl">What will they do?</h1>
          <fieldset className="mt-8">
            <legend className="text-sm text-ink">Channel</legend>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              {(Object.keys(CHANNELS) as Channel[]).map((c) => (
                <label
                  key={c}
                  className="cursor-pointer rounded-card border border-line bg-surface p-4 transition-colors duration-150 hover:border-line-accent has-[:checked]:border-accent has-[:checked]:bg-accent-soft"
                >
                  <input
                    type="radio"
                    name="channel"
                    value={c}
                    checked={setup.channel === c}
                    onChange={() => setSetup({ ...setup, channel: c })}
                    className="sr-only"
                  />
                  <span className="font-medium text-ink-strong">{CHANNELS[c].label}</span>
                  <span className="mt-1 block text-sm text-ink-muted">{CHANNELS[c].blurb}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div className="mt-8 grid gap-4 sm:grid-cols-2">
            <Select
              label="Opening language"
              value={setup.language}
              onChange={(v) => setSetup({ ...setup, language: v as Language, second: "" })}
              options={Object.entries(LANGUAGES)}
            />
            <Select
              label="Also speaks"
              value={setup.second}
              onChange={(v) => setSetup({ ...setup, second: v as Language | "" })}
              options={[
                ["", setup.language === "en" ? "English only" : "English"],
                ...Object.entries(LANGUAGES).filter(([l]) => l !== setup.language && l !== "en"),
              ]}
              hint={setup.language === "en" ? undefined : "English is always on; you can add one more."}
            />
          </div>
          <div className="mt-10 flex justify-end">
            <button type="button" className={btn.primary} onClick={() => setStep({ at: "brief" })}>
              Next: describe the job
            </button>
          </div>
        </section>
      )}

      {step.at === "brief" && (
        <section className="page-in">
          <h1 className="display mt-3 text-4xl">Describe the job.</h1>
          <p className="mt-2 text-ink-muted">
            Your business, who they call, what a good call ends with. Type it or say it, in {LANGUAGES[setup.language]} or
            English.
          </p>
          <BriefInput value={brief} onChange={setBrief} language={setup.language} onError={setError} />
          <Footer
            back={() => setStep({ at: "setup" })}
            next={{ label: busy ? "Reading your brief…" : "Next", run: ask, disabled: busy || brief.trim().length < 20 }}
            skip={() => void hire()}
          />
        </section>
      )}

      {step.at === "questions" && (
        <section className="page-in">
          <h1 className="display mt-3 text-4xl">A few questions.</h1>
          <p className="mt-2 text-ink-muted">Answer what you can; skip the rest.</p>
          <ol className="mt-8 space-y-5">
            {step.questions.map((q, i) => (
              <li key={q}>
                <label className="block">
                  <span className="flex gap-3 text-ink">
                    <span className="num text-accent">{String(i + 1).padStart(2, "0")}</span>
                    {q}
                  </span>
                  <textarea
                    rows={2}
                    maxLength={2000}
                    value={answers[q] ?? ""}
                    onChange={(e) => setAnswers({ ...answers, [q]: e.target.value })}
                    className="mt-2 w-full rounded-ctl border border-line-accent bg-surface px-3.5 py-2.5 text-ink-strong outline-none focus:border-accent"
                  />
                </label>
              </li>
            ))}
          </ol>
          <Footer
            back={() => setStep({ at: "brief" })}
            next={{ label: busy ? "Drafting your employee…" : "Draft my employee", run: draft, disabled: busy }}
          />
        </section>
      )}

      {step.at === "draft" && <Materialise draft={step.draft} busy={busy} hire={() => void hire(step.draft)} redo={() => setStep({ at: "brief" })} />}

      {error !== null && (
        <div className="mt-6 space-y-3">
          <ErrorState error={error} />
          {step.at !== "draft" && (
            <button type="button" className={btn.ghost} onClick={() => void hire()} disabled={busy}>
              Skip the AI and write the script myself
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Footer(props: {
  back: () => void;
  next: { label: string; run: () => void; disabled: boolean };
  skip?: () => void;
}) {
  return (
    <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
      <button type="button" className={btn.quiet} onClick={props.back}>
        Back
      </button>
      <div className="flex flex-wrap gap-2">
        {props.skip && (
          <button type="button" className={btn.ghost} onClick={props.skip}>
            Write it myself
          </button>
        )}
        <button type="button" className={btn.primary} onClick={props.next.run} disabled={props.next.disabled}>
          {props.next.label}
        </button>
      </div>
    </div>
  );
}

/** The draft builds itself: each part reveals in turn, numbered like the site's capability cards. */
function Materialise({ draft, busy, hire, redo }: { draft: Draft; busy: boolean; hire: () => void; redo: () => void }) {
  const parts = [
    { title: "Welcome line", body: draft.script.welcome_message ?? "" },
    ...(draft.script.sections ?? []).map((s) => ({ title: s.title, body: s.body })),
    { title: "When the call ends", body: draft.script.end_rules ?? "" },
  ].filter((p) => p.body.trim());
  return (
    <section className="page-in">
      <h1 className="display mt-3 text-4xl">
        Meet <span className="text-accent">{draft.name}</span>.
      </h1>
      {draft.role_title && <p className="mt-2 text-ink-muted">{draft.role_title}</p>}
      <ol className="mt-8 grid gap-3 sm:grid-cols-2">
        {parts.map((p, i) => (
          <li
            key={i}
            className="reveal rounded-card border border-line bg-surface p-5"
            style={{ animationDelay: `${i * 90}ms` }}
          >
            <p className="num text-xs text-accent">{String(i + 1).padStart(2, "0")}</p>
            <p className={`mt-2 font-medium ${i === parts.length - 1 ? "text-accent" : "text-ink-strong"}`}>{p.title}</p>
            <p className="mt-1.5 line-clamp-4 text-sm whitespace-pre-line text-ink-muted">{p.body}</p>
          </li>
        ))}
      </ol>
      {draft.capture.length > 0 && (
        <p className="mt-6 text-sm text-ink-muted">
          Captures on every call: <span className="text-ink">{draft.capture.map((c) => c.name).join(", ")}</span>
        </p>
      )}
      <div className="mt-10 flex flex-wrap items-center justify-between gap-3">
        <button type="button" className={btn.quiet} onClick={redo}>
          Change the brief
        </button>
        <button type="button" className={btn.primary} onClick={hire} disabled={busy}>
          {busy ? "Hiring…" : `Hire ${draft.name} and review the script`}
        </button>
      </div>
    </section>
  );
}
