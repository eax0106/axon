import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useSyncExternalStore } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";

import { session } from "./lib/api";
import { queryClient } from "./lib/queries";
import { Shell } from "./shell/Shell";

const SignIn = lazy(() => import("./pages/SignIn"));
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
            <Route element={<Gate />}>
              <Route index element={<Overview />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
