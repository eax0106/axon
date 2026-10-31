import type { ReactNode } from "react";

import { ApiError } from "../lib/api";

// Vendor names as the API reports them (app/providers/registry.py) -> what an owner calls them.
const VENDOR: Record<string, string> = {
  vobiz: "Vobiz",
  sarvam: "Sarvam",
  smallest: "Smallest",
  cartesia: "Cartesia",
  gemini: "Gemini",
  razorpay: "Razorpay",
  r2: "object storage",
  google: "Google",
  meta_lead_ads: "Meta Lead Ads",
  resend: "Resend (email)",
  interakt: "Interakt",
  aisensy: "AiSensy",
};

export function Skeleton({ className = "" }: { className?: string }) {
  return <span aria-hidden className={`skeleton block h-4 ${className}`} />;
}

/** A failed request, as one calm panel. A missing vendor key gets its own "connect" message. */
export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const provider = error instanceof ApiError ? error.provider : null;
  if (provider) {
    const name = VENDOR[provider.provider] ?? provider.provider;
    return (
      <Panel role="status" tone="info" title={`Connect ${name} to use this`}>
        This needs a {provider.kind.replaceAll("_", " ")} provider that isn't set up yet. Add{" "}
        {provider.missing_keys.map((k, i) => (
          <span key={k}>
            {i > 0 && ", "}
            <code className="num text-ink">{k}</code>
          </span>
        ))}{" "}
        to the server settings and it starts working, nothing else to change.
      </Panel>
    );
  }
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <Panel role="alert" tone="danger" title="That didn't load">
      {message}
      {retry && (
        <button
          type="button"
          onClick={retry}
          className="ml-3 text-accent underline underline-offset-4"
        >
          Try again
        </button>
      )}
    </Panel>
  );
}

function Panel(props: {
  role: "status" | "alert";
  tone: "info" | "danger";
  title: string;
  children: ReactNode;
}) {
  const dot = props.tone === "info" ? "bg-info" : "bg-danger";
  return (
    <div role={props.role} className="rounded-card border border-line bg-surface p-5">
      <p className="flex items-center gap-2 font-medium text-ink-strong">
        <span aria-hidden className={`size-1.5 rounded-full ${dot}`} />
        {props.title}
      </p>
      <p className="mt-1.5 text-sm text-ink-muted">{props.children}</p>
    </div>
  );
}
