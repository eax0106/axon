import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";

test("billing shows the real ledger, saves limits, and the store and top-up say what to connect", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f5-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  const { access_token } = await signup.json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  // First run: nothing done yet.
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Get your first employee on the phone" })).toBeVisible();
  await expect(page.getByText("0/5")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // The ledger as the API keeps it: 50 free credits, opening 0, closing 50.
  await page.getByRole("link", { name: /credits/ }).first().click();
  await expect(page).toHaveURL(/\/billing$/);
  await expect(page.getByRole("heading", { name: "Credits", exact: true })).toBeVisible();
  const statement = page.getByRole("region", { name: /Statement for/ });
  await expect(statement.getByText("Opening balance")).toBeVisible();
  await expect(statement.getByText("Free credits · 1")).toBeVisible();
  await expect(statement.getByText("+50")).toBeVisible();
  const row = page.getByRole("row").filter({ hasText: "Free credits" });
  await expect(row.getByRole("cell").nth(2)).toHaveText("+50");
  await expect(row.getByRole("cell").nth(3)).toHaveText("50");
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Spend cap saves and clears; a bad GSTIN is refused in place.
  await page.getByLabel("Hourly spend cap (credits)").fill("25");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Hourly spend cap (credits)")).toHaveValue("25");
  await page.getByLabel("Hourly spend cap (credits)").fill("");
  await page.getByLabel("GSTIN").fill("123");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("that GSTIN is not valid");
  await page.getByLabel("GSTIN").fill("");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Hourly spend cap (credits)")).toHaveValue("");

  // Without payment keys the top-up says which provider to connect.
  await page.getByRole("radio", { name: "₹500" }).click();
  await page.getByRole("button", { name: /^Pay ₹500/ }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connect" })).toBeVisible();

  // The number store needs the carrier.
  await page.goto("/numbers");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Connect" })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/billing");
  await expect(page.getByRole("heading", { name: "Credits", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
