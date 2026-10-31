import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";
import { publish, sql } from "./stack";

test("a live call streams its stages and words; test calls show what to connect", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f4-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const me = await (await request.get("/api/accounts/me", { headers: auth })).json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  // A call in progress on this account; the engine would create it when a call starts.
  const callId = sql(
    `INSERT INTO calls (account_id, direction, channel, status, is_test) VALUES ('${me.account.id}', 'inbound', 'instant', 'in_progress', true) RETURNING id`,
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(`/calls/${callId}/live`);
  await expect(page.getByText("Words appear here as they are spoken.")).toBeVisible();

  // The API subscribes once the socket is open; repeat the first event until it lands.
  await expect(async () => {
    publish(callId, { type: "started", call_id: callId, language: "te" });
    await expect(page.getByText("On a call · Listening")).toBeVisible({ timeout: 500 });
  }).toPass({ timeout: 10_000 });

  publish(callId, { type: "user_started_speaking" });
  publish(callId, { type: "user_transcript", text: "నాకు 3 BHK కావాలి" });
  publish(callId, { type: "user_stopped_speaking" });
  await expect(page.getByText("On a call · Thinking")).toBeVisible();
  publish(callId, { type: "bot_started_speaking" });
  publish(callId, { type: "bot_text", text: "తప్పకుండా," });
  publish(callId, { type: "bot_text", text: "మీ budget ఎంత?" });
  await expect(page.getByText("On a call · Speaking")).toBeVisible();
  await expect(page.getByText("తప్పకుండా, మీ budget ఎంత?")).toBeVisible();
  await expect(page.getByText("నాకు 3 BHK కావాలి")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  publish(callId, { type: "bot_stopped_speaking" });
  publish(callId, { type: "action", name: "book_site_visit", ok: true, ms: 420 });
  publish(callId, { type: "ended", reason: "caller_hung_up" });
  await expect(page.getByText("Call ended")).toBeVisible();
  await expect(page.getByText("Ended: caller hung up")).toBeVisible();
  await expect(page.getByText("Used book_site_visit")).toBeVisible();
  expect(errors).toEqual([]);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.setViewportSize({ width: 1280, height: 800 });

  // A call opened after it ended shows its stored transcript, not a call stuck ringing.
  const done = sql(
    `INSERT INTO calls (account_id, direction, channel, status, is_test, transcript) VALUES ('${me.account.id}', 'outbound', 'instant', 'completed', true, '[{"role":"assistant","text":"నమస్తే, Kokapet Homes."},{"role":"user","text":"Not interested, thanks."}]') RETURNING id`,
  );
  await page.goto(`/calls/${done}/live`);
  await expect(page.getByText("Call ended")).toBeVisible();
  await expect(page.getByText("Not interested, thanks.")).toBeVisible();

  // Someone else's call is refused by the API, shown plainly.
  await page.goto("/calls/00000000-0000-0000-0000-000000000001/live");
  await expect(page.getByText("Not available")).toBeVisible();

  // Try it: without keys, chat and the browser call each say which provider to connect.
  const employee = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "en" } })).json();
  await page.goto(`/employees/${employee.id}/try`);
  await page.getByLabel("Your message").fill("Hello, is this Kokapet Homes?");
  await page.getByRole("button", { name: "Send" }).click();
  await expect(page.getByRole("status")).toContainText("Connect");
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("tab", { name: /Talk in the browser/ }).click();
  await page.getByRole("button", { name: "Start a browser call" }).click();
  await expect(page.getByRole("status")).toContainText("Connect");
  await page.getByRole("tab", { name: /Ring my phone/ }).click();
  await expect(page.getByRole("link", { name: "Verify your phone" })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
});
