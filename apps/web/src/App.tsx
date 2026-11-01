import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useSyncExternalStore } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";

import { session } from "./lib/api";
import { queryClient, useMe } from "./lib/queries";
import { Shell } from "./shell/Shell";

const SignIn = lazy(() => import("./pages/SignIn"));
const SignUp = lazy(() => import("./pages/SignUp"));
const Account = lazy(() => import("./pages/Account"));
const Employees = lazy(() => import("./pages/employees/List"));
const Hire = lazy(() => import("./pages/employees/Hire"));
const Employee = lazy(() => import("./pages/employees/Detail"));
const ScriptTab = lazy(() => import("./pages/employees/ScriptTab"));
const VoiceTab = lazy(() => import("./pages/employees/VoiceTab"));
const BehaviourTab = lazy(() => import("./pages/employees/BehaviourTab"));
const VersionsTab = lazy(() => import("./pages/employees/VersionsTab"));
const TryTab = lazy(() => import("./pages/employees/TryTab"));
const InstantTab = lazy(() => import("./pages/employees/instant/InstantTab"));
const IncomingTab = lazy(() => import("./pages/employees/IncomingTab"));
const TrainingTab = lazy(() => import("./pages/employees/training/TrainingTab"));
const ActionsTab = lazy(() => import("./pages/employees/actions/ActionsTab"));
const LivePage = lazy(() => import("./pages/calls/LivePage"));
const Billing = lazy(() => import("./pages/billing/Billing"));
const Inbox = lazy(() => import("./pages/inbox/Inbox"));
const Campaigns = lazy(() => import("./pages/campaigns/List"));
const Campaign = lazy(() => import("./pages/campaigns/Detail"));
const Conversations = lazy(() => import("./pages/calls/Conversations"));
const CallDetail = lazy(() => import("./pages/calls/CallDetail"));
const Leads = lazy(() => import("./pages/leads/Leads"));
const LeadDetail = lazy(() => import("./pages/leads/LeadDetail"));
const Numbers = lazy(() => import("./pages/numbers/Numbers"));
const Overview = lazy(() => import("./pages/Overview"));
const Developers = lazy(() => import("./pages/developers/Developers"));
const Support = lazy(() => import("./pages/support/Support"));
const Admin = lazy(() => import("./pages/admin/Admin"));

function Gate() {
  const token = useSyncExternalStore(session.subscribe, () => session.token());
  const signedIn = token !== null;
  const location = useLocation();

  // A different session (signed out, or a support session starting or ending) sees none of the last one's data.
  useEffect(() => () => queryClient.clear(), [token]);

  if (!signedIn) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  return <Shell />;
}

/** Only platform staff ever load the admin chunk; everyone else is sent home. */
function StaffOnly() {
  const me = useMe();
  if (!me.data) return null;
  return me.data.user.staff && !me.data.user.support_session ? <Admin /> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={null}>
          <Routes>
            <Route path="/sign-in" element={<SignIn />} />
            <Route path="/sign-up" element={<SignUp />} />
            <Route element={<Gate />}>
              <Route index element={<Overview />} />
              <Route path="account" element={<Account />} />
              <Route path="employees" element={<Employees />} />
              <Route path="employees/new" element={<Hire />} />
              <Route path="calls" element={<Conversations />} />
              <Route path="calls/:id" element={<CallDetail />} />
              <Route path="calls/:id/live" element={<LivePage />} />
              <Route path="leads" element={<Leads />} />
              <Route path="leads/:id" element={<LeadDetail />} />
              <Route path="billing" element={<Billing />} />
              <Route path="inbox" element={<Inbox />} />
              <Route path="campaigns" element={<Campaigns />} />
              <Route path="campaigns/:id" element={<Campaign />} />
              <Route path="numbers" element={<Numbers />} />
              <Route path="developers" element={<Developers />} />
              <Route path="support" element={<Support />} />
              <Route path="admin/*" element={<StaffOnly />} />
              <Route path="employees/:id" element={<Employee />}>
                <Route index element={<Navigate to="script" replace />} />
                <Route path="script" element={<ScriptTab />} />
                <Route path="voice" element={<VoiceTab />} />
                <Route path="behaviour" element={<BehaviourTab />} />
                <Route path="versions" element={<VersionsTab />} />
                <Route path="try" element={<TryTab />} />
                <Route path="instant" element={<InstantTab />} />
                <Route path="incoming" element={<IncomingTab />} />
                <Route path="training" element={<TrainingTab />} />
                <Route path="actions" element={<ActionsTab />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
