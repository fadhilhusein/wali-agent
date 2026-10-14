"use client";

import Link from "next/link";
import { useWorkspace } from "@/components/workspace-provider";

export function MandatePage() {
  const {
    role,
    busy,
    mandating,
    mandateNotice,
    requests,
    queueState,
    draftMandate,
  } = useWorkspace();
  const mandateCount = requests.filter(
    (request) => request.kind === "mandate",
  ).length;

  return (
    <section
      className="content-page mandate-page"
      aria-labelledby="mandate-title"
    >
      <header className="content-heading">
        <div>
          <span className="page-eyebrow">WALI / RULES</span>
          <h1 id="mandate-title">Business mandate</h1>
          <p>
            Draft spending rules for verified suppliers in this local
            simulation.
          </p>
        </div>
      </header>
      <div className="mandate-content">
        <div className="mandate-step">
          <span className="mandate-step-number">01</span>
          <div>
            <h2>Draft</h2>
            <p>
              Wali creates a request for the owner to review. Drafting does not
              confirm the rules.
            </p>
          </div>
        </div>
        <div className="mandate-step">
          <span className="mandate-step-number">02</span>
          <div>
            <h2>Review in Approvals</h2>
            <p>
              Check the proposed changes and any risk warnings before confirming
              or declining.
            </p>
          </div>
        </div>
        {mandateNotice && (
          <div
            className={`notice notice-${mandateNotice.tone}`}
            role={mandateNotice.tone === "error" ? "alert" : "status"}
          >
            {mandateNotice.text}
          </div>
        )}
        {role === "owner" ? (
          <button
            className="button button-primary mandate-action"
            type="button"
            disabled={busy}
            onClick={() => void draftMandate()}
          >
            {mandating ? "Drafting…" : "Draft mandate"}
          </button>
        ) : (
          <div className="state-panel">
            <strong>Owner action</strong>
            <p>
              Only the owner can draft a mandate. Switch to owner in this local
              simulation to try it.
            </p>
          </div>
        )}
        {mandateNotice?.tone === "success" && (
          <Link className="mandate-review-link" href="/approvals">
            Review the request in Approvals <span aria-hidden="true">↗</span>
          </Link>
        )}
        {queueState === "ready" && mandateCount > 0 && (
          <p className="mandate-pending">
            {mandateCount} mandate {mandateCount === 1 ? "request" : "requests"}{" "}
            currently waiting. <Link href="/approvals">Open Approvals</Link>
          </p>
        )}
      </div>
    </section>
  );
}
