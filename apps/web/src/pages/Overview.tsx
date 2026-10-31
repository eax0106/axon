import { useMe } from "../lib/queries";
import { Skeleton } from "../ui/states";
import { Dashboard } from "./Dashboard";
import { FirstRun } from "./FirstRun";

function greeting(hour = new Date().getHours()) {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function Overview() {
  const me = useMe();
  return (
    <>
      <p className="eyebrow">Overview</p>
      <h1 className="display mt-3 text-4xl md:text-[44px]">
        {me.data ? (
          <>
            {greeting()}, <span className="text-accent">{me.data.account.name}.</span>
          </>
        ) : (
          <Skeleton className="h-11 w-80 max-w-full" />
        )}
      </h1>
      <FirstRun />
      <Dashboard />
    </>
  );
}
