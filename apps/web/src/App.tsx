import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useSyncExternalStore } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router";

import { SIGNED_OUT, session } from "./lib/api";
import { queryClient } from "./lib/queries";
import { Shell } from "./shell/Shell";

const SignIn = lazy(() => import("./pages/SignIn"));
const Overview = lazy(() => import("./pages/Overview"));

const subscribe = (onChange: () => void) => {
  window.addEventListener(SIGNED_OUT, onChange);
  window.addEventListener("storage", onChange); // signed out in another tab
  return () => {
    window.removeEventListener(SIGNED_OUT, onChange);
    window.removeEventListener("storage", onChange);
  };
};

function Gate() {
  const signedIn = useSyncExternalStore(subscribe, () => session.token() !== null);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (!signedIn) queryClient.clear();
  }, [signedIn]);

  if (!signedIn) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  const signOut = () => {
    session.set(null);
    window.dispatchEvent(new Event(SIGNED_OUT));
    navigate("/sign-in", { replace: true });
  };
  return <Shell onSignOut={signOut} />;
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
