import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";

test("bulk: create, import with mapping, exclusions, consent, settings, constellation, export", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f8-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "bulk", language: "te", name: "Arjun" } })).json();
  await request.put(`/api/employees/${emp.id}/script`, { headers: auth, data: { welcome_message: "నమస్తే", pre_call_variables: ["project"] } });
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  await page.goto("/campaigns");
  await page.getByLabel("New campaign").fill("Kokapet launch");
  await page.getByRole("button", { name: "Create" }).click();
  await expect(page.getByRole("heading", { name: "Kokapet launch" })).toBeVisible();
  const id = page.url().split("/").at(-1) ?? "";
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Import: exact column names are the only ones pre-selected; the report is the API's own counts.
  await page.getByRole("tab", { name: "Contacts" }).click();
  await page.getByLabel("Or paste").fill(
    "phone,name,project\n+919876500051,రవి కుమార్,Kokapet\n+919876500052,Sita,Tellapur\n+919876500052,Sita again,Tellapur\nnot-a-phone,Bad,X",
  );
  await page.getByRole("button", { name: "Check the columns" }).click();
  await expect(page.getByLabel("Phone column")).toHaveValue("phone");
  await expect(page.getByLabel("Script detail: project")).toHaveValue("project");
  await page.getByRole("button", { name: /^Add \d+ contacts$/ }).click();
  const report = page.getByRole("status").filter({ hasText: "Added" });
  await expect(report).toContainText("Added2");
  await expect(report).toContainText("Repeated in the file1");
  await expect(report).toContainText("Invalid numbers1");
  await expect(page.getByRole("region", { name: "Contacts table" }).getByText("రవి కుమార్")).toBeVisible();

  await page.getByLabel("Phone", { exact: true }).fill("+919876500053");
  await page.getByRole("button", { name: "Add contact" }).click();
  await page.getByLabel("Numbers to exclude").fill("+919876500099");
  await page.getByRole("button", { name: "Exclude" }).click();
  await expect(page.getByText("+919876500099")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // One dot per contact.
  await page.getByRole("tab", { name: "Live" }).click();
  await expect(page.locator("figure svg[role=img] circle")).toHaveCount(3);

  // Settings save through the API.
  await page.getByRole("tab", { name: "Settings" }).click();
  await page.getByLabel("Calls at once").fill("5");
  await page.getByRole("button", { name: "Save settings" }).click();
  await expect(page.getByText("Saved.", { exact: true })).toBeVisible();
  expect((await (await request.get(`/api/campaigns/${id}`, { headers: auth })).json()).settings.concurrency).toBe(5);

  // Start: the API refuses without consent; the dialog shows the statement word for word and needs a tick.
  expect((await request.post(`/api/campaigns/${id}/start`, { headers: auth })).status()).toBe(409);
  const statement = (await (await request.get(`/api/campaigns/${id}`, { headers: auth })).json()).consent_statement;
  await page.getByRole("button", { name: "Start", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(statement, { exact: true })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Start calling" })).toBeDisabled();
  await dialog.getByRole("checkbox").check();
  await dialog.getByRole("button", { name: "Start calling" }).click();
  // Consent is recorded; this employee has no number yet, so the API's own reason shows.
  await expect(dialog.getByRole("alert")).toBeVisible();
  const consent = await (await request.get(`/api/campaigns/${id}/consent`, { headers: auth })).json();
  expect(consent[0].statement).toBe(statement);
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.keyboard.press("Escape");

  const [file] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Export CSV" }).click()]);
  expect(readFileSync((await file.path()) ?? "", "utf8")).toContain("+919876500051");

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
