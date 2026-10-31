import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "../../lib/api";
import { OUTCOME } from "../../lib/data";
import { credits } from "../../lib/format";
import { Bars } from "../../ui/Bars";
import { ErrorState, Skeleton } from "../../ui/states";

type Stats = {
  attempts: number;
  answered_calls: number;
  answer_rate: number;
  contacts_reached: number;
  avg_talk_seconds: number;
  credits_spent: string;
  outcomes: Record<string, number>;
  by_day: { date: string; attempts: number; answered: number }[];
};

export function Analytics({ campaignId }: { campaignId: string }) {
  const stats = useQuery({ queryKey: ["campaigns", campaignId, "analytics"], queryFn: () => unwrap<Stats>(api.GET("/campaigns/{campaign_id}/analytics", { params: { path: { campaign_id: campaignId } } })) });
  if (stats.error) return <ErrorState error={stats.error} retry={() => void stats.refetch()} />;
  if (!stats.data) return <Skeleton className="h-48 rounded-card" />;
  const s = stats.data;
  if (s.attempts === 0) return <p className="rounded-card border border-dashed border-line p-8 text-center text-sm text-ink-muted">No calls yet. Results appear here once the campaign starts dialling.</p>;
  return (
    <div className="space-y-6">
      <dl className="grid gap-px overflow-hidden rounded-card border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
        {[["Calls placed", String(s.attempts)], ["Answered", `${Math.round(s.answer_rate * 100)}%`], ["People reached", String(s.contacts_reached)], ["Credits spent", credits(s.credits_spent)]].map(([k, v]) => (
          <div key={k} className="bg-surface p-5"><dt className="text-sm text-ink-muted">{k}</dt><dd className="display num mt-2 text-3xl">{v}</dd></div>
        ))}
      </dl>
      <div className="grid gap-6 lg:grid-cols-[1.6fr_1fr]">
        <div className="rounded-card border border-line bg-surface p-6">
          <p className="eyebrow">By day</p>
          <div className="mt-4">
            <Bars data={s.by_day.map((d) => ({ label: d.date.slice(5), total: d.attempts, part: d.answered }))} caption="Calls placed and answered by day" totalName="Placed" partName="Answered" />
          </div>
        </div>
        <div className="rounded-card border border-line bg-surface p-6">
          <p className="eyebrow">Outcomes</p>
          <dl className="mt-3 divide-y divide-line">
            {Object.entries(s.outcomes).map(([k, n]) => (
              <div key={k} className="flex justify-between py-2 text-sm"><dt className="text-ink-muted">{OUTCOME[k] ?? k}</dt><dd className="num text-ink">{n}</dd></div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
