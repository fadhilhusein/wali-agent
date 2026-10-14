"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useRef } from "react";
import { useWorkspace } from "@/components/workspace-provider";
import type { PendingRequest } from "@/lib/wali-api";

function formatAmount(value: string | number, currency: string): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return `${value} ${currency}`;
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(numeric)} ${currency}`;
}

function formatExpiry(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `Expires ${new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(date)}`;
}

export function ApprovalsPage() {
  const reduceMotion = useReducedMotion();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const {
    role,
    infoError,
    requests,
    queueState,
    queueError,
    queueNotice,
    processingId,
    busy,
    retryPending,
    decide,
  } = useWorkspace();

  async function takeDecision(
    request: PendingRequest,
    action: "confirm" | "cancel",
  ) {
    await decide(request, action);
    headingRef.current?.focus();
  }

  return (
    <section
      className="content-page approvals-page"
      aria-labelledby="approvals-title"
    >
      <header className="content-heading">
        <div>
          <span className="page-eyebrow">WALI / DECISIONS</span>
          <h1 id="approvals-title" ref={headingRef} tabIndex={-1}>
            Approvals
          </h1>
          <p>
            Requests waiting for your role. Check the details before making a
            decision.
          </p>
        </div>
        <span
          className="heading-count"
          aria-label={`${requests.length} pending requests`}
        >
          {queueState === "ready" ? requests.length : "·"}
        </span>
      </header>
      {queueNotice && (
        <div
          className={`notice notice-${queueNotice.tone}`}
          role={queueNotice.tone === "error" ? "alert" : "status"}
        >
          {queueNotice.text}
        </div>
      )}
      {infoError && (
        <div className="state-panel" role="alert">
          <strong>Approvals unavailable</strong>
          <p>Connect to Wali to see requests for this role.</p>
        </div>
      )}
      {!infoError && queueState === "loading" && (
        <div className="state-panel" role="status">
          <strong>Loading approvals</strong>
          <p>Checking what is waiting for {role || "you"}.</p>
        </div>
      )}
      {!infoError && queueState === "error" && (
        <div className="state-panel" role="alert">
          <strong>Approvals unavailable</strong>
          <p>{queueError}</p>
          <button
            className="button"
            type="button"
            onClick={() => void retryPending()}
          >
            Retry approvals
          </button>
        </div>
      )}
      {!infoError && queueState === "ready" && requests.length === 0 && (
        <div className="state-panel empty-queue">
          <strong>Nothing waiting</strong>
          <p>
            There are no requests for {role || "this role"} right now. New
            approvals will appear here.
          </p>
        </div>
      )}
      {!infoError && queueState === "ready" && requests.length > 0 && (
        <ul className="queue-list">
          <AnimatePresence initial={false}>
            {requests.map((request) => (
              <motion.li
                key={request.subject_id}
                initial={reduceMotion ? false : { opacity: 0, y: 7 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -5 }}
                transition={{ duration: 0.18 }}
              >
                <article className="request-card">
                  <div className="request-top">
                    <span className="request-kind">{request.kind}</span>
                    <span className="request-expiry">
                      {formatExpiry(request.expires_at)}
                    </span>
                  </div>
                  <h2 className="request-title">
                    {request.summary?.supplier_name ??
                      (request.kind === "mandate"
                        ? "Business mandate"
                        : "Approval request")}
                  </h2>
                  <p className="request-by">
                    Requested by {request.requested_by} · For{" "}
                    {request.required_role}
                  </p>
                  {request.summary && (
                    <>
                      <p className="request-amount">
                        {formatAmount(
                          request.summary.amount,
                          request.summary.currency,
                        )}
                      </p>
                      <dl className="request-details">
                        <dt>Invoice</dt>
                        <dd>{request.summary.invoice_number}</dd>
                        <dt>Due</dt>
                        <dd>{request.summary.due_date}</dd>
                        <dt>Registered account</dt>
                        <dd>{request.summary.registered_account}</dd>
                        <dt>Balance after</dt>
                        <dd>
                          {formatAmount(
                            request.summary.balance_after,
                            request.summary.currency,
                          )}
                        </dd>
                      </dl>
                    </>
                  )}
                  {request.changes.length > 0 && (
                    <div className="request-section">
                      <h3>Proposed changes</h3>
                      <ul className="request-changes">
                        {request.changes.map((change, index) => (
                          <li key={`${index}-${change}`}>{change}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {request.risk_warnings.length > 0 && (
                    <div className="request-section">
                      <h3>Risk warnings</h3>
                      <ul className="risk-list">
                        {request.risk_warnings.map((warning, index) => (
                          <li key={`${index}-${warning.message}`}>
                            Warning: {warning.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="request-actions">
                    <button
                      className="button button-danger"
                      type="button"
                      disabled={busy}
                      onClick={() => void takeDecision(request, "cancel")}
                    >
                      {processingId === request.subject_id
                        ? "Processing…"
                        : "Decline"}
                    </button>
                    <button
                      className="button button-primary"
                      type="button"
                      disabled={busy}
                      onClick={() => void takeDecision(request, "confirm")}
                    >
                      {processingId === request.subject_id
                        ? "Processing…"
                        : "Confirm"}
                    </button>
                  </div>
                </article>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}
