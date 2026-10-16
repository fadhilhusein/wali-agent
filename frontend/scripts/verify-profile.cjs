const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/wali/**", async (route) => {
      const action = new URL(route.request().url()).pathname.split("/").at(-1);
      assert(
        ["info", "pending"].includes(action),
        `Unexpected action: ${action}`,
      );
      await route.fulfill({
        json:
          action === "info"
            ? {
                roles: ["owner", "bookkeeper", "staff"],
                simulation:
                  "Local simulation. No real money or bank connections.",
                screening_model: false,
              }
            : { requests: [] },
      });
    });
    await page.goto(
      `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/mandate`,
    );
    const avatar = page.locator(".paper-avatar");
    const popup = page.getByRole("dialog", { name: "Settings and help" });
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .waitFor();
    await avatar.click();
    await popup.waitFor();
    await page.waitForFunction(() => {
      const opacity = Number(
        getComputedStyle(document.querySelector(".paper-settings")).opacity,
      );
      return opacity > 0 && opacity < 1;
    });
    await page.waitForFunction(
      () =>
        Number(
          getComputedStyle(document.querySelector(".paper-settings")).opacity,
        ) === 1,
    );
    assert.equal(await avatar.getAttribute("aria-expanded"), "true");
    assert.equal(await page.locator("dialog[open]").count(), 0);
    const contrastChecks = await popup.evaluate((panel) => {
      const luminance = (color) => {
        const channels = color
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map((value) => {
            const n = Number(value) / 255;
            return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          });
        return (
          channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
        );
      };
      return [
        ["h2", ".paper-settings", "color", 4.5],
        [".paper-settings-heading p", ".paper-settings", "color", 4.5],
        [".paper-settings-note", ".paper-settings-role", "color", 4.5],
        ["select", "select", "color", 4.5],
        ["select", "select", "borderTopColor", 3],
      ].map(([selector, background, property, minimum]) => {
        const foregroundStyle = getComputedStyle(panel.querySelector(selector));
        const backgroundStyle = getComputedStyle(
          background === ".paper-settings"
            ? panel
            : panel.querySelector(background),
        );
        const a = luminance(foregroundStyle[property]);
        const b = luminance(backgroundStyle.backgroundColor);
        return {
          selector,
          property,
          minimum,
          ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
        };
      });
    });
    for (const check of contrastChecks)
      assert(check.ratio >= check.minimum, JSON.stringify(check));
    await page.screenshot({ path: path.join(output, "profile-desktop.png") });
    await page.keyboard.press("Tab");
    assert(
      await page
        .getByRole("button", { name: "Close settings" })
        .evaluate((el) => el === document.activeElement),
    );
    await page.keyboard.press("Tab");
    assert(
      await page
        .getByRole("combobox", { name: "Acting as" })
        .evaluate((el) => el === document.activeElement),
    );
    await page
      .getByRole("combobox", { name: "Acting as" })
      .selectOption("staff");
    await page.getByRole("heading", { name: "Owner action" }).waitFor();
    await page.keyboard.press("Escape");
    assert(await avatar.evaluate((el) => el === document.activeElement));
    await popup.waitFor({ state: "detached" });
    await avatar.click();
    await page
      .getByRole("heading", { name: "Business mandate", exact: true })
      .click();
    await popup.waitFor({ state: "detached" });
    console.log(
      "PASS avatar animation, keyboard focus, role switch, Escape and outside dismissal",
    );

    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: width < 500 ? 640 : 900 });
      await avatar.click();
      await page.waitForFunction(
        () =>
          Number(
            getComputedStyle(document.querySelector(".paper-settings")).opacity,
          ) === 1,
      );
      const bounds = await popup.boundingBox();
      assert(
        bounds.x >= 0 && bounds.x + bounds.width <= width,
        `Popup overflow at ${width}`,
      );
      const avatarBounds = await avatar.boundingBox();
      assert(bounds.y > avatarBounds.y, "Popup must sit below avatar");
      await page
        .getByRole("combobox", { name: "Acting as" })
        .scrollIntoViewIfNeeded();
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "profile-mobile.png"),
        });
      await page.getByRole("button", { name: "Close settings" }).click();
      await popup.waitFor({ state: "detached" });
    }
    await page.setViewportSize({ width: 320, height: 400 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await avatar.click();
    await popup.waitFor();
    await page.waitForFunction(
      () =>
        Number(
          getComputedStyle(document.querySelector(".paper-settings")).opacity,
        ) === 1,
    );
    const small = await popup.boundingBox();
    assert(small.y + small.height <= 400, "Short viewport overflow");
    assert.equal(
      await popup.evaluate((el) => getComputedStyle(el).transform),
      "matrix(1, 0, 0, 1, 0, 0)",
    );
    await page.getByRole("combobox", { name: "Acting as" }).focus();
    await page.keyboard.press("Tab");
    await popup.waitFor({ state: "detached" });
    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await page
      .getByRole("button", { name: "Settings and help", exact: true })
      .click();
    await popup.waitFor();
    assert.equal(await page.locator(".paper-main").getAttribute("inert"), null);
    await page.keyboard.press("Escape");
    assert(await avatar.evaluate((el) => el === document.activeElement));
    assert.deepEqual(errors, []);
    console.log(
      "PASS five viewport widths, short-screen scrolling, reduced motion, Tab exit and mobile sidebar shortcut",
    );
    await fs.writeFile(
      path.join(output, "profile-results.json"),
      JSON.stringify(
        {
          result: "pass",
          errors,
          contrastChecks,
          widths: [1440, 1024, 768, 390, 320],
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
