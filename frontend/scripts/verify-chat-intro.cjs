const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  try {
    for (const reduced of [false, true]) {
      const page = await browser.newPage({
        viewport: { width: 390, height: 700 },
        reducedMotion: reduced ? "reduce" : "no-preference",
      });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript(() => {
        window.__chatIntroTimings = [];
        const original = Element.prototype.animate;
        Element.prototype.animate = function (keyframes, options) {
          const animation = original.call(this, keyframes, options);
          if (this.dataset.chatIntro) {
            window.__chatIntroTimings.push({
              part: this.dataset.chatIntro,
              delay: animation.effect.getTiming().delay,
            });
          }
          return animation;
        };
      });
      let releaseInfo;
      const ready = new Promise((resolve) => {
        releaseInfo = resolve;
      });
      await page.route("**/api/wali/**", async (route) => {
        const action = new URL(route.request().url()).pathname
          .split("/")
          .at(-1);
        assert(["info", "pending", "chat", "reset"].includes(action));
        if (action === "info") await ready;
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
                : action === "chat"
                  ? { reply: "Test reply", blocked: false, new_requests: [] }
                  : { status: "reset" },
        });
      });
      await page.goto(
        `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/chat`,
        { waitUntil: "domcontentloaded" },
      );
      await page.getByRole("heading", { name: "Connecting to Wali" }).waitFor();
      releaseInfo();
      await page.locator(".paper-welcome").waitFor();
      if (!reduced) {
        await page.waitForFunction(() =>
          window.__chatIntroTimings.some((item) => item.part === "greeting"),
        );
        const timings = await page.evaluate(() => window.__chatIntroTimings);
        assert.equal(timings.find((item) => item.part === "greeting").delay, 0);
        assert.equal(
          timings.find((item) => item.part === "question").delay,
          80,
        );
        assert.deepEqual(
          [
            ...new Set(
              timings
                .filter((item) => item.part === "prompt")
                .map((item) => Math.round(item.delay)),
            ),
          ],
          [160, 220, 280, 340],
        );
        assert.equal(
          timings.find((item) => item.part === "composer").delay,
          400,
        );
        await page.locator("#message-input").focus();
        await page.waitForFunction(
          () =>
            getComputedStyle(document.querySelector(".paper-composer"))
              .opacity === "1",
        );
      }
      await page.locator(".paper-prompt:enabled").first().waitFor();
      const running = () =>
        page
          .locator("[data-chat-intro]")
          .evaluateAll(
            (els) =>
              els
                .flatMap((el) => el.getAnimations())
                .filter((animation) => animation.playState === "running")
                .length,
          );
      assert.equal(await running(), 0);
      if (reduced)
        assert.equal(
          await page.evaluate(() => window.__chatIntroTimings.length),
          0,
        );
      assert.equal(
        await page
          .locator(".paper-disclaimer")
          .evaluate((el) => getComputedStyle(el).opacity),
        "0.5",
      );
      await page.locator("#message-input").fill("Test intro only");
      assert.equal(await running(), 0);
      await page
        .getByRole("button", { name: "Send message", exact: true })
        .click();
      await page.getByText("Test reply", { exact: true }).waitFor();
      await page
        .getByRole("button", { name: "Open navigation menu", exact: true })
        .click();
      await page.getByRole("button", { name: "New chat", exact: true }).click();
      await page.locator(".paper-welcome").waitFor();
      assert.equal(await running(), 0);
      const send = await page
        .getByRole("button", { name: "Send message", exact: true })
        .boundingBox();
      assert(send.y + send.height <= 700);
      assert.deepEqual(errors, []);
      if (!reduced) {
        await page.reload({ waitUntil: "domcontentloaded" });
        await page.waitForFunction(() =>
          window.__chatIntroTimings.some((item) => item.part === "greeting"),
        );
        await page.waitForFunction(() =>
          [...document.querySelectorAll("[data-chat-intro]")].every((el) =>
            el
              .getAnimations()
              .every((animation) => animation.playState !== "running"),
          ),
        );
        assert.equal(
          await page
            .locator(".paper-composer")
            .evaluate((el) => getComputedStyle(el).opacity),
          "1",
        );
        assert.equal(
          await page
            .locator(".paper-disclaimer")
            .evaluate((el) => getComputedStyle(el).opacity),
          "0.5",
        );
      }
      if (!reduced)
        await page.screenshot({
          path: path.join(output, "chat-intro-complete.png"),
        });
      console.log(
        `PASS ${reduced ? "reduced motion skips intro" : "staggered text/cards/composer and immediate completion on focus"}: existing opacity, no replay on typing/New chat, mobile composer and no runtime errors`,
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
