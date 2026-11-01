import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { sql } from "./stack";

const signup = async (request: import("@playwright/test").APIRequestContext, prefix: string, account: string) => {
  const email = `${prefix}-${Date.now()}@example.com`;
  const r = await request.post("/api/auth/signup", { data: { email, password: "correct horse battery", account_name: account } });
  return { email, token: (await r.json()).access_token as string };
};

test("a non-staff user never sees or loads the staff console", async ({ page, request }) => {
  const owner = await signup(request, "f12o", "Miyapur Dental");
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), owner.token);
  const chunks: string[] = [];
  page.on("request", (r) => chunks.push(r.url()));
  await page.goto("/admin/accounts");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "Staff console" })).toHaveCount(0);
  expect(chunks.filter((u) => /\/assets\/Admin-/.test(u))).toEqual([]);
});

test("staff: find an account, adjust credits, support session with banner, reply, rules, system", async ({ page, request }) => {
  const owner = await signup(request, "f12c", "Madhapur Motors");
  await request.post("/api/support/chat", { headers: { Authorization: `Bearer ${owner.token}` }, data: { body: `My calls are not starting (${owner.email}).` } });
  const staff = await signup(request, "f12s", "ALTERX");
  sql(`UPDATE users SET is_platform_admin = true WHERE email = '${staff.email}' RETURNING id`);
  await page.addInitScript((t) => localStorage.getItem("axon.token") ?? localStorage.setItem("axon.token", t), staff.token);

  await page.goto("/");
  await page.getByRole("link", { name: "Staff console" }).click();
  await page.getByLabel("Find an account").fill(owner.email);
  await page.getByRole("link", { name: new RegExp(owner.email) }).click();
  await expect(page.getByRole("heading", { name: "Madhapur Motors" })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.getByLabel("Credits (negative takes back)").fill("100");
  await page.getByLabel("Note").fill("Goodwill for dropped calls");
  await page.getByRole("button", { name: "Post" }).click();
  await expect(page.getByText("Added 100 credits. Balance now 150.")).toBeVisible();
  await expect(page.getByText("Goodwill for dropped calls")).toBeVisible();

  // A support session shows the banner on every page and hands back the staff session when it ends.
  await page.getByLabel("Reason").fill("Ticket 7: calls not starting");
  await page.getByRole("button", { name: "Start" }).click();
  const banner = page.getByRole("status").filter({ hasText: "Support session" });
  await expect(banner).toContainText(owner.email);
  await page.goto("/billing");
  await expect(banner).toBeVisible();
  await expect(page.getByRole("link", { name: "Staff console" })).toHaveCount(0);
  await page.getByRole("button", { name: "End support session" }).click();
  await expect(page.getByRole("heading", { name: "Madhapur Motors" })).toBeVisible();
  await expect(banner).toHaveCount(0);

  await page.getByRole("link", { name: "Support inbox" }).click();
  const msg = page.getByRole("listitem").filter({ hasText: owner.email });
  await msg.getByRole("button", { name: "Reply" }).click();
  await msg.getByLabel("Reply to Madhapur Motors").fill("Looking into it now.");
  await msg.getByRole("button", { name: "Send" }).click();
  await expect(page.getByText("Replied to Madhapur Motors; it shows in their chat and bell.")).toBeVisible();
  const chat = await (await request.get("/api/support/chat", { headers: { Authorization: `Bearer ${owner.token}` } })).json();
  expect(chat.at(-1)).toMatchObject({ body: "Looking into it now.", from_staff: true });
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.getByRole("link", { name: "Dialing rules" }).click();
  const cell = page.getByRole("button", { name: /^promotional from 1600, outbound: / });
  const was = (await cell.getAttribute("aria-label"))!;
  await cell.click();
  await expect(page.getByRole("status").filter({ hasText: "promotional calls from 1600 numbers (outbound) are now" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^promotional from 1600, outbound: / })).not.toHaveAttribute("aria-label", was);
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.getByRole("link", { name: "System" }).click();
  await expect(page.getByText("Database")).toBeVisible();
  await page.getByRole("link", { name: "Providers" }).click();
  await expect(page.getByRole("heading", { name: /Vendors/ })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await seriousA11yIssues(page)).toEqual([]);
});
