import { useParams } from "react-router";

import { useLiveCall } from "../../lib/live";
import { LiveView } from "./LiveView";

/** /calls/:id/live: follow any call on the account as it happens. */
export default function LivePage() {
  const { id = "" } = useParams();
  const state = useLiveCall(id);
  return (
    <>
      <p className="eyebrow">Live call</p>
      <h1 className="display mt-3 mb-8 text-4xl">Listening in</h1>
      <LiveView state={state} who="Employee" />
    </>
  );
}
