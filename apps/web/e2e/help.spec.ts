import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";

test("help: search finds a guide, and guides show the reader's real lead URL", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f13-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Nallagandla Realty" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  // With no Instant employee, a guide says so instead of showing a made-up address.
  await page.goto("/help");
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByLabel("Search help").fill("zapier");
  await expect(page.getByRole("link", { name: /Credits and what a call costs/ })).toHaveCount(0);
  await page.getByRole("link", { name: /^Zapier/ }).click();
  await expect(page.getByRole("heading", { name: "Zapier", level: 1 })).toBeVisible();
  await expect(page.getByText("You have no Instant employee yet")).toBeVisible();

  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "en", name: "Priya" } })).json();
  const info = await (await request.get(`/api/employees/${emp.id}/instant`, { headers: auth })).json();
  await page.reload();
  await expect(page.getByText(`/api${info.intake_path}`)).toBeVisible();
  await expect(page.getByText(info.secret_header, { exact: true })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.getByRole("link", { name: "Make" }).click();
  await expect(page.getByRole("heading", { name: "Make", level: 1 })).toBeVisible();
  await page.goto("/help/webhooks");
  await expect(page.getByText("X-Axon-Signature", { exact: false }).first()).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await seriousA11yIssues(page)).toEqual([]);
});
