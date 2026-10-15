const { chromium, devices } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({
      ...devices["Pixel 7"],
      viewport: { width: 393, height: 700 },
      reducedMotion: "reduce",
    });
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
    const measurements = [];
    for (const [width, height] of [
      [393, 700],
      [390, 640],
      [320, 568],
      [320, 400],
    ]) {
      await page.setViewportSize({ width, height });
      await page.goto(
        `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/chat`,
      );
      await page.locator(".paper-prompt:enabled").first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      // Reproduce an oversized measurement left behind by mobile browser chrome.
      await page
        .locator(".paper-shell")
        .evaluate((el) =>
          el.style.setProperty("--paper-viewport-height", "1000px"),
        );
      const dock = await page.locator(".paper-chat-dock").boundingBox();
      assert(
        dock.y >= 64 && dock.y + dock.height <= height + 1,
        `Composer clipped at ${width}x${height}`,
      );
      await page.locator(".paper-chat-scroll").evaluate((el) => {
        el.scrollTop = 0;
      });
      await page.locator(".paper-prompt").last().scrollIntoViewIfNeeded();
      const scrollTop = await page
        .locator(".paper-chat-scroll")
        .evaluate((el) => el.scrollTop);
      assert(scrollTop > 0, "Empty-state prompts should scroll independently");
      const last = await page.locator(".paper-prompt").last().boundingBox();
      assert(last.y >= 64 && last.y + last.height <= dock.y + 1);
      const after = await page.locator(".paper-chat-dock").boundingBox();
      assert.equal(after.y, dock.y);
      await page.locator(".paper-prompt").last().tap();
      assert(
        await page
          .locator("#message-input")
          .evaluate((el) => el === document.activeElement),
      );
      assert(await page.locator("#message-input").inputValue());
      const send = await page
        .getByRole("button", { name: "Send message", exact: true })
        .boundingBox();
      assert(send.y + send.height <= height);
      measurements.push({ width, height, dock, scrollTop });
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "mobile-composer-fixed.png"),
        });
      console.log(
        `PASS empty mobile chat ${width}x${height}: stale viewport cap, scrolling, prompt focus and send reachability`,
      );
    }
    await page.setViewportSize({ width: 393, height: 700 });
    await page.setViewportSize({ width: 393, height: 400 });
    await page.waitForFunction(
      () =>
        parseFloat(
          document
            .querySelector(".paper-shell")
            .style.getPropertyValue("--paper-viewport-height"),
        ) <= 400,
    );
    const resized = await page.locator(".paper-chat-dock").boundingBox();
    assert(resized.y + resized.height <= 400);
    await page.evaluate(() => {
      Object.defineProperty(window.visualViewport, "height", {
        configurable: true,
        get: () => 340,
      });
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    await page.locator("#message-input").focus();
    await page.waitForFunction(
      () =>
        document.querySelector(".paper-shell").getBoundingClientRect().height <=
        341,
    );
    const keyboardDock = await page.locator(".paper-chat-dock").boundingBox();
    assert(
      keyboardDock.y + keyboardDock.height <= 341,
      JSON.stringify(keyboardDock),
    );
    const keyboardSend = await page
      .getByRole("button", { name: "Send message", exact: true })
      .boundingBox();
    assert(
      keyboardSend.y + keyboardSend.height <= 341,
      JSON.stringify(keyboardSend),
    );
    await page.evaluate(() => {
      delete window.visualViewport.height;
      window.visualViewport.dispatchEvent(new Event("resize"));
    });
    assert.equal(
      await page
        .locator(".paper-shell")
        .evaluate((el) => getComputedStyle(el).position),
      "fixed",
    );
    assert.deepEqual(errors, []);
    await fs.writeFile(
      path.join(output, "mobile-composer-results.json"),
      JSON.stringify({ result: "pass", measurements, errors }, null, 2),
    );
    console.log(
      "PASS reduced visual viewport while focused, fixed shell and viewport recovery; no browser errors",
    );
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
