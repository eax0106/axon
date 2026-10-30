import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack: Compose (`docker compose ... up`) or `pnpm dev` with the API up.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  reporter: "list",
  use: { baseURL: process.env.AXON_WEB_URL ?? `http://localhost:${process.env.AXON_WEB_PORT ?? "8080"}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
