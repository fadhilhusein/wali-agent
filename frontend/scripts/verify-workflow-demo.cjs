const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const origin = process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000";
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const checks = [],
    errors = [],
    calls = [];
  const check = (name) => {
    checks.push(name);
    console.log(`PASS ${name}`);
  };
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    page.setDefaultNavigationTimeout(90_000);
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/wali/**", (route) => {
      calls.push(route.request().url());
      return route.abort();
    });
    await page.goto(origin);
    const demo = page.locator(".wl-demo");
    const clock = () => demo.getAttribute("data-elapsed").then(Number);
    await page.waitForTimeout(400);
    assert.equal(await clock(), 0, "Offscreen demo must not start");
    assert.equal(await demo.locator(".wl-demo-accessible li").count(), 4);
    assert.equal(await demo.locator("[aria-live]").count(), 0);
    await demo.scrollIntoViewIfNeeded();
    const initialBox = await demo.boundingBox();
    await page.waitForFunction(
      () => Number(document.querySelector(".wl-demo").dataset.elapsed) >= 1100,
    );
    assert(await demo.locator(".wl-demo-processing").innerText());
    await demo.getByRole("button", { name: "Pause conversation demo" }).click();
    const stopped = await clock();
    assert.equal(await demo.locator(".lucide-play").count(), 1);
    await page.waitForTimeout(350);
    assert.equal(await clock(), stopped);
    assert.equal(await demo.getAttribute("data-running"), "false");
    await page.keyboard.press("Tab");
    await demo
      .getByRole("button", { name: "Resume conversation demo" })
      .focus();
    assert.equal(
      await demo
        .getByRole("button", { name: "Resume conversation demo" })
        .evaluate((el) => getComputedStyle(el).outlineStyle),
      "solid",
    );
    await page.keyboard.press("Enter");
    assert.equal(await demo.locator(".lucide-pause").count(), 1);
    assert.equal(await demo.locator(".lucide-rotate-ccw").count(), 1);
    for (const icon of await demo.locator(".lucide").all()) {
      assert.equal(await icon.getAttribute("width"), "16");
      assert.equal(await icon.getAttribute("stroke-width"), "1.75");
      assert.equal(await icon.getAttribute("aria-hidden"), "true");
    }
    await page.waitForFunction(
      () => Number(document.querySelector(".wl-demo").dataset.elapsed) >= 3000,
    );
    const partial = await demo.locator(".wl-demo-copy").nth(1).innerText();
    assert(partial.startsWith("Let’s review"));
    assert(
      partial.length <
        "Let’s review due dates and payment details before deciding what to do."
          .length,
    );
    assert(Math.abs((await demo.boundingBox()).height - initialBox.height) < 1);
    await page.screenshot({
      path: path.join(output, "workflow-demo-playing.png"),
    });
    await page.evaluate(() => {
      document.documentElement.style.scrollBehavior = "auto";
      scrollTo(0, 0);
    });
    await page.waitForFunction(
      () => document.querySelector(".wl-demo").dataset.running === "false",
    );
    const offscreen = await clock();
    await page.waitForTimeout(350);
    assert.equal(await clock(), offscreen);
    await demo.scrollIntoViewIfNeeded();
    await page.waitForFunction(
      () => document.querySelector(".wl-demo").dataset.running === "true",
    );
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.waitForFunction(
      () => document.querySelector(".wl-demo").dataset.running === "false",
    );
    const hidden = await clock();
    await page.waitForTimeout(350);
    assert.equal(await clock(), hidden);
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    check(
      "Viewport start, partial text, keyboard pause/resume, stable height, offscreen and hidden-tab pauses",
    );
    await page.waitForFunction(
      () => document.querySelector(".wl-demo").dataset.elapsed === "14000",
      { timeout: 20_000 },
    );
    assert.equal(
      await demo.locator(".wl-demo-copy").nth(3).innerText(),
      "Draft them in Mandate. The Owner reviews the draft before the rules take effect.",
    );
    assert.equal(
      await demo
        .getByRole("button", { name: "Pause conversation demo" })
        .count(),
      0,
    );
    assert(Math.abs((await demo.boundingBox()).height - initialBox.height) < 1);
    await page.waitForTimeout(400);
    assert.equal(await clock(), 14000, "Demo must not loop");
    await demo.getByRole("button", { name: "Replay demo" }).click();
    assert((await clock()) < 1000);
    await demo.getByRole("button", { name: "Pause conversation demo" }).click();
    check(
      "Four complete messages, no automatic loop, replay and no completion layout shift",
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(
      () => !document.querySelector(".wl-demo-controls"),
    );
    assert.equal(
      await demo.locator(".wl-demo-copy").nth(3).innerText(),
      "Draft them in Mandate. The Owner reviews the draft before the rules take effect.",
    );
    const dimensions = [];
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await demo.scrollIntoViewIfNeeded();
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      for (const bubble of await demo.locator(".wl-demo-bubble").all()) {
        const box = await bubble.boundingBox();
        const outer = await demo.boundingBox();
        assert(
          box.x >= outer.x && box.x + box.width <= outer.x + outer.width + 1,
        );
        assert(
          await bubble
            .locator(".wl-demo-text")
            .evaluate((el) => el.scrollHeight <= el.clientHeight + 1),
        );
      }
      dimensions.push({ width, box: await demo.boundingBox() });
      await page.screenshot({
        path: path.join(output, `workflow-demo-${width}.png`),
      });
    }
    const reducedTime = await clock();
    await page.waitForTimeout(300);
    assert.equal(await clock(), reducedTime);
    check(
      "Reduced motion static transcript, no overflow or clipped text at five widths",
    );
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await demo.getByRole("button", { name: "Replay demo" }).click();
    for (const button of await demo.getByRole("button").all()) {
      const box = await button.boundingBox();
      assert(box.height >= 44 && box.width >= 44);
    }
    const nojs = await browser.newPage({
      javaScriptEnabled: false,
      viewport: { width: 390, height: 844 },
    });
    await nojs.route("**/api/wali/**", (route) => {
      calls.push(route.request().url());
      return route.abort();
    });
    await nojs.goto(origin);
    assert.equal(
      await nojs.locator(".wl-demo-copy").nth(3).innerText(),
      "Draft them in Mandate. The Owner reviews the draft before the rules take effect.",
    );
    assert.equal(await nojs.locator(".wl-demo-controls").count(), 0);
    assert.equal(
      await nojs
        .locator(".wl-demo-message")
        .nth(3)
        .evaluate((el) => getComputedStyle(el).opacity),
      "1",
    );
    assert.deepEqual(calls, []);
    assert.deepEqual(errors, []);
    const contrast = await page.evaluate(() => {
      const luminance = (color) => {
        const values = color
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map((v) => {
            const n = Number(v) / 255;
            return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          });
        return values[0] * 0.2126 + values[1] * 0.7152 + values[2] * 0.0722;
      };
      return [
        [
          "User bubble",
          ".wl-demo-user .wl-demo-bubble",
          ".wl-demo-user .wl-demo-bubble",
        ],
        [
          "Assistant bubble",
          ".wl-demo-assistant .wl-demo-bubble",
          ".wl-demo-assistant .wl-demo-bubble",
        ],
        ["Speaker label", ".wl-demo-speaker", ".wl-demo"],
        ["Disclosure", ".wl-demo-footer > span", ".wl-demo"],
        ["Controls", ".wl-demo-controls button", ".wl-demo"],
      ].map(([label, fg, bg]) => {
        const a = luminance(getComputedStyle(document.querySelector(fg)).color);
        const b = luminance(
          getComputedStyle(document.querySelector(bg)).backgroundColor,
        );
        return {
          label,
          ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
        };
      });
    });
    contrast.forEach((item) => assert(item.ratio >= 4.5, JSON.stringify(item)));
    check(
      "44px controls, complete no-JavaScript transcript, no live-region chatter, zero Wali API calls and no runtime errors",
    );
    await fs.writeFile(
      path.join(output, "workflow-demo-results.json"),
      JSON.stringify({ checks, dimensions, contrast, calls, errors }, null, 2),
    );
  } finally {
    await browser.close();
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
