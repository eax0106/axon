import "@fontsource-variable/inter";
import "@fontsource-variable/manrope";
import "@fontsource-variable/noto-sans-devanagari";
import "@fontsource-variable/noto-sans-telugu";
import "./styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
