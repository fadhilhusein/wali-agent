const { chromium } = require("playwright");
const assert = require("node:assert/strict");

async function main() {
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    for (const reduced of [false, true]) {
      const page = await browser.newPage({
        viewport: { width: 1024, height: 700 },
        reducedMotion: reduced ? "reduce" : "no-preference",
      });
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.addInitScript(() => {
        window.__messageAnimations = [];
        window.__scrollSamples = [];
        const original = Element.prototype.animate;
        Element.prototype.animate = function (frames, options) {
          const animation = original.call(this, frames, options);
          if (this.classList.contains("paper-message"))
            window.__messageAnimations.push({
              className: this.className,
              duration: animation.effect.getTiming().duration,
            });
          return animation;
        };
        document.addEventListener(
          "scroll",
          (event) => {
            if (event.target.classList?.contains("paper-chat-scroll"))
              window.__scrollSamples.push(event.target.scrollTop);
          },
          true,
        );
      });
      let releaseReply;
      let chatCount = 0;
      await page.route("**/api/wali/**", async (route) => {
        const action = new URL(route.request().url()).pathname
          .split("/")
          .at(-1);
        assert(["info", "pending", "chat"].includes(action));
        if (action === "chat") {
          chatCount++;
          await new Promise((resolve) => {
            releaseReply = resolve;
          });
        }
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
                    reply: Array.from(
                      { length: 65 },
                      (_, i) =>
                        `Test reply ${chatCount}, item ${i + 1}: review this record.`,
                    ).join("\n"),
                    blocked: false,
                    new_requests: [],
                  },
        });
      });
      await page.goto(
        `${process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000"}/chat`,
        { waitUntil: "domcontentloaded" },
      );
      const input = page.locator("#message-input");
      const scroller = page.locator(".paper-chat-scroll");
      await page.locator(".paper-prompt:enabled").first().waitFor();
      await input.fill("First test message");
      await input.press("Enter");
      await page.getByText("Thinking through your request…").waitFor();
      while (!releaseReply) await page.waitForTimeout(20);
      releaseReply();
      await page.waitForFunction(
        () => document.querySelectorAll(".paper-reply").length === 1,
      );
      await page.waitForFunction(() => {
        const el = document.querySelector(".paper-chat-scroll");
        return el.scrollHeight - el.scrollTop - el.clientHeight < 3;
      });
      if (!reduced) {
        const records = await page.evaluate(() => window.__messageAnimations);
        assert(
          records.some(
            (entry) =>
              entry.className.includes("paper-message-user") &&
              entry.duration === 240,
          ),
        );
        assert(
          records.some(
            (entry) =>
              entry.className.includes("paper-message-assistant") &&
              entry.duration === 240,
          ),
        );
        const samples = await page.evaluate(() => window.__scrollSamples);
        const maximum = await scroller.evaluate(
          (el) => el.scrollHeight - el.clientHeight,
        );
        assert(
          samples.filter((top) => top > 0 && top < maximum - 3).length > 1,
          "Expected intermediate smooth-scroll positions",
        );
      }
      assert.equal(
        await page
          .locator(".paper-message")
          .evaluateAll(
            (elements) =>
              elements
                .flatMap((el) => el.getAnimations())
                .filter((animation) => animation.playState === "running")
                .length,
          ),
        0,
      );
      releaseReply = null;
      await input.fill("Second test message");
      await input.press("Enter");
      await page.getByText("Thinking through your request…").waitFor();
      while (!releaseReply) await page.waitForTimeout(20);
      await scroller.dispatchEvent("wheel", { deltaY: -500 });
      await scroller.evaluate((el) => {
        el.scrollTo({ top: 0, behavior: "instant" });
        el.dispatchEvent(new Event("scroll"));
      });
      releaseReply();
      await page.waitForFunction(
        () => document.querySelectorAll(".paper-reply").length === 2,
      );
      await page.waitForTimeout(350);
      assert.equal(await scroller.evaluate((el) => el.scrollTop), 0);
      releaseReply = null;
      await input.fill("Resume following with a new message");
      await input.press("Enter");
      await page.getByText("Thinking through your request…").waitFor();
      while (!releaseReply) await page.waitForTimeout(20);
      releaseReply();
      await page.waitForFunction(
        () => document.querySelectorAll(".paper-reply").length === 3,
      );
      await page.waitForFunction(() => {
        const el = document.querySelector(".paper-chat-scroll");
        return el.scrollHeight - el.scrollTop - el.clientHeight < 3;
      });
      await page.getByRole("link", { name: "Approvals", exact: true }).click();
      await page
        .getByRole("heading", { name: "Approvals", exact: true })
        .waitFor();
      await page.evaluate(() => {
        window.__messageAnimations = [];
      });
      await page.getByRole("link", { name: "Chat", exact: true }).click();
      await page.locator(".paper-reply").first().waitFor();
      assert.equal(
        (await page.evaluate(() => window.__messageAnimations)).length,
        0,
      );
      assert.deepEqual(errors, []);
      console.log(
        `PASS ${reduced ? "reduced-motion immediate updates" : "new bubble/pending animations and actual smooth scroll"}, manual scroll interruption, preserved reading position and no replay of restored history`,
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
