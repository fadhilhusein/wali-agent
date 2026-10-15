const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");

const fixtures = [
  {
    kind: "payment",
    subject_id: "test-payment",
    required_role: "owner",
    requested_by: "bookkeeper",
    expires_at: "2026-10-16T09:00:00Z",
    summary: {
      supplier_name: "Test supplier",
      invoice_number: "TEST-INV-042",
      due_date: "2026-10-20",
      amount: "2901000",
      currency: "IDR",
      registered_account:
        "test-account-with-a-deliberately-long-reference-12345678901234567890",
      balance_after: "18000000",
    },
    changes: [],
    risk_warnings: [
      { message: "Test invoice details need review before payment." },
    ],
  },
  {
    kind: "mandate",
    subject_id: "test-mandate",
    required_role: "owner",
    requested_by: "owner",
    expires_at: "2026-10-16T09:00:00Z",
    summary: null,
    changes: [
      "Test spending rule for verified suppliers",
      "Test owner review requirement",
    ],
    risk_warnings: [],
  },
];

async function main() {
  const origin = process.env.WALI_TEST_ORIGIN || "http://127.0.0.1:3000";
  const output = path.resolve(__dirname, "../test-results");
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  try {
    const page = await browser.newPage({
      reducedMotion: "reduce",
      viewport: { width: 1440, height: 900 },
    });
    const errors = [];
    const calls = [];
    const contrastChecks = [];
    async function checkContrast(
      label,
      selector,
      backgroundSelector,
      property = "color",
      minimum = 4.5,
    ) {
      const colors = await page
        .locator(selector)
        .first()
        .evaluate(
          (el, { backgroundSelector, property }) => ({
            foreground: getComputedStyle(el)[property],
            background: getComputedStyle(
              document.querySelector(backgroundSelector),
            ).backgroundColor,
          }),
          { backgroundSelector, property },
        );
      const luminance = (rgb) => {
        const channels = rgb
          .match(/[\d.]+/g)
          .slice(0, 3)
          .map((value) => {
            const channel = Number(value) / 255;
            return channel <= 0.04045
              ? channel / 12.92
              : ((channel + 0.055) / 1.055) ** 2.4;
          });
        return (
          channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
        );
      };
      const first = luminance(colors.foreground),
        second = luminance(colors.background);
      const ratio =
        (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
      assert(ratio >= minimum, `${label} contrast ${ratio}`);
      contrastChecks.push({
        label,
        ...colors,
        ratio: Number(ratio.toFixed(2)),
        minimum,
      });
    }
    page.on("pageerror", (error) => errors.push(error.message));
    let requests = structuredClone(fixtures),
      failPending = false,
      failInfo = false,
      failDecision = false,
      failMandate = false;
    let releaseDecision, releaseDraft;
    await page.route("**/api/wali/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const action = url.pathname.split("/").at(-1);
      calls.push(action);
      let status = 200,
        body = {};
      if (action === "info") {
        status = failInfo ? 503 : 200;
        body = failInfo
          ? { detail: "Test connection unavailable" }
          : {
              roles: ["owner", "bookkeeper", "staff"],
              simulation: "Test simulation",
              screening_model: false,
            };
      } else if (action === "pending") {
        status = failPending ? 503 : 200;
        body = failPending
          ? { detail: "Test queue unavailable" }
          : {
              requests: requests.filter(
                (item) => item.required_role === url.searchParams.get("role"),
              ),
            };
      } else if (action === "confirm" || action === "cancel") {
        if (releaseDecision)
          await new Promise((resolve) => {
            releaseDecision.resolve = resolve;
          });
        status = failDecision ? 503 : 200;
        if (!failDecision)
          requests = requests.filter(
            (item) => item.subject_id !== request.postDataJSON().subject_id,
          );
        body = failDecision
          ? { detail: "Test decision unavailable" }
          : { status: "complete", message: "Test decision recorded." };
      } else if (action === "mandate") {
        if (releaseDraft)
          await new Promise((resolve) => {
            releaseDraft.resolve = resolve;
          });
        status = failMandate ? 503 : 200;
        if (!failMandate) requests = [structuredClone(fixtures[1])];
        body = failMandate
          ? { detail: "Test drafting unavailable" }
          : { status: "pending", message: "Test mandate ready for review." };
      } else throw new Error(`Unexpected action: ${action}`);
      await route.fulfill({ status, json: body });
    });
    await page.goto(`${origin}/approvals`);
    await page
      .getByRole("heading", { name: "Test supplier", exact: true })
      .waitFor();
    assert.equal(await page.locator(".paper-request").count(), 2);
    for (const [label, selector, background, property, minimum] of [
      ["heading", ".paper-finance-heading h1", "body"],
      ["secondary text", ".paper-finance-heading > p", "body"],
      ["amount", ".paper-request-amount p", ".paper-request-amount"],
      ["risk warning", ".paper-request-risk h3", ".paper-request-risk"],
      ["pending pill", ".paper-finance-pill", ".paper-finance-pill"],
      ["confirm", ".paper-action-primary", ".paper-action-primary"],
      ["decline", ".paper-action-decline", ".paper-action-decline"],
      [
        "decline boundary",
        ".paper-action-decline",
        "body",
        "borderTopColor",
        3,
      ],
    ])
      await checkContrast(label, selector, background, property, minimum);
    assert(await page.getByText("2,901,000 IDR", { exact: true }).isVisible());
    assert(
      await page.getByText("Registered account", { exact: true }).isVisible(),
    );
    await page.screenshot({ path: path.join(output, "approvals-desktop.png") });
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
      );
      assert(
        await page
          .locator(".paper-content")
          .evaluate((el) => el.scrollWidth <= el.clientWidth),
      );
      for (const action of await page
        .locator(".paper-request-actions button")
        .all()) {
        const bounds = await action.boundingBox();
        assert(
          bounds.width >= 44 &&
            bounds.height >= 44 &&
            bounds.x + bounds.width <= width,
        );
      }
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "approvals-mobile.png"),
        });
    }
    console.log(
      "PASS payment and mandate details, warnings, five responsive widths and action targets",
    );
    failDecision = true;
    await page
      .locator(".paper-request")
      .first()
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Confirm failed" })
      .waitFor();
    assert.equal(await page.locator(".paper-request").count(), 2);
    failDecision = false;
    releaseDecision = {};
    await page
      .locator(".paper-request")
      .first()
      .getByRole("button", { name: "Confirm", exact: true })
      .click();
    await page.getByRole("button", { name: "Processing…" }).first().waitFor();
    for (const button of await page
      .locator(".paper-request-actions button")
      .all())
      assert(await button.isDisabled());
    releaseDecision.resolve();
    releaseDecision = null;
    await page
      .getByRole("status")
      .filter({ hasText: "Test decision recorded." })
      .waitFor();
    await page.waitForFunction(
      () => document.querySelectorAll(".paper-request").length === 1,
    );
    await page.getByRole("button", { name: "Decline", exact: true }).click();
    await page.getByRole("heading", { name: "Nothing waiting" }).waitFor();
    await page.screenshot({ path: path.join(output, "approvals-empty.png") });
    await page.getByRole("link", { name: "Go to chat", exact: true }).click();
    await page.locator(".paper-welcome").waitFor();
    console.log(
      "PASS failed confirmation retains requests, processing disables decisions, confirm/decline and empty-state chat link",
    );
    failPending = true;
    await page.goto(`${origin}/approvals`);
    await page
      .getByRole("alert")
      .filter({ hasText: "Test queue unavailable" })
      .waitFor();
    failPending = false;
    await page
      .getByRole("button", { name: "Retry approvals", exact: true })
      .click();
    await page.getByRole("heading", { name: "Nothing waiting" }).waitFor();
    await page.goto(`${origin}/mandate`);
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .waitFor();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: path.join(output, "mandate-desktop.png") });
    for (const width of [1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      assert(
        await page
          .locator(".paper-content")
          .evaluate((el) => el.scrollWidth <= el.clientWidth),
      );
      if (width === 390)
        await page.screenshot({
          path: path.join(output, "mandate-mobile.png"),
        });
    }
    failMandate = true;
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .press("Space");
    await page
      .getByRole("alert")
      .filter({ hasText: "Mandate draft failed" })
      .waitFor();
    failMandate = false;
    releaseDraft = {};
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .click();
    await page.getByRole("button", { name: "Drafting…" }).waitFor();
    assert(await page.getByRole("button", { name: "Drafting…" }).isDisabled());
    releaseDraft.resolve();
    releaseDraft = null;
    await page
      .getByRole("link", { name: /Review the request in Approvals/ })
      .waitFor();
    await checkContrast(
      "secondary action",
      ".paper-mandate-review",
      ".paper-mandate-review",
    );
    await checkContrast(
      "secondary boundary",
      ".paper-mandate-review",
      "body",
      "borderTopColor",
      3,
    );
    await checkContrast(
      "step number",
      ".paper-mandate-step-number",
      ".paper-mandate-step-number",
    );
    await checkContrast(
      "panel copy",
      ".paper-mandate-flow > p",
      ".paper-mandate-flow",
    );
    await page
      .getByRole("link", { name: /Review the request in Approvals/ })
      .click();
    await page
      .getByRole("heading", { name: "Business mandate", exact: true })
      .waitFor();
    console.log(
      "PASS approvals retry, mandate responsive layouts, draft failure/processing/success and review navigation",
    );
    await page.goto(`${origin}/mandate`);
    await page
      .getByRole("button", { name: "Settings, acting as owner", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Acting as" })
      .selectOption("staff");
    await page
      .getByRole("button", { name: "Close settings", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "Owner action", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "Draft mandate", exact: true })
        .count(),
      0,
    );
    await page.screenshot({ path: path.join(output, "mandate-staff.png") });
    failInfo = true;
    await page.reload();
    await page
      .getByRole("heading", { name: "Mandate unavailable", exact: true })
      .waitFor();
    assert.equal(
      await page
        .getByRole("heading", { name: "Owner action", exact: true })
        .count(),
      0,
    );
    failInfo = false;
    await page
      .getByRole("button", { name: "Retry connection", exact: true })
      .click();
    await page
      .getByRole("button", { name: "Draft mandate", exact: true })
      .waitFor();
    console.log(
      "PASS non-owner guidance, missing connection state and retry without misleading role restriction",
    );
    failPending = true;
    await page.goto(`${origin}/mandate`);
    await page
      .getByRole("alert")
      .filter({ hasText: "Test queue unavailable" })
      .waitFor();
    failPending = false;
    await page
      .getByRole("button", { name: "Retry approvals", exact: true })
      .click();
    await page
      .getByRole("link", { name: "Open Approvals", exact: true })
      .waitFor();
    await page
      .getByRole("link", { name: "Open Approvals", exact: true })
      .click();
    await page.waitForURL("**/approvals");
    await page
      .getByRole("heading", { name: "Approvals", exact: true })
      .waitFor();
    await page
      .getByRole("heading", { name: "Business mandate", exact: true })
      .waitFor();
    failInfo = true;
    await page.reload();
    await page
      .getByRole("alert")
      .filter({ hasText: "Test connection unavailable" })
      .waitFor();
    failInfo = false;
    await page
      .getByRole("button", { name: "Retry connection", exact: true })
      .click();
    await page.locator(".paper-request").waitFor();
    console.log(
      "PASS mandate queue retry, pending-request navigation and approvals connection retry",
    );
    assert.deepEqual(errors, []);
    assert(!calls.includes("chat"));
    await fs.writeFile(
      path.join(output, "finance-results.json"),
      JSON.stringify(
        { result: "pass", calls, errors, contrastChecks },
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
