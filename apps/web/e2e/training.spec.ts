import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";

test("training and actions: teach, facts and rules, documents, an HTTP action, the result webhook", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f10-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  const auth = { Authorization: `Bearer ${access_token}` };
  const emp = await (await request.post("/api/employees", { headers: auth, data: { channel: "instant", language: "te", name: "Priya" } })).json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  await page.goto(`/employees/${emp.id}/training`);
  // Without an AI key, teaching says what to connect and saves nothing.
  await page.getByLabel("What to teach").fill("3 BHK in Tower B is ₹1.35 crore. Never promise a discount.");
  await page.getByRole("button", { name: "Turn into facts and rules" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connect" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Facts" }).or(page.locator("section", { has: page.getByRole("heading", { name: /^Facts/ }) })).getByText("0/60")).toBeVisible();

  // Facts and rules by hand: add, edit, remove; the counts follow.
  await page.getByLabel("New fact").fill("Possession is in March 2027.");
  await page.locator("form", { has: page.getByLabel("New fact") }).getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("Possession is in March 2027.")).toBeVisible();
  await expect(page.getByText("1/60")).toBeVisible();
  await page.getByRole("button", { name: /^Edit: Possession/ }).click();
  await page.getByLabel("Edit fact").fill("Possession is in June 2027.");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText("Possession is in June 2027.")).toBeVisible();
  await page.getByLabel("New rule").fill("Always offer a site visit before ending.");
  await page.locator("form", { has: page.getByLabel("New rule") }).getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("1/20")).toBeVisible();
  await page.getByRole("button", { name: /^Remove: Possession/ }).click();
  await expect(page.getByText("0/60")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // A document needs an embedding key: the state says so and nothing is stored.
  await page.locator("input[type=file][accept*='.pdf']").setInputFiles({ name: "price-list.txt", mimeType: "text/plain", buffer: Buffer.from("3 BHK: 1.35 crore\n2 BHK: 95 lakh") });
  await expect(page.getByRole("status").filter({ hasText: "Connect" })).toBeVisible();
  expect((await (await request.get(`/api/employees/${emp.id}/training`, { headers: auth })).json()).documents).toHaveLength(0);

  // An HTTP action with a secret: saved, the secret comes back masked, and the script now has edits to apply.
  await page.getByRole("link", { name: "Actions" }).click();
  await page.getByLabel("Add an action").selectOption("http_api");
  await page.getByLabel("When to use it").fill("When the caller asks if a flat is still available");
  await page.getByLabel("Address (https)").first().fill("https://api.example.in/stock");
  await page.getByLabel("Sign in with").selectOption("bearer");
  await page.getByLabel("Secret (never shown back)").fill("s3cret-token");
  await page.getByRole("button", { name: "Save actions" }).click();
  await expect(page.getByText("Test it")).toBeVisible(); // shown once the saved list is back
  await expect(page.getByRole("button", { name: "Apply to live calls" })).toBeVisible();
  const stored = (await (await request.get(`/api/employees/${emp.id}/actions`, { headers: auth })).json()).actions[0];
  expect(stored.auth.secret).not.toBe("s3cret-token");
  await expect(page.getByLabel("Secret (never shown back)")).not.toHaveValue("s3cret-token");
  // The test console shows whatever the API answers (here the outside host is not reachable or refuses).
  await page.getByText("Test it").click();
  await page.getByRole("button", { name: "Run" }).click();
  await expect(page.locator("details pre").or(page.locator("details [role=alert]"))).toBeVisible({ timeout: 20_000 });
  expect(await seriousA11yIssues(page)).toEqual([]);

  // The result webhook: trigger saved, secret masked.
  await page.getByLabel("Address (https)").last().fill("https://hooks.example.in/axon");
  await page.getByLabel("Send for").selectOption("skip_voicemail");
  await page.getByLabel("Signing secret (optional, never shown back)").fill("whsec_test_value");
  await page.locator("form", { has: page.getByRole("heading", { name: "Send each result to your system" }) }).getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Send a test" })).toBeVisible();
  const hook = (await (await request.get(`/api/employees/${emp.id}/webhook`, { headers: auth })).json()).webhook;
  expect([hook.trigger, hook.secret === "whsec_test_value"]).toEqual(["skip_voicemail", false]);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
