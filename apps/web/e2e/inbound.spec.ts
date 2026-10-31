import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { sql } from "./stack";

test("inbound: hours, greetings, notice, transfer; inbox messages and missed callers", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f9-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const me = await (await request.get("/api/accounts/me", { headers: auth })).json();
  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "inbound", language: "te", name: "Meera" } })).json();
  const instant = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "en", name: "Priya" } })).json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  await page.goto(`/employees/${emp.id}/incoming`);
  await page.getByRole("radio", { name: "Opening hours" }).click();
  await page.getByRole("button", { name: "Add", exact: true }).click(); // Mon–Fri 09:00–18:00
  for (const d of ["Mon", "Tue", "Wed", "Thu"]) await page.getByText(d, { exact: true }).last().click(); // leave Fri
  await page.getByText("Sat", { exact: true }).last().click();
  await page.getByLabel("From", { exact: true }).fill("22:00");
  await page.getByLabel("To", { exact: true }).fill("02:00");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("22:00–24:00")).toBeVisible();
  await expect(page.getByText("00:00–02:00")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // A placeholder the API doesn't allow for new callers is refused in place.
  await page.getByLabel("Greeting for a new caller").fill("Hello {{name}}!");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("placeholders");
  await page.getByLabel("Greeting for a new caller").fill("Hello, thank you for calling {{business_name}}.");
  await page.getByLabel("Transfer to").fill("+91 98765 43210");
  await page.getByLabel("When", { exact: true }).fill("The caller asks for a person");
  await page.getByLabel("Recording notice").fill("");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Saved. The next call follows these settings.")).toBeVisible();
  const saved = await (await request.get(`/api/employees/${emp.id}/inbound-settings`, { headers: auth })).json();
  expect(saved.hours).toHaveLength(3);
  expect(saved.transfer_number).toBe("+919876543210");
  // An empty notice means the standard words, never no notice: the field shows them as its placeholder.
  expect(saved.disclosure).toBe("");
  await expect(page.getByLabel("Recording notice")).toHaveAttribute("placeholder", /recorded/);

  // An Instant employee only chooses whether to answer its own leads.
  await page.goto(`/employees/${instant.id}/incoming`);
  await expect(page.getByRole("switch", { name: /Answer my leads/ })).toBeVisible();
  await expect(page.getByText("When it answers")).toHaveCount(0);

  // Inbox: a message is ticked done and reopened; a missed caller shows the plain reason.
  const call = sql(`INSERT INTO calls (account_id, employee_id, direction, channel, status, caller_phone, ended_at) VALUES ('${me.account.id}', '${emp.id}', 'inbound', 'inbound', 'completed', '+919876500061', now()) RETURNING id`);
  sql(`INSERT INTO inbound_messages (account_id, employee_id, call_id, phone, name, body, callback_at) VALUES ('${me.account.id}', '${emp.id}', '${call}', '+919876500061', 'రవి', 'Please call me about the 3 BHK price.', now() + interval '1 day') RETURNING id`);
  sql(`INSERT INTO calls (account_id, employee_id, direction, channel, status, caller_phone, miss_reason) VALUES ('${me.account.id}', '${emp.id}', 'inbound', 'inbound', 'no_answer', '+919876500062', 'Closed: it was outside your opening hours.') RETURNING id`);
  await page.goto("/inbox");
  await expect(page.getByText("Please call me about the 3 BHK price.")).toBeVisible();
  await expect(page.getByText("Closed: it was outside your opening hours.")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("checkbox", { name: /Mark message from రవి done/ }).click();
  await expect(page.getByText("Nothing to do.")).toBeVisible();
  await page.getByRole("radio", { name: "Done" }).click();
  await page.getByRole("checkbox", { name: /Reopen message from రవి/ }).click();
  await page.getByRole("radio", { name: "To do" }).click();
  await expect(page.getByText("Please call me about the 3 BHK price.")).toBeVisible();

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
