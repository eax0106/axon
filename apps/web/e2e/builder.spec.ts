import { expect, test } from "@playwright/test";

import { seriousA11yIssues } from "./a11y";

test("hire, write and publish a script, keep versions, tune the voice and behaviour", async ({ page, request }) => {
  const signup = await request.post("/api/auth/signup", {
    data: { email: `f3-${Date.now()}@example.com`, password: "correct horse battery", account_name: "Kokapet Homes" },
  });
  expect(signup.ok()).toBeTruthy();
  const { access_token } = await signup.json();
  await page.addInitScript((t) => localStorage.setItem("axon.token", t), access_token);

  // Empty team: the one showpiece, then the hire flow.
  await page.goto("/employees");
  await expect(page.getByRole("heading", { name: /Describe the job/ })).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("link", { name: "Hire your first AI employee" }).click();
  await page.getByText("Bulk", { exact: true }).click();
  await page.getByLabel("Opening language").selectOption("en");
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Next: describe the job" }).click();

  // Without an LLM key the AI path says which provider to connect and offers the manual path.
  await page.getByLabel("Brief").fill("We sell 2 and 3 BHK flats in Kokapet. Find budget and book a site visit.");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Connect");
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Skip the AI and write the script myself" }).click();
  await expect(page).toHaveURL(/\/employees\/[\w-]+\/script$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("New employee");

  // Script: welcome line and three steps, reorder and delete, autosaved as a draft.
  await page.getByLabel("Welcome line").fill("Namaste! This is Kokapet Homes calling about your enquiry.");
  for (const _ of [1, 2, 3]) await page.getByRole("button", { name: "+ Add a step" }).click();
  await page.getByLabel("Step 1 title").fill("Greet");
  await page.getByLabel("Step 2 title").fill("Qualify");
  await page.getByLabel("Step 3 title").fill("Close");
  await page.getByRole("button", { name: "Move step 3 up" }).click();
  await expect(page.getByLabel("Step 2 title")).toHaveValue("Close");
  await page.getByRole("button", { name: "Delete step 2" }).click();
  await expect(page.getByLabel("Step 2 title")).toHaveValue("Qualify");
  await expect(page.getByText("Draft saved.")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Publish: the bar goes away and version 1 is live.
  await page.getByRole("button", { name: "Apply to live calls" }).click();
  await expect(page.getByRole("button", { name: "Apply to live calls" })).toHaveCount(0);
  await page.getByRole("link", { name: "Versions" }).click();
  await expect(page.getByText("Version 1")).toBeVisible();
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Edit again, then discard: the editor returns to the published words.
  await page.getByRole("link", { name: "Script" }).click();
  await page.getByLabel("Welcome line").fill("A different opening.");
  await expect(page.getByText("Draft saved.")).toBeVisible();
  await page.getByRole("button", { name: "Discard changes" }).click();
  await expect(page.getByLabel("Welcome line")).toHaveValue("Namaste! This is Kokapet Homes calling about your enquiry.");

  // Voice: pick another voice that speaks English; a sample needs a voice vendor key.
  await page.getByRole("link", { name: "Voice" }).click();
  const voices = page.getByRole("radiogroup", { name: "Voices" }).getByRole("radio");
  await expect(voices.first()).toBeVisible();
  const unchosen = page.getByRole("radiogroup", { name: "Voices" }).getByRole("radio", { checked: false }).first();
  await unchosen.click();
  await expect(page.getByRole("radiogroup", { name: "Voices" }).getByRole("radio", { checked: true })).toHaveCount(1);
  await page.getByRole("button", { name: /^Play a sample of/ }).first().click();
  await expect(page.getByRole("status").first()).toContainText("Connect");
  expect(await seriousA11yIssues(page)).toEqual([]);

  // Behaviour: a toggle survives a reload; going live without a number is refused in place.
  await page.getByRole("link", { name: "Behaviour" }).click();
  await page.getByRole("switch", { name: /Warm, natural style/ }).click();
  await expect(page.getByRole("switch", { name: /Warm, natural style/ })).toBeChecked();
  await page.reload();
  await expect(page.getByRole("switch", { name: /Warm, natural style/ })).toBeChecked();
  await page.getByRole("button", { name: "Go live" }).click();
  await expect(page.getByRole("alert")).toContainText("attach a phone number before going live");
  expect(await seriousA11yIssues(page)).toEqual([]);
  await page.getByRole("button", { name: "Duplicate" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("New employee (copy)");

  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/employees");
  await expect(page.getByRole("link", { name: /New employee \(copy\)/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(0);
  expect(await seriousA11yIssues(page)).toEqual([]);
});
