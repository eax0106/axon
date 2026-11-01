import type { Language } from "../../../lib/employees";
import { useTraining } from "../../../lib/training";
import { ErrorState, Skeleton } from "../../../ui/states";
import { useDetail } from "../Detail";
import { Teach } from "./Teach";
import { Documents, Items, Suggestions } from "./Knowledge";

/** What the employee has been taught. Unlike the script, it applies to the next call at once. */
export default function TrainingTab() {
  const { employee } = useDetail();
  const training = useTraining(employee.id);
  if (training.error) return <ErrorState error={training.error} retry={() => void training.refetch()} />;
  if (!training.data) return <Skeleton className="h-96 rounded-card" />;
  return (
    <div className="space-y-6">
      <Suggestions employeeId={employee.id} />
      <Teach employeeId={employee.id} language={employee.language as Language} />
      <Items employeeId={employee.id} training={training.data} />
      <Documents employeeId={employee.id} training={training.data} />
    </div>
  );
}
