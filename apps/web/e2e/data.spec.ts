import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { sql } from "./stack";

// Hindi with a zero-width joiner (क्‍ष) and Telugu with a non-joiner: they must reach the screen as stored.
const HINDI = "मुझे 3 BHK चाहिए, बजट 80 लाख, क्‍षेत्र कोकापेट";
const TELUGU = "సరే, శనివారం‌ site visit పెట్టుకుందాం";

test("dashboard, conversations, call detail, leads and search read the same real calls", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f6-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const me = await (await request.get("/api/accounts/me", { headers: auth })).json();
  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "te", name: "Priya" } })).json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  // Two finished calls with their leads, as the engine and the post-call job leave them.
  const account = me.account.id;
  const lead = sql(`INSERT INTO leads (account_id, phone, name, fields) VALUES ('${account}', '+919876500011', 'Ravi Kumar', '{"budget": "80 lakh"}') RETURNING id`);
  const other = sql(`INSERT INTO leads (account_id, phone, name) VALUES ('${account}', '+919876500012', 'Sita') RETURNING id`);
  const transcript = JSON.stringify([
    { role: "assistant", text: "నమస్తే రవి గారు!" },
    { role: "user", text: HINDI },
    { role: "assistant", text: TELUGU },
  ]).replaceAll("'", "''");
  const call = sql(
    `INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status, outcome, sentiment, summary, duration_s, transcript, captured, started_at, answered_at, ended_at, analysis_status)
     VALUES ('${account}', '${emp.id}', '${lead}', 'outbound', 'instant', 'completed', 'interested', 'positive', 'Wants a 3 BHK, budget 80 lakh; site visit Saturday.', 95, '${transcript}', '{"budget": "80 lakh"}', now() - interval '1 hour', now() - interval '1 hour', now() - interval '58 minutes', 'done') RETURNING id`,
  );
  sql(
    `INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status, outcome, summary, duration_s, started_at, answered_at, ended_at, analysis_status)
     VALUES ('${account}', '${emp.id}', '${other}', 'outbound', 'instant', 'completed', 'not_interested', 'Not looking right now.', 30, now() - interval '2 hours', now() - interval '2 hours', now() - interval '119 minutes', 'done') RETURNING id`,
  );

  // Dashboard totals are the API's.
  const stats = await (await request.get("/api/stats/overview?range=7d", { headers: auth })).json();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Performance" })).toBeVisible();
  const calls = page.locator("dl").filter({ hasText: "Connect rate" });
  await expect(calls.getByText(String(stats.totals.calls), { exact: true })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // A filter narrows the list and is remembered across a reload.
  await page.goto("/calls");
  await expect(page.getByText("2 calls")).toBeVisible();
  await page.getByLabel("Outcome").selectOption("interested");
  await expect(page.getByText("1 call", { exact: true })).toBeVisible();
  await page.waitForTimeout(900); // the filter is saved after a short pause
  await page.reload();
  await expect(page.getByLabel("Outcome")).toHaveValue("interested");
  await expect(page.getByText("1 call", { exact: true })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Call detail: summary, transcript with joiners intact, a note.
  await page.getByRole("link", { name: /Ravi Kumar/ }).click();
  await expect(page).toHaveURL(new RegExp(`/calls/${call}$`));
  await expect(page.getByText("Wants a 3 BHK, budget 80 lakh; site visit Saturday.")).toBeVisible();
  expect(await page.getByText(HINDI).textContent()).toContain(HINDI);
  expect(await page.getByText(TELUGU).textContent()).toContain(TELUGU);
  await page.getByLabel("Add a note").fill("Send the brochure before Saturday.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("Send the brochure before Saturday.")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.goto("/calls");
  await page.getByRole("button", { name: /Clear/ }).click();
  await expect(page.getByText("2 calls")).toBeVisible();

  // Leads: the same two in every view.
  await page.goto("/leads");
  await expect(page.getByRole("link", { name: "Ravi Kumar" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sita" })).toBeVisible();
  await page.getByRole("radio", { name: "cards" }).click();
  await expect(page.getByRole("link", { name: /Ravi Kumar/ })).toBeVisible();
  await page.getByRole("radio", { name: "By outcome" }).click();
  await expect(page.getByRole("region", { name: "Interested" }).getByText("Ravi Kumar")).toBeVisible();
  await expect(page.getByRole("region", { name: "Not interested" }).getByText("Sita")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Export with a captured field ticked.
  await page.getByRole("radio", { name: "table" }).click();
  await page.getByRole("button", { name: "Export CSV" }).click();
  await page.getByRole("checkbox", { name: "budget" }).check();
  const [file] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download" }).click()]);
  const csv = readFileSync((await file.path()) ?? "", "utf8");
  expect(csv.split("\n")[0]).toContain("field:budget");
  expect(csv).toContain("80 lakh");

  // The palette finds a lead by name.
  await page.keyboard.press("ControlOrMeta+k");
  await page.keyboard.type("Ravi");
  await expect(page.getByRole("option", { name: /Ravi Kumar\s*Lead/ })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(`/calls/${call}`);
  await expect(page.getByText(HINDI)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
