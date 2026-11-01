import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, unwrap } from "../../lib/api";
import { btn } from "../../ui/buttons";
import { Keys } from "./Keys";
import { Deliveries, Requests } from "./Logs";
import { Webhooks } from "./Webhooks";

type Status = { api: { version: string; status: string }; requests_24h: number; server_errors_24h: number; webhooks_24h: { delivered: number; failed: number; pending: number } };
const TABS = ["Keys", "Webhooks", "Deliveries", "Requests"] as const;

export default function Developers() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Keys");
  const status = useQuery({ queryKey: ["dev", "status"], queryFn: () => unwrap<Status>(api.GET("/developer/status")) });
  const s = status.data;
  return (
    <>
      <p className="eyebrow">Developers</p>
      <h1 className="display mt-3 text-4xl">Connect your systems</h1>
      <p className="mt-2 max-w-2xl text-ink-muted">A read-only REST API (plus posting leads), signed webhooks for six events, and the logs of both.</p>
      <div className="mt-8 grid gap-4 sm:grid-cols-[1fr_auto]">
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-4">
          {[["API", s ? `${s.api.version} · ${s.api.status}` : "…"], ["Requests, 24 h", s ? String(s.requests_24h) : "…"], ["Server errors, 24 h", s ? String(s.server_errors_24h) : "…"], ["Webhooks, 24 h", s ? `${s.webhooks_24h.delivered} sent · ${s.webhooks_24h.failed} failed` : "…"]].map(([k, v]) => (
            <div key={k} className="bg-surface p-4"><dt className="text-xs text-ink-muted">{k}</dt><dd className="num mt-1 text-ink-strong">{v}</dd></div>
          ))}
        </dl>
        <div className="flex flex-wrap items-center gap-2">
          <a href="/api/v1/openapi.json" download="axon-openapi.json" className={btn.ghost}>OpenAPI</a>
          <a href="/api/v1/postman.json" download="axon-postman.json" className={btn.ghost}>Postman</a>
        </div>
      </div>
      <div role="tablist" aria-label="Developer tools" className="mt-8 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className="-mb-px border-b-2 border-transparent px-3.5 py-2.5 text-sm text-ink-muted transition-colors duration-150 hover:text-ink aria-selected:border-accent aria-selected:text-ink-strong">{t}</button>
        ))}
      </div>
      <div role="tabpanel" className="mt-8">
        {tab === "Keys" && <Keys />}
        {tab === "Webhooks" && <Webhooks />}
        {tab === "Deliveries" && <Deliveries />}
        {tab === "Requests" && <Requests />}
      </div>
    </>
  );
}
