import assert from "node:assert/strict";
import { test } from "node:test";

import { decisionTone } from "./decision-tone.ts";

test("a payment that ran, a decline and an active mandate are shown as success", () => {
  for (const status of ["executed", "declined", "active"]) {
    assert.equal(
      decisionTone(status, ["executed", "declined", "active"]),
      "success",
    );
  }
});

test("a denied, failed or unconfirmed decision is shown as an error", () => {
  for (const status of ["denied", "failed", "needs_confirmation"]) {
    assert.equal(
      decisionTone(status, ["executed", "declined", "active"]),
      "error",
    );
  }
});

test("a mandate draft waiting for the owner is the expected outcome", () => {
  assert.equal(
    decisionTone("needs_confirmation", ["needs_confirmation"]),
    "success",
  );
  assert.equal(decisionTone("denied", ["needs_confirmation"]), "error");
});
