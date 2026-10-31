import AxeBuilder from "@axe-core/playwright";
import { type Page, expect, test } from "@playwright/test";

async function seriousA11yIssues(page: Page) {
  // Measure the settled page: mid-fade text is dimmer than it ends up.
  await page.waitForFunction(() =>
    document.getAnimations().every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity),
  );
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  return violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
}

test("a real account signs in and the shell shows its real data", async ({ page, request }) => {
  const email = `f1-${Date.now()}@example.com`;
  const account = "శ్రీ Traders"; // Telugu must survive the round trip untouched
  const signup = await request.post("/api/auth/signup", {
    data: { email, password: "correct horse battery", account_name: account },
  });
  expect(signup.ok()).toBeTruthy();

  await page.goto("/");
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.getByLabel("Password").fill("wrong password!");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("don't match");

  await page.getByLabel("Password").fill("correct horse battery");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(account);
  await expect(page.getByTitle("Credit balance (1 credit = ₹1)")).toContainText("50");
  await expect(page.getByRole("button", { name: /^Notifications/ })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  await page.keyboard.type("light theme");
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  expect(await seriousA11yIssues(page)).toEqual([]);

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await page.setViewportSize({ width: 375, height: 812 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("dialog", { name: "Menu" })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("dialog", { name: "Menu" }).getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
});
