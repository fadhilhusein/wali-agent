// The API answers 200 for a decision that was denied or failed too, so the notice colour comes
// from the status it reports, not from the request having gone through.
export function decisionTone(
  status: string,
  expected: readonly string[],
): "success" | "error" {
  return expected.includes(status) ? "success" : "error";
}
