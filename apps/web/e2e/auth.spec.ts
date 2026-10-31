import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

async function seriousA11yIssues(page: Page) {
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity),
  );
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

test("sign up, sign out, sign back in to the page asked for, and start a phone check", async ({ page }) => {
  const email = `f2-${Date.now()}@example.com`;
  const business = "శ్రీ లక్ష్మి Traders";

  await page.goto("/sign-up");
  // The page is a lazy chunk: measure it once it has rendered, not the blank frame before.
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Enter your business name.")).toBeVisible();
  await expect(page.getByText("Enter a valid email address.")).toBeVisible();
  await expect(page.getByText("Use at least 8 characters.")).toBeVisible();

  await page.getByLabel("Business name").fill(business);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("short");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Use at least 8 characters.")).toBeVisible();
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(business);

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/sign-in$/);

  // The same email again is refused next to the field.
  await page.goto("/sign-up");
  await page.getByLabel("Business name").fill("Another");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("This email already has an account.")).toBeVisible();

  // A protected page asked for while signed out is where sign-in lands.
  await page.goto("/account");
  await expect(page).toHaveURL(/\/sign-in$/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("wrong password!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");
  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your account");

  // A malformed number never leaves the browser; a real one reaches the API, which on a stack
  // without carrier keys answers 503, shown as the calm "connect" state, not a crash.
  await page.getByLabel("Mobile number").fill("12345");
  await page.getByRole("button", { name: "Call me with a code" }).click();
  await expect(page.getByText("Enter a 10-digit Indian mobile number.")).toBeVisible();
  await page.getByLabel("Mobile number").fill("9876543210");
  await page.getByRole("button", { name: "Call me with a code" }).click();
  await expect(page.getByRole("status")).toContainText("Connect Vobiz to use this");
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
