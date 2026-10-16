const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  try {
    for (const fallback of [false, true]) {
      const page = await browser.newPage({
        viewport: { width: 1440, height: 900 },
        reducedMotion: "no-preference",
      });
      const errors = [];
      page.setDefaultNavigationTimeout(120_000);
      page.on("pageerror", (error) => errors.push(error.message));
      if (fallback)
        await page.addInitScript(() => {
          const original = HTMLCanvasElement.prototype.getContext;
          HTMLCanvasElement.prototype.getContext = function (type, ...args) {
            return type === "webgl2"
              ? null
              : original.call(this, type, ...args);
          };
        });
      await page.route("**/api/wali/**", (route) => {
        const action = new URL(route.request().url()).pathname
          .split("/")
          .at(-1);
        assert(["info", "pending", "chat"].includes(action));
        return route.fulfill({
          json:
            action === "info"
              ? {
                  roles: ["owner"],
                  simulation: "Test simulation",
                  screening_model: false,
                }
              : action === "pending"
                ? { requests: [] }
                : {
                    reply: "Test reply. No financial action performed.",
                    blocked: false,
                    new_requests: [],
                  },
        });
      });
      await page.goto(
        `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/chat`,
      );
      await page.locator(".paper-prompt:enabled").first().waitFor();
      const background = page.locator(".paper-chat-background");
      assert.equal(await background.getAttribute("aria-hidden"), "true");
      assert.equal(
        await background.evaluate((el) => getComputedStyle(el).pointerEvents),
        "none",
      );
      if (!fallback) {
        await page.locator(".paper-chat-grain canvas").waitFor();
        await page.waitForFunction(
          () =>
            document.querySelector(".paper-chat-grain")?.paperShaderMount
              ?.speed > 0,
        );
        await page.screenshot({
          path: path.join(output, "chat-grain-desktop.png"),
        });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.waitForFunction(
          () =>
            document.querySelector(".paper-chat-grain")?.paperShaderMount
              ?.speed === 0,
        );
      } else {
        assert.equal(await background.locator("canvas").count(), 0);
      }
      await page.setViewportSize({ width: 390, height: 700 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      if (!fallback)
        await page.screenshot({
          path: path.join(output, "chat-grain-mobile.png"),
        });
      await page.locator(".paper-prompt").first().click();
      await page
        .getByRole("button", { name: "Send message", exact: true })
        .click();
      await page
        .getByText("Test reply. No financial action performed.")
        .waitFor();
      assert.equal(
        await background.evaluate((el) => getComputedStyle(el).opacity),
        "0.16",
      );
      if (!fallback)
        await page.screenshot({
          path: path.join(output, "chat-grain-conversation.png"),
        });
      const send = await page
        .getByRole("button", { name: "Send message", exact: true })
        .boundingBox();
      assert(send.y + send.height <= 700);
      await page.goto(
        `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/mandate`,
      );
      assert.equal(await page.locator(".paper-chat-background").count(), 0);
      assert.deepEqual(errors, []);
      console.log(
        `PASS ${fallback ? "WebGL fallback" : "Grain shader, animation and reduced motion"}: mobile layout, prompt/send, conversation opacity and Chat-only scope`,
      );
      await page.close();
    }
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
