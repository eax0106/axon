import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In dev the API lives on its own port; the browser always talks to /api on the web origin
// (Compose does the same with nginx), so there is no CORS and the WebSocket shares the origin.
const api = process.env.AXON_API_URL ?? `http://localhost:${process.env.AXON_API_PORT ?? "8000"}`;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: { "/api": { target: api, ws: true, rewrite: (path) => path.replace(/^\/api/, "") } },
  },
  build: { manifest: true, target: "es2022" },
  test: { environment: "jsdom", include: ["src/**/*.test.{ts,tsx}"] },
});
