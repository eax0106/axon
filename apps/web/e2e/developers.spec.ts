import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { sql } from "./stack";

test("developers: key shown once and revoked; webhook secret once, rotated, paused; request log", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f11-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Gachibowli Motors" },
  });
  const { access_token } = await signup.json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  await page.goto("/developers");
  await page.getByLabel("New key for").fill("Our CRM");
  await page.getByRole("button", { name: "Create key" }).click();
  const key = (await page.getByLabel("Your new API key").textContent()) ?? "";
  expect(key).toMatch(/^axk_/);
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByLabel("Your new API key")).toHaveCount(0);

  // The key works on the public API, shows up in the request log, and stops working once revoked.
  const v1 = () => request.get("/api/v1/account", { headers: { Authorization: `Bearer ${key}` } });
  expect((await v1()).status()).toBe(200);
  await page.getByRole("tab", { name: "Requests" }).click();
  await expect(page.getByText("/v1/account")).toBeVisible();
  await page.getByRole("tab", { name: "Keys" }).click();
  await page.getByRole("button", { name: "Revoke" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText(/^Revoked/)).toBeVisible();
  expect((await v1()).status()).toBe(401);

  await page.getByRole("tab", { name: "Webhooks" }).click();
  await page.getByLabel("Address (https)").fill("https://hooks.example.com/axon");
  await page.getByRole("checkbox", { name: /call\.completed/ }).check();
  await page.getByRole("checkbox", { name: /lead\.created/ }).check();
  await page.getByRole("button", { name: "Add webhook" }).click();
  const secret = await page.getByLabel(/Signing secret for/).textContent();
  expect(secret).toBeTruthy();
  await expect(page.getByText("call.completed, lead.created")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Done" }).click();
  await page.getByRole("button", { name: "Rotate secret" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Rotate" }).click();
  const rotated = await page.getByLabel(/New signing secret for/).textContent();
  expect(rotated).toBeTruthy();
  expect(rotated).not.toBe(secret);
  await page.getByRole("button", { name: "Pause" }).click();
  await expect(page.getByText("● Paused")).toBeVisible();

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await seriousA11yIssues(page)).toEqual([]);
});

test("settings, password, do-not-call and support", async ({ page, request }) => {
  const email = `f11s-${Date.now()}@example.com`;
  const signup = await request.post("/api/auth/signup", { data: { email, password: "correct horse battery", account_name: "Kondapur Clinic" } });
  const { access_token } = await signup.json();
  // Only the first load gets the sign-up token: after the password change the page holds a new one.
  await page.addInitScript((t) => localStorage.getItem("axon.token") ?? localStorage.setItem("axon.token", t), access_token);

  const me = await (await request.get("/api/accounts/me", { headers: { Authorization: `Bearer ${access_token}` } })).json();
  const emp = await (await request.post("/api/employees", { headers: { Authorization: `Bearer ${access_token}` }, data: { channel: "inbound", language: "en", name: "Asha" } })).json();
  await page.goto("/account");
  await page.getByLabel("Business name on calls").fill("Kondapur Family Clinic");
  await page.getByLabel("Longest call (minutes)").fill("5");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Saved" })).toBeVisible();
  const settings = await (await request.get("/api/account/settings", { headers: { Authorization: `Bearer ${access_token}` } })).json();
  expect(settings).toMatchObject({ business_name: "Kondapur Family Clinic", max_call_s: 300 });

  // A wrong current password is refused in place; a right one keeps this session going.
  await page.getByLabel("Current password").fill("not it at all");
  await page.getByLabel("New password").fill("a much better passphrase");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText(/current password is wrong/i)).toBeVisible();
  await page.getByLabel("Current password").fill("correct horse battery");
  await page.getByLabel("New password").fill("a much better passphrase");
  await page.getByRole("button", { name: "Change password" }).click();
  await expect(page.getByText("Password changed. Other sessions are signed out.")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Your account" })).toBeVisible();
  expect((await request.post("/api/auth/login", { data: { email, password: "correct horse battery" } })).status()).toBe(401);
  expect((await request.post("/api/auth/login", { data: { email, password: "a much better passphrase" } })).status()).toBe(200);

  await page.getByLabel(/^Numbers/).fill("9876500101\n98765 00102, +91 98765 00101, hello");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("2 added · 0 already listed · 1 not phone numbers")).toBeVisible();
  await page.getByLabel(/^Numbers/).fill("9876500101");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("0 added · 1 already listed · 0 not phone numbers")).toBeVisible();
  await page.getByLabel("Search do-not-call numbers").fill("00102");
  await expect(page.getByText("+919876500101")).toHaveCount(0);
  await page.getByRole("button", { name: "Remove +919876500102" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("No number matches.")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // A finished call is rated from its page; the rating reaches the support record.
  const call = sql(`INSERT INTO calls (account_id, employee_id, direction, channel, status, caller_phone, ended_at) VALUES ('${me.account.id}', '${emp.id}', 'inbound', 'inbound', 'completed', '+919876500201', now()) RETURNING id`);
  await page.goto(`/calls/${call}`);
  await page.getByRole("radio", { name: "2 of 5" }).click();
  await page.getByPlaceholder("What happened (optional)").fill("It talked over the caller.");
  await page.getByRole("button", { name: "Send rating" }).click();
  await expect(page.getByText("Thanks. The Axon team sees it with the call.")).toBeVisible();
  expect(sql(`SELECT rating FROM support_messages WHERE call_id = '${call}'`)).toBe("2");

  await page.goto("/support");
  await page.getByRole("textbox", { name: "Message" }).fill("How do I connect Zapier?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("list", { name: "Messages" }).getByText("How do I connect Zapier?")).toBeVisible();
  await page.getByLabel("What should Axon do better?").fill("A Kannada voice, please.");
  await page.getByRole("button", { name: "Send feedback" }).click();
  await expect(page.getByText("Thanks, the team reads every note.")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await seriousA11yIssues(page)).toEqual([]);
});
