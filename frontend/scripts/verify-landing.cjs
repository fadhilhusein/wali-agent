const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

async function main() {
  const origin = process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000";
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const checks = [];
  const check = (name) => {
    checks.push(name);
    console.log(`PASS ${name}`);
  };
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 900 },
    });
    page.setDefaultNavigationTimeout(120_000);
    const errors = [],
      calls = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/wali/**", (route) => {
      const action = new URL(route.request().url()).pathname.split("/").at(-1);
      calls.push(action);
      assert(["info", "pending"].includes(action), `Unexpected API ${action}`);
      return route.fulfill({
        json:
          action === "info"
            ? {
                roles: ["owner", "bookkeeper", "staff"],
                simulation: "Test simulation",
                screening_model: false,
              }
            : { requests: [] },
      });
    });
    const response = await page.goto(origin);
    assert.equal(response.status(), 200);
    assert.equal(new URL(page.url()).pathname, "/");
    assert.match(
      await page.locator("h1").innerText(),
      /Clearer finances\.\s*One conversation\./,
    );
    assert.equal(await page.locator(".paper-shell").count(), 0);
    assert.match(await page.title(), /Wali \| Clearer finances/);
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh")?.paperShaderMount?.speed > 0,
    );
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh")?.paperShaderMount?.speed === 0,
    );
    const panel = page.locator(".wl-hero-visual");
    await panel.hover();
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh").paperShaderMount.speed > 0,
    );
    const frame = await page
      .locator(".wl-mesh")
      .evaluate((el) => el.paperShaderMount.currentFrame);
    await page.waitForFunction(
      (frame) =>
        document.querySelector(".wl-mesh").paperShaderMount.currentFrame >
        frame,
      frame,
    );
    await page.mouse.move(0, 0);
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh").paperShaderMount.speed === 0,
    );
    await panel.getByRole("link", { name: "Open chat" }).focus();
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh").paperShaderMount.speed > 0,
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(
      () => document.querySelector(".wl-mesh").paperShaderMount.speed === 0,
    );
    await page.locator("h1").click();
    check(
      "Mesh intro, pause, hover, focus, actual frame progression and reduced motion",
    );
    const links = await page
      .locator(".wl-landing a")
      .evaluateAll((els) => els.map((el) => el.getAttribute("href")));
    assert(
      links.every(
        (href) => href === "/" || href === "/chat" || documentAnchor(href),
      ),
    );
    for (const href of new Set(links.filter((href) => href.startsWith("#"))))
      assert.equal(await page.locator(href).count(), 1, href);
    for (const link of await page
      .locator(
        '.wl-desktop-nav a, .wl-hero-actions a[href^="#"], .wl-footer nav a[href^="#"]',
      )
      .all()) {
      const href = await link.getAttribute("href");
      await link.click();
      assert.equal(new URL(page.url()).hash, href);
    }
    for (const logo of await page.locator(".wl-brand").all()) {
      await logo.click();
      await page.waitForURL((url) => url.pathname === "/" && url.hash === "");
      assert.equal(new URL(page.url()).pathname, "/");
      assert.equal(new URL(page.url()).hash, "");
    }
    await page.keyboard.press("Tab");
    await page.locator(".wl-hero-actions a").first().focus();
    assert.equal(
      await page
        .locator(".wl-hero-actions a")
        .first()
        .evaluate((el) => getComputedStyle(el).outlineStyle),
      "solid",
    );
    assert(await page.evaluate(() => document.fonts.check("500 32px Poppins")));
    const contrast = await page.evaluate(() => {
      const luminance = (color) => {
        const c = color
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map((v) => {
            const n = Number(v) / 255;
            return n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
          });
        return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722;
      };
      return [
        ["Hero", ".wl-hero h1", ".wl-landing", "color", 4.5],
        ["Secondary text", ".wl-hero-description", ".wl-landing", "color", 4.5],
        [
          "Primary button",
          ".wl-button-primary",
          ".wl-button-primary",
          "color",
          4.5,
        ],
        [
          "Secondary boundary",
          ".wl-button-secondary",
          ".wl-landing",
          "borderTopColor",
          3,
        ],
        ["Preview", ".wl-preview-card p", ".wl-preview-card", "color", 4.5],
        [
          "Simulation",
          ".wl-simulation p",
          ".wl-simulation-inner",
          "color",
          4.5,
        ],
      ].map(([label, fg, bg, property, minimum]) => {
        const a = luminance(
          getComputedStyle(document.querySelector(fg))[property],
        );
        const b = luminance(
          getComputedStyle(document.querySelector(bg)).backgroundColor,
        );
        return {
          label,
          ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05),
          minimum,
        };
      });
    });
    contrast.forEach((item) =>
      assert(item.ratio >= item.minimum, JSON.stringify(item)),
    );
    check(
      "Real destinations, section anchors, metadata and six computed contrast pairs",
    );
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(() => scrollTo(0, 0));
      await page.waitForFunction(
        () => document.documentElement.scrollWidth <= innerWidth,
      );
      const canvas = await page
        .locator(".wl-mesh canvas")
        .evaluate((el) => el.width * el.height);
      assert(
        canvas <= (width <= 760 ? 240_000 : 480_000) + 2000,
        `Pixel budget ${width}: ${canvas}`,
      );
      for (const button of await page
        .locator(".wl-button:visible, .wl-mobile-menu summary:visible")
        .all()) {
        const box = await button.boundingBox();
        assert(box.height >= 44 && box.width >= 44);
      }
      await page.screenshot({
        path: path.join(output, `landing-${width}.png`),
        fullPage: true,
      });
      await page.evaluate(() => scrollTo(0, 600));
      assert.equal(
        Math.round((await page.locator(".wl-header").boundingBox()).y),
        0,
      );
      check(
        `Responsive bounds, touch targets, sticky header and screenshot at ${width}px`,
      );
    }
    const menu = page.locator(".wl-mobile-menu");
    const trigger = menu.locator("summary");
    await trigger.click();
    assert(await menu.evaluate((el) => el.open));
    await page.keyboard.press("Tab");
    assert.equal(
      await page.evaluate(() => document.activeElement.textContent),
      "Capabilities",
    );
    await page.keyboard.press("Escape");
    assert(!(await menu.evaluate((el) => el.open)));
    assert(await trigger.evaluate((el) => el === document.activeElement));
    await page.keyboard.press("Enter");
    await menu.getByRole("link", { name: "Simulation", exact: true }).click();
    assert.equal(new URL(page.url()).hash, "#simulation");
    assert(!(await menu.evaluate((el) => el.open)));
    assert(await trigger.evaluate((el) => el === document.activeElement));
    await trigger.click();
    await page.locator("#simulation h2").click();
    assert(!(await menu.evaluate((el) => el.open)));
    await page.goto(origin);
    await page.keyboard.press("Tab");
    assert.equal(
      await page.evaluate(() => document.activeElement.textContent.trim()),
      "Skip to content",
    );
    await page.keyboard.press("Enter");
    assert(
      await page
        .locator("main")
        .evaluate((el) => el === document.activeElement),
    );
    assert.equal(calls.length, 0, "Landing must never request Wali API");
    check(
      "Mobile menu keyboard, Escape, focus return, selection, outside dismissal and skip link; zero Wali calls",
    );
    for (const cta of [
      ".wl-header-actions > a",
      ".wl-hero-actions > a:first-child",
      ".wl-preview-card a",
      ".wl-simulation a",
      ".wl-footer nav a:last-child",
    ]) {
      await page.goto(origin);
      await page.locator(cta).click();
      await page.waitForURL("**/chat");
      await page.locator("#message-input").waitFor();
    }
    for (const route of ["/approvals", "/mandate"]) {
      await page.goto(`${origin}${route}`);
      await page.locator(".paper-shell").waitFor();
      assert.equal(new URL(page.url()).pathname, route);
    }
    check("All five Chat CTAs and direct workspace routes with API mocks");
    const fallback = await browser.newPage({
      viewport: { width: 390, height: 844 },
      reducedMotion: "reduce",
    });
    await fallback.addInitScript(() => {
      const getContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (type, ...args) {
        return type === "webgl2" ? null : getContext.call(this, type, ...args);
      };
    });
    await fallback.goto(origin);
    await fallback.getByRole("heading", { level: 1 }).waitFor();
    assert.equal(await fallback.locator(".wl-mesh").count(), 0);
    assert.notEqual(
      await fallback
        .locator(".wl-mesh-layer")
        .evaluate((el) => getComputedStyle(el).backgroundImage),
      "none",
    );
    await fallback.screenshot({
      path: path.join(output, "landing-no-webgl.png"),
      fullPage: true,
    });
    const nojs = await browser.newPage({
      javaScriptEnabled: false,
      viewport: { width: 390, height: 844 },
    });
    await nojs.goto(origin);
    assert(await nojs.locator("h1").isVisible());
    await nojs.locator("summary").click();
    assert(
      await nojs
        .getByRole("navigation", { name: "Mobile navigation" })
        .getByText("Capabilities")
        .isVisible(),
    );
    await nojs.locator(".wl-hero-actions > a:first-child").click();
    assert.equal(new URL(nojs.url()).pathname, "/chat");
    check(
      "CSS fallback without WebGL; SSR content, native menu and Chat navigation without JavaScript",
    );
    assert.deepEqual(errors, []);
    await fs.writeFile(
      path.join(output, "landing-results.json"),
      JSON.stringify(
        { checks, contrast, errors, mockedWorkspaceCalls: calls },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}
function documentAnchor(href) {
  return href?.startsWith("#");
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
