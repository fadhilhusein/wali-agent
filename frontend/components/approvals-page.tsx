"use client";

import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { useRef } from "react";
import { useWorkspace } from "@/components/workspace-provider";
import type { PendingRequest } from "@/lib/wali-api";
import { ChatIcon } from "@/components/ui/chat-icon";
import { FinanceHeading, FinanceState } from "@/components/finance-page-ui";
import { useMediaQuery } from "@/lib/use-media-query";

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
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const {
    role,
    infoError,
    retryInfo,
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
      className="paper-finance-page approvals-page"
      aria-labelledby="approvals-title"
    >
      <FinanceHeading
        id="approvals-title"
        title="Approvals"
        kicker="Review & decide"
        icon="check"
        headingRef={headingRef}
        role={role}
        description="Review the requests waiting for your role, then confirm or decline."
      >
        {queueState === "ready" && !infoError && (
          <span className="paper-finance-pill">
            {requests.length} pending{" "}
            {requests.length === 1 ? "request" : "requests"}
          </span>
        )}
      </FinanceHeading>
      {queueNotice && (
        <div
          className={`paper-finance-notice paper-finance-notice-${queueNotice.tone}`}
          role={queueNotice.tone === "error" ? "alert" : "status"}
        >
          {queueNotice.text}
        </div>
      )}
      {infoError && (
        <FinanceState
          title="Approvals unavailable"
          description={infoError}
          icon="refresh"
          tone="error"
          role="alert"
        >
          <button
            className="paper-action paper-action-secondary"
            type="button"
            onClick={() => void retryInfo()}
          >
            <ChatIcon name="refresh" />
            Retry connection
          </button>
        </FinanceState>
      )}
      {!infoError && queueState === "loading" && (
        <FinanceState
          title="Loading approvals"
          description={`Checking what is waiting for ${role || "you"}.`}
          icon="check"
          role="status"
        />
      )}
      {!infoError && queueState === "error" && (
        <FinanceState
          title="Approvals unavailable"
          description={queueError}
          icon="refresh"
          tone="error"
          role="alert"
        >
          <button
            className="paper-action paper-action-secondary"
            type="button"
            onClick={() => void retryPending()}
          >
            <ChatIcon name="refresh" />
            Retry approvals
          </button>
        </FinanceState>
      )}
      {!infoError && queueState === "ready" && requests.length === 0 && (
        <FinanceState
          title="Nothing waiting"
          description={`There are no requests for ${role || "this role"} right now. Continue your conversation with Wali; anything that needs a decision will appear here.`}
          icon="check"
        >
          <Link className="paper-action paper-action-secondary" href="/chat">
            <ChatIcon name="chat" />
            Go to chat
          </Link>
        </FinanceState>
      )}
      {!infoError && queueState === "ready" && requests.length > 0 && (
        <ul className="paper-approval-list">
          <AnimatePresence initial={false}>
            {requests.map((request) => (
              <motion.li
                key={request.subject_id}
                initial={reduceMotion ? false : { opacity: 0, y: 7 }}
                animate={{ opacity: 1, y: 0 }}
                exit={reduceMotion ? undefined : { opacity: 0, y: -5 }}
                transition={{ duration: 0.18 }}
              >
                <article className="paper-request">
                  <div className="paper-request-top">
                    <span className="paper-request-kind">
                      <ChatIcon name={request.summary ? "invoice" : "rules"} />
                      {request.kind}
                    </span>
                    <span className="paper-request-expiry">
                      {formatExpiry(request.expires_at)}
                    </span>
                  </div>
                  <h2 className="paper-request-title">
                    {request.summary?.supplier_name ??
                      (request.kind === "mandate"
                        ? "Business mandate"
                        : "Approval request")}
                  </h2>
                  <p className="paper-request-by">
                    Requested by {request.requested_by} · For{" "}
                    {request.required_role}
                  </p>
                  {request.summary && (
                    <>
                      <div className="paper-request-amount">
                        <span>Payment amount</span>
                        <p>
                          {formatAmount(
                            request.summary.amount,
                            request.summary.currency,
                          )}
                        </p>
                      </div>
                      <dl className="paper-request-details">
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
                    <div className="paper-request-section">
                      <h3>Proposed changes</h3>
                      <ul className="paper-request-changes">
                        {request.changes.map((change, index) => (
                          <li key={`${index}-${change}`}>{change}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {request.risk_warnings.length > 0 && (
                    <div className="paper-request-section paper-request-risk">
                      <h3>Risk warnings</h3>
                      <ul className="paper-risk-list">
                        {request.risk_warnings.map((warning, index) => (
                          <li key={`${index}-${warning.message}`}>
                            Warning: {warning.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="paper-request-actions">
                    <button
                      className="paper-action paper-action-decline"
                      type="button"
                      disabled={busy}
                      onClick={() => void takeDecision(request, "cancel")}
                    >
                      <ChatIcon name="close" />
                      {processingId === request.subject_id
                        ? "Processing…"
                        : "Decline"}
                    </button>
                    <button
                      className="paper-action paper-action-primary"
                      type="button"
                      disabled={busy}
                      onClick={() => void takeDecision(request, "confirm")}
                    >
                      <ChatIcon name="check" />
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
