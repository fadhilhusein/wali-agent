import assert from "node:assert/strict";
import { test } from "node:test";

import nextConfig from "../next.config.ts";

test("every page refuses to be framed by another website", async () => {
  const rules = await nextConfig.headers?.();
  const everyPage = rules?.find((rule) => rule.source === "/:path*");
  const headers = new Map(
    everyPage?.headers.map(({ key, value }) => [key, value]),
  );

  assert.equal(headers.get("X-Frame-Options"), "DENY");
  assert.match(
    headers.get("Content-Security-Policy") ?? "",
    /frame-ancestors 'none'/,
  );
});

test("every page tells browsers not to guess content types", async () => {
  const rules = await nextConfig.headers?.();
  const everyPage = rules?.find((rule) => rule.source === "/:path*");
  const headers = new Map(
    everyPage?.headers.map(({ key, value }) => [key, value]),
  );

  assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
});

test("the dev server only trusts this computer", () => {
  assert.deepEqual(nextConfig.allowedDevOrigins, ["127.0.0.1"]);
});
