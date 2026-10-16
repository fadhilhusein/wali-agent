const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
      reducedMotion: "no-preference",
    });
    page.setDefaultNavigationTimeout(90_000);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/wali/**", (route) => {
      const action = new URL(route.request().url()).pathname.split("/").at(-1);
      assert(["info", "pending"].includes(action));
      return route.fulfill({
        json:
          action === "info"
            ? {
                roles: ["owner"],
                simulation: "Test simulation",
                screening_model: false,
              }
            : { requests: [] },
      });
    });
    await page.goto(
      `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/chat`,
      { waitUntil: "domcontentloaded" },
    );
    const card = page.locator(".paper-prompt").first();
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh")?.paperShaderMount
          ?.speed === 1,
    );
    await page.waitForFunction(() => {
      const meshes = [...document.querySelectorAll(".paper-prompt-mesh")];
      return (
        meshes.length === 4 &&
        meshes.every((el) => el.paperShaderMount?.speed === 0)
      );
    });
    await page.screenshot({
      path: path.join(output, "prompt-mesh-desktop.png"),
    });
    await card.hover();
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount.speed ===
        1,
    );
    const firstFrame = await card
      .locator(".paper-prompt-mesh")
      .evaluate((el) => el.paperShaderMount.currentFrame);
    await page.waitForFunction(
      (frame) =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount
          .currentFrame > frame,
      firstFrame,
    );
    await page.mouse.move(500, 40);
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount.speed ===
        0,
    );
    await page.keyboard.press("Tab");
    await card.focus();
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount.speed ===
        1,
    );
    await card.press("Space");
    assert(await page.locator("#message-input").inputValue());
    assert(
      await page
        .locator("#message-input")
        .evaluate((el) => el === document.activeElement),
    );
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount.speed ===
        0,
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await card.hover();
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-prompt-mesh").paperShaderMount.speed ===
        0,
    );
    for (const width of [1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 700 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      const size = await card.boundingBox();
      assert(size.height >= 44);
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "prompt-mesh-mobile.png"),
        });
    }
    assert.deepEqual(errors, []);
    console.log(
      "PASS intro stops, hover animates actual frames, pointer leave stops, keyboard activation/focus, reduced motion and responsive cards",
    );
    await fs.writeFile(
      path.join(output, "prompt-mesh-results.json"),
      JSON.stringify({ result: "pass", errors }, null, 2),
    );
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
