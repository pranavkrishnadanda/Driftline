/**
 * The site header on every page: navigation with the current view marked, the main call
 * to action, the theme switch (remembered across visits), and on small screens a menu
 * that traps focus and closes on Escape. Runs against the stub gateway
 * (`bun run test:e2e:stub`).
 */
import { expect, test } from "@playwright/test";

import { VIEWS } from "./views";

for (const view of VIEWS) {
  test(`${view.name} (${view.path}) has the header, with the right view marked`, async ({
    page,
  }) => {
    await page.goto(view.path);
    const header = page.getByRole("banner");
    await expect(header.getByRole("link", { name: "Driftline" })).toHaveAttribute("href", "/");
    await expect(header.getByRole("link", { name: "Try Ask" })).toBeVisible();
    // The recorded-demo banner belongs to the demo build only.
    await expect(page.getByTestId("demo-banner")).toHaveCount(0);
    const nav = header.getByRole("navigation", { name: "Views" });
    await expect(nav.getByRole("link")).toHaveCount(5);
    const current = nav.locator("[aria-current=page]");
    if (view.name === "landing") await expect(current).toHaveCount(0);
    else if (view.name === "document") await expect(current).toHaveText("Timeline");
    else await expect(current).toHaveText(new RegExp(`^${view.name}$`, "i"));
  });
}

test("the theme switch turns dark mode on and remembers it", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const html = page.locator("html");
  await expect(html).not.toHaveClass(/\bdark\b/);
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(html).toHaveClass(/\bdark\b/);
  await page.reload();
  await expect(html).toHaveClass(/\bdark\b/);
  await expect(page.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
});

test("dark mode follows the system when nothing was chosen", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/stats");
  await expect(page.locator("html")).toHaveClass(/\bdark\b/);
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the menu opens, keeps focus inside, and closes on Escape", async ({ page }) => {
    await page.goto("/drift");
    const header = page.getByRole("banner");
    await expect(header.getByRole("navigation", { name: "Views" })).toBeHidden();

    const open = header.getByRole("button", { name: "Open menu" });
    await open.click();
    const menu = page.getByRole("dialog", { name: "Menu" });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("link", { name: "Drift" })).toHaveAttribute("aria-current", "page");

    // Tab cycles within the menu.
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      expect(await menu.evaluate((el) => el.contains(document.activeElement))).toBe(true);
    }

    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(open).toBeFocused();

    await open.click();
    await page.getByRole("dialog", { name: "Menu" }).getByRole("link", { name: "Review" }).click();
    await expect(page).toHaveURL(/\/review$/);
    await expect(page.getByRole("dialog", { name: "Menu" })).toBeHidden();
  });
});
