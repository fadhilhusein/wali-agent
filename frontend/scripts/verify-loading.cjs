const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const origin = process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000";
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const results = [];
  try {
    for (const reducedMotion of ["no-preference", "reduce"]) {
      const context = await browser.newContext({
        reducedMotion,
        viewport: { width: 1440, height: 900 },
      });
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      let receiveChat;
      const nextChat = () =>
        new Promise((resolve) => {
          receiveChat = resolve;
        });
      await context.route("**/api/wali/**", async (route) => {
        const action = new URL(route.request().url()).pathname
          .split("/")
          .at(-1);
        if (action === "chat") {
          receiveChat(route);
          return;
        }
        await route.fulfill({
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
      await page.goto(`${origin}/chat`);
      await page.locator(".paper-welcome").waitFor();
      const input = page.getByRole("textbox", { name: "Message Wali" });
      const waiting = page.locator('.paper-message[role="status"]');
      const request = nextChat();
      await input.fill("Review invoices");
      await input.press("Enter");
      const heldRoute = await request;
      await waiting.waitFor();
      const logo = waiting.locator(".paper-assistant-mark");
      assert(await logo.isVisible());
      assert.equal(await logo.getAttribute("aria-hidden"), "true");
      if (reducedMotion === "no-preference") {
        await page.waitForFunction(
          () =>
            document.querySelector('.paper-message[role="status"] .wali-logo')
              .dataset.playback === "playing",
        );
        const start = await logo.locator("svg").innerHTML();
        await page.waitForFunction(
          (initial) =>
            document.querySelector(
              '.paper-message[role="status"] .wali-logo svg',
            ).innerHTML !== initial,
          start,
        );
        const loop = await logo.evaluate(async (el) => {
          await new Promise((resolve) => setTimeout(resolve, 1600));
          return el.dataset.playback;
        });
        assert.equal(loop, "playing");
        await page.screenshot({ path: path.join(output, "chat-loading.png") });
        await page.emulateMedia({ reducedMotion: "reduce" });
        await page.waitForFunction(
          () =>
            document.querySelector('.paper-message[role="status"] .wali-logo')
              .dataset.playback === "static",
        );
        assert.equal(await logo.locator("svg").count(), 0);
        await page.emulateMedia({ reducedMotion: "no-preference" });
        await page.waitForFunction(
          () =>
            document.querySelector('.paper-message[role="status"] .wali-logo')
              .dataset.playback === "playing" &&
            document.querySelector(
              '.paper-message[role="status"] .wali-logo svg',
            ),
        );
      } else {
        assert.equal(await logo.getAttribute("data-playback"), "static");
        assert.equal(await logo.locator("svg").count(), 0);
      }
      await heldRoute.fulfill({
        json: {
          reply: "Test response complete.",
          blocked: false,
          new_requests: [],
        },
      });
      await waiting.waitFor({ state: "detached" });
      await page.getByText("Test response complete.").waitFor();
      const replyLogo = page.locator(".paper-assistant-mark");
      if (reducedMotion === "no-preference") {
        await page.waitForFunction(
          () =>
            document.querySelector(".paper-message-assistant .wali-logo")
              .dataset.playback === "playing",
        );
        await page.waitForFunction(
          () =>
            document.querySelector(".paper-message-assistant .wali-logo")
              .dataset.playback === "complete",
        );
      } else
        assert.equal(await replyLogo.getAttribute("data-playback"), "static");
      await page.screenshot({
        path: path.join(output, `chat-lottie-reply-${reducedMotion}.png`),
      });
      assert.equal(
        await page.locator(".paper-brand-logo").getAttribute("data-playback"),
        "static",
      );
      assert(
        await page.locator('link[rel="icon"][href="/brand/wali.svg"]').count(),
      );
      assert.equal(
        (await context.request.get(`${origin}/brand/wali.svg`)).status(),
        200,
      );
      assert.equal(
        (await context.request.get(`${origin}/brand/wali-180.png`)).status(),
        200,
      );
      const failingRequest = nextChat();
      await input.fill("Retain this draft");
      await input.press("Enter");
      const failure = await failingRequest;
      await waiting.waitFor();
      await failure.fulfill({
        status: 503,
        json: { detail: "Test model unavailable" },
      });
      await page
        .getByRole("alert")
        .filter({ hasText: "Message not completed" })
        .waitFor();
      await waiting.waitFor({ state: "detached" });
      assert.equal(await input.inputValue(), "Retain this draft");
      assert.deepEqual(errors, []);
      results.push(
        `${reducedMotion}: Lottie processing loop, reply logo, header/favicon, preference changes, success/failure cleanup, no runtime errors`,
      );
      console.log(`PASS ${results.at(-1)}`);
      await context.close();
    }
    await fs.writeFile(
      path.join(output, "loading-results.json"),
      JSON.stringify({ results }, null, 2),
    );
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
