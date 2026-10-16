const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

const origin = process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3005";
const output = path.resolve(__dirname, "../test-results");
const results = [];
const check = (name) => {
  results.push(name);
  console.log(`PASS ${name}`);
};

function contrast(foreground, background) {
  const luminance = (hex) => {
    const channels = hex.match(/[0-9a-f]{2}/gi).map((value) => {
      const channel = parseInt(value, 16) / 255;
      return channel <= 0.04045
        ? channel / 12.92
        : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  };
  const first = luminance(foreground),
    second = luminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

async function main() {
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    permissions: ["clipboard-read", "clipboard-write"],
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let failInfo = false,
    failChat = false,
    failReset = false,
    blockReply = false,
    chatCalls = 0,
    resetCalls = 0;
  let pending = [];
  let nextReply =
    "Here are the records to review:\n\n1. Check the invoice due date.\n2. Reconcile the unmatched transaction.\n3. Review your cash forecast.\n\nNo payment has been made.";
  await context.route("**/api/wali/**", async (route) => {
    const action = new URL(route.request().url()).pathname.split("/").at(-1);
    let status = 200,
      body = {};
    if (action === "info") {
      status = failInfo ? 503 : 200;
      body = failInfo
        ? { detail: "Test service unavailable" }
        : {
            simulation: "Local simulation. No real money or bank connections.",
            roles: ["owner", "bookkeeper", "staff"],
            screening_model: false,
          };
    } else if (action === "pending") body = { requests: pending };
    else if (action === "chat") {
      chatCalls++;
      await new Promise((resolve) => setTimeout(resolve, 180));
      status = failChat ? 503 : 200;
      body = failChat
        ? { detail: "Test chat unavailable" }
        : { reply: nextReply, blocked: blockReply, new_requests: [] };
    } else if (action === "reset") {
      resetCalls++;
      status = failReset ? 503 : 200;
      body = failReset
        ? { detail: "Test reset unavailable" }
        : { status: "reset" };
    } else if (action === "mandate") {
      pending = [
        {
          kind: "mandate",
          subject_id: "test-request",
          required_role: "owner",
          requested_by: "owner",
          expires_at: "2026-10-16T00:00:00Z",
          summary: null,
          changes: ["Test spending rule"],
          risk_warnings: [],
        },
      ];
      body = {
        status: "pending",
        message: "Test mandate is ready for review.",
      };
    } else if (action === "confirm" || action === "cancel") {
      pending = [];
      body = { status: "complete", message: "Test decision recorded." };
    } else throw new Error(`Unexpected API action: ${action}`);
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });

  try {
    await page.goto(`${origin}/chat`);
    await page
      .getByRole("heading", { name: /How can I help you today\?/ })
      .waitFor();
    assert.equal(await page.locator(".paper-prompt").count(), 4);
    assert.equal(
      await page.locator(".paper-sidebar").evaluate((el) => el.offsetWidth),
      280,
    );
    assert.equal(
      await page.locator(".paper-composer").evaluate((el) => el.offsetWidth),
      760,
    );
    await page.screenshot({ path: path.join(output, "chat-home-desktop.png") });
    check("desktop reference dimensions and four finance prompts");
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        `overflow at ${width}`,
      );
      const composer = await page.locator(".paper-composer").boundingBox();
      assert(
        composer.x >= 0 &&
          composer.x + composer.width <= width &&
          composer.y + composer.height <= 900,
      );
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "chat-home-mobile.png"),
        });
    }
    check("home reflow at 1440, 1024, 768, 390 and 320 CSS pixels");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await page.waitForFunction(
      () => document.querySelector(".paper-sidebar").offsetWidth === 64,
    );
    assert.equal(
      await page.locator(".paper-sidebar").evaluate((el) => el.offsetWidth),
      64,
    );
    await page.getByRole("button", { name: "Toggle sidebar" }).click();
    await page.waitForFunction(
      () => document.querySelector(".paper-sidebar").offsetWidth === 280,
    );
    assert.equal(
      await page.locator(".paper-sidebar").evaluate((el) => el.offsetWidth),
      280,
    );
    check("desktop sidebar collapse and expand");
    const keyboardPrompt = page.locator(".paper-prompt").first();
    await keyboardPrompt.focus();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Shift+Tab");
    assert(
      await keyboardPrompt.evaluate(
        (el) => getComputedStyle(el).outlineStyle === "solid",
      ),
    );
    await keyboardPrompt.press("Space");
    assert(
      await page
        .locator("#message-input")
        .evaluate((el) => el === document.activeElement),
    );
    const contrastPairs = [
      ["1f1f1f", "ffffff", 4.5],
      ["ffffff", "886e89", 4.5],
      ["666b70", "ffffff", 4.5],
      ["505762", "f0f4f9", 4.5],
      ["632268", "ecdcef", 4.5],
      ["ffffff", "7c2f81", 4.5],
      ["7c2f81", "f8f3f9", 4.5],
      ["68546d", "f8f3f9", 4.5],
      ["59415f", "f8f3f9", 4.5],
      ["632268", "ead9ed", 4.5],
      ["ffffff", "59616c", 4.5],
      ["444746", "f0f4f9", 4.5],
      ["345337", "ffffff", 4.5],
      ["744018", "fff7ec", 4.5],
      ["803633", "fff5f4", 4.5],
      ["26543d", "f0faf4", 4.5],
      ["4675d1", "ffffff", 3],
      ["6650c9", "ffffff", 3],
      ["4d76ac", "ffffff", 3],
    ];
    for (const [fg, bg, minimum] of contrastPairs)
      assert(contrast(fg, bg) >= minimum, `contrast ${fg}/${bg}`);
    check(
      `keyboard prompt activation, visible focus and ${contrastPairs.length} text contrast pairings`,
    );
    for (let i = 0; i < 4; i++) {
      await page.locator(".paper-prompt").nth(i).click();
      assert(await page.locator("#message-input").inputValue());
      assert(
        await page
          .locator("#message-input")
          .evaluate((el) => el === document.activeElement),
      );
    }
    const input = page.getByRole("textbox", { name: "Message Wali" });
    await input.fill("Review invoices");
    await input.press("Shift+Enter");
    assert.equal(await input.inputValue(), "Review invoices\n");
    await input.press("Enter");
    await page.getByText("Thinking through your request…").waitFor();
    assert(
      await page
        .getByRole("button", { name: "Sending message", exact: true })
        .isDisabled(),
    );
    await page.locator(".paper-reply").waitFor();
    assert.equal(chatCalls, 1);
    assert.equal(await input.inputValue(), "");
    await page.screenshot({
      path: path.join(output, "chat-conversation-desktop.png"),
    });
    check(
      "all prompts focus input, Shift+Enter, Enter, loading and single API submission",
    );
    assert.equal(
      await page.getByRole("button", { name: /coming soon/i }).count(),
      7,
    );
    for (const control of await page
      .getByRole("button", { name: /coming soon/i })
      .all())
      assert(await control.isDisabled());
    await page.getByRole("button", { name: "Copy reply", exact: true }).click();
    await page.getByText("Copied to clipboard").waitFor();
    assert.equal(
      (await page.evaluate(() => navigator.clipboard.readText())).replace(
        /\r\n/g,
        "\n",
      ),
      nextReply,
    );
    await page.evaluate(() => {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async () => {
            throw new Error("Denied");
          },
        },
      });
    });
    await page.getByRole("button", { name: "Copy reply", exact: true }).click();
    await page.getByText(/Could not copy/).waitFor();
    check(
      "future controls disabled; copy success and clipboard failure feedback",
    );
    await page.getByRole("link", { name: "Approvals", exact: true }).click();
    await page
      .getByRole("heading", { name: "Approvals", exact: true })
      .waitFor();
    await page.getByRole("link", { name: "Chat", exact: true }).click();
    await page.locator(".paper-message").first().waitFor();
    assert.equal(await page.locator(".paper-message").count(), 2);
    failReset = true;
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Could not reset" })
      .waitFor();
    assert.equal(await page.locator(".paper-message").count(), 2);
    failReset = false;
    await page.getByRole("button", { name: "New chat", exact: true }).click();
    await page.locator(".paper-welcome").waitFor();
    assert.equal(resetCalls, 2);
    check(
      "navigation retains transcript; reset failure preserves messages and success clears them",
    );
    failChat = true;
    await input.fill("Keep my draft");
    await page
      .getByRole("button", { name: "Send message", exact: true })
      .click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Message not completed" })
      .waitFor();
    assert.equal(await input.inputValue(), "Keep my draft");
    assert.equal(await page.locator(".paper-message").count(), 0);
    failChat = false;
    blockReply = true;
    await input.press("Enter");
    await page.getByText("Reply blocked for safety").waitFor();
    check("chat failure restores draft and blocked replies are labeled");
    blockReply = false;
    await page
      .getByRole("button", { name: "Settings and help", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Acting as" })
      .selectOption("staff");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".paper-message").count(), 0);
    assert(
      await page
        .getByRole("button", { name: "Settings and help", exact: true })
        .evaluate((el) => el === document.activeElement),
    );
    await page.getByRole("link", { name: "Mandate", exact: true }).click();
    await page
      .getByText("Only the owner can draft a mandate.", { exact: false })
      .waitFor();
    await page
      .getByRole("button", { name: "Settings, acting as staff", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Acting as" })
      .selectOption("owner");
    await page
      .getByRole("button", { name: "Close settings", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .click();
    await page
      .getByRole("link", { name: /Review the request in Approvals/ })
      .click();
    await page.getByRole("button", { name: "Confirm", exact: true }).click();
    await page.getByText("Test decision recorded.").waitFor();
    await page.getByRole("link", { name: "Mandate", exact: true }).click();
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .click();
    await page
      .getByRole("link", { name: /Review the request in Approvals/ })
      .click();
    await page.getByRole("button", { name: "Decline", exact: true }).click();
    await page.getByText("Test decision recorded.").waitFor();
    check(
      "settings focus restoration, role clearing, owner-only mandate, confirm and decline",
    );
    await page.getByRole("link", { name: "Chat", exact: true }).click();
    await page.setViewportSize({ width: 390, height: 700 });
    await page.locator(".paper-welcome").waitFor();
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await page.locator(".paper-sidebar-open").waitFor();
    await page.waitForFunction(
      () =>
        document.activeElement?.getAttribute("aria-label") ===
        "Close navigation",
    );
    assert(
      await page
        .getByRole("button", { name: "Close navigation", exact: true })
        .evaluate((el) => el === document.activeElement),
    );
    await page.keyboard.press("Shift+Tab");
    assert(
      await page
        .getByRole("button", { name: "Settings and help", exact: true })
        .evaluate((el) => el === document.activeElement),
    );
    await page
      .getByRole("button", { name: "Settings and help", exact: true })
      .click();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator(".paper-sidebar-open").count(), 0);
    assert(
      await page
        .locator(".paper-avatar")
        .evaluate((el) => el === document.activeElement),
    );
    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await page.waitForFunction(
      () =>
        document.activeElement?.getAttribute("aria-label") ===
        "Close navigation",
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () =>
        document.activeElement?.getAttribute("aria-label") ===
        "Open navigation menu",
    );
    assert(
      await page
        .getByRole("button", { name: "Open navigation menu" })
        .evaluate((el) => el === document.activeElement),
    );
    await page.getByRole("button", { name: "Open navigation menu" }).click();
    await page.getByRole("link", { name: "Chat", exact: true }).click();
    check(
      "mobile drawer focus trap, profile shortcut, Escape, restore focus and navigation",
    );
    await page.setViewportSize({ width: 320, height: 400 });
    await input.focus();
    const bounds = await input.boundingBox();
    assert(bounds.y >= 0 && bounds.y + bounds.height <= 400);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    );
    check(
      "320 CSS pixel zoom budget and input visible in a 400px-tall viewport",
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    nextReply = Array.from(
      { length: 90 },
      (_, i) =>
        `Review item ${i + 1}: confirm the ledger entry before taking action.`,
    ).join("\n");
    await input.fill("Long reply");
    await input.press("Enter");
    await page.locator(".paper-reply").waitFor();
    const scroller = page.locator(".paper-chat-scroll");
    assert(
      await scroller.evaluate(
        (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 5,
      ),
    );
    await input.fill("Next reply");
    await input.press("Enter");
    await scroller.evaluate((el) => {
      el.scrollTop = 0;
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForFunction(
      () => document.querySelectorAll(".paper-reply").length === 2,
    );
    assert.equal(await scroller.evaluate((el) => el.scrollTop), 0);
    await page.setViewportSize({ width: 390, height: 700 });
    await page.screenshot({
      path: path.join(output, "chat-conversation-mobile.png"),
    });
    check(
      "long replies stay contained, follow new messages near bottom, preserve manual scroll",
    );
    failInfo = true;
    await page.reload();
    await page.getByRole("heading", { name: "Unable to connect" }).waitFor();
    assert(await input.isDisabled());
    failInfo = false;
    await page.getByRole("button", { name: "Retry connection" }).click();
    await page.locator(".paper-welcome").waitFor();
    check("connection failure and retry");
    assert.deepEqual(errors, []);
    check("no browser runtime errors");
    await fs.writeFile(
      path.join(output, "results.json"),
      JSON.stringify(
        {
          results,
          errors,
          chatCalls,
          resetCalls,
          contrast: contrastPairs.map(([foreground, background, minimum]) => ({
            foreground,
            background,
            minimum,
            ratio: Number(contrast(foreground, background).toFixed(2)),
          })),
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
