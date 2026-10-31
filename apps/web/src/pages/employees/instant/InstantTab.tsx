import { useInstant } from "../../../lib/instant";
import { ErrorState, Skeleton } from "../../../ui/states";
import { useDetail } from "../Detail";
import { DialerForm } from "./Dialer";
import { IntakeLog } from "./IntakeLog";
import { Queue } from "./Queue";
import { Sources } from "./Sources";

/** Everything about how an Instant employee hears about new leads and calls them. */
export default function InstantTab() {
  const { employee } = useDetail();
  const info = useInstant(employee.id);
  if (employee.channel !== "instant") return <p className="text-ink-muted">This employee isn't on Instant.</p>;
  if (info.error) return <ErrorState error={info.error} retry={() => void info.refetch()} />;
  if (!info.data) return <Skeleton className="h-96 rounded-card" />;
  return (
    <div className="space-y-10">
      <Queue employeeId={employee.id} />
      <Sources employeeId={employee.id} info={info.data} />
      {/* Seeded once: a refetch after saving must not reset the form or its "Saved" note. */}
      <DialerForm key={employee.id} employeeId={employee.id} settings={info.data.dialer} />
      <IntakeLog employeeId={employee.id} />
    </div>
  );
}
