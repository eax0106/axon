import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { sql } from "./stack";

test("instant: sources, test lead, calling rules, public intake, queue and log", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f7-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const me = await (await request.get("/api/accounts/me", { headers: auth })).json();
  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "en", name: "Priya" } })).json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  await page.goto(`/employees/${emp.id}/instant`);
  await expect(page.getByRole("heading", { name: "Calling rules" })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // A test lead runs the intake rules without a call.
  await page.getByLabel("Phone").fill("+919876500021");
  await page.getByLabel("Name", { exact: true }).fill("Ravi");
  await page.getByRole("button", { name: "Send a test lead (no call)" }).click();
  await expect(page.getByRole("status").filter({ hasText: "accepted" })).toBeVisible();
  const log = page.getByRole("region", { name: "Leads received" }).or(page.locator("section", { has: page.getByRole("heading", { name: "Leads received" }) }));
  await expect(log.getByText("+919876500021")).toBeVisible();

  // The secret reveals, then rotates to a different value.
  await page.getByRole("button", { name: "Reveal" }).click();
  const secret = page.getByLabel("Secret");
  await expect(secret).not.toHaveText(/•/);
  const first = (await secret.textContent()) ?? "";
  await page.getByRole("button", { name: "Rotate" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Rotate" }).click();
  await expect(secret).not.toHaveText(first);
  const current = (await secret.textContent()) ?? "";

  // A lead posted to the public URL with that secret is logged with the API's reason.
  const info = await (await request.get(`/api/employees/${emp.id}/instant`, { headers: auth })).json();
  const posted = await request.post(`/api${info.intake_path}`, {
    headers: { [info.secret_header]: current },
    data: { phone: "+919876500022", name: "Sita" },
  });
  // The secret was accepted (not 401); the lead itself is refused because the employee is not live.
  expect(posted.status()).not.toBe(401);
  expect((await posted.json()).reason).toBe("employee is not live");
  await expect(log.getByText("employee is not live")).toBeVisible({ timeout: 15_000 });

  // Calling rules: an end before the start is the API's to refuse; a valid window and ladder save.
  await page.getByLabel("Calls from").fill("20:00");
  await page.getByLabel("Until").fill("10:00");
  await page.getByRole("button", { name: "Save calling rules" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.getByLabel("Calls from").fill("10:00");
  await page.getByLabel("Until").fill("20:00");
  await page.getByRole("button", { name: "Remove attempt 5" }).click();
  await page.getByRole("button", { name: "Save calling rules" }).click();
  await expect(page.getByText("Saved. New leads follow these rules.")).toBeVisible();
  const saved = await (await request.get(`/api/employees/${emp.id}/instant/dialer`, { headers: auth })).json();
  expect([saved.window_start_min, saved.window_end_min, saved.retry_ladder_min.length]).toEqual([600, 1200, 3]);

  // A call the dialer has queued waits with its countdown; cancelling moves it to Done.
  const lead = sql(`INSERT INTO leads (account_id, phone, name) VALUES ('${me.account.id}', '+919876500023', 'Kavya') RETURNING id`);
  sql(
    `INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status, scheduled_for) VALUES ('${me.account.id}', '${emp.id}', '${lead}', 'outbound', 'instant', 'queued', now() + interval '20 minutes') RETURNING id`,
  );
  const waiting = page.getByRole("region", { name: "Waiting" });
  await expect(waiting.getByText("+919876500023")).toBeVisible({ timeout: 10_000 });
  await expect(waiting.getByText(/\d+m/)).toBeVisible();
  await waiting.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("region", { name: "Done" }).getByText("+919876500023")).toBeVisible({ timeout: 10_000 });
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
