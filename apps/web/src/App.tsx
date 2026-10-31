import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useSyncExternalStore } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";

import { session } from "./lib/api";
import { queryClient } from "./lib/queries";
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
const LivePage = lazy(() => import("./pages/calls/LivePage"));
const Billing = lazy(() => import("./pages/billing/Billing"));
const Numbers = lazy(() => import("./pages/numbers/Numbers"));
const Overview = lazy(() => import("./pages/Overview"));

function Gate() {
  const signedIn = useSyncExternalStore(session.subscribe, () => session.token() !== null);
  const location = useLocation();

  useEffect(() => {
    if (!signedIn) queryClient.clear();
  }, [signedIn]);

  if (!signedIn) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  return <Shell />;
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
              <Route path="calls/:id/live" element={<LivePage />} />
              <Route path="billing" element={<Billing />} />
              <Route path="numbers" element={<Numbers />} />
              <Route path="employees/:id" element={<Employee />}>
                <Route index element={<Navigate to="script" replace />} />
                <Route path="script" element={<ScriptTab />} />
                <Route path="voice" element={<VoiceTab />} />
                <Route path="behaviour" element={<BehaviourTab />} />
                <Route path="versions" element={<VersionsTab />} />
                <Route path="try" element={<TryTab />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
