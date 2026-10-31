import { CHANNELS, type Employee } from "../../lib/employees";

export function Avatar({ employee, size = "md" }: { employee: Employee; size?: "md" | "lg" }) {
  const initials = String((employee.avatar as { initials?: string }).initials ?? "?");
  return (
    <span
      aria-hidden
      className={`display grid shrink-0 place-items-center rounded-full border border-line-accent bg-accent-soft text-accent ${
        size === "lg" ? "size-14 text-xl" : "size-10 text-sm"
      }`}
    >
      {initials}
    </span>
  );
}

const STATUS: Record<Employee["status"], { label: string; dot: string }> = {
  live: { label: "Live", dot: "live-dot bg-accent" },
  paused: { label: "Paused", dot: "bg-warn" },
  training: { label: "Training", dot: "bg-info" },
  draft: { label: "Draft", dot: "bg-ink-muted" },
};

export function StatusTag({ status }: { status: Employee["status"] }) {
  return (
    <span className="eyebrow inline-flex items-center gap-1.5 text-ink-muted">
      <span aria-hidden className={`size-1.5 rounded-full ${STATUS[status].dot}`} />
      {STATUS[status].label}
    </span>
  );
}

export const channelLabel = (e: Employee) => CHANNELS[e.channel].label;
