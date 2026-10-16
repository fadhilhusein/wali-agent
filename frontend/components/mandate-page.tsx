"use client";

import Link from "next/link";
import { useWorkspace } from "@/components/workspace-provider";
import { FinanceHeading, FinanceState } from "@/components/finance-page-ui";
import { ChatIcon } from "@/components/ui/chat-icon";

export function MandatePage() {
  const {
    info,
    infoError,
    retryInfo,
    role,
    busy,
    mandating,
    mandateNotice,
    requests,
    queueState,
    queueError,
    retryPending,
    draftMandate,
  } = useWorkspace();
  const mandateCount = requests.filter(
    (request) => request.kind === "mandate",
  ).length;

  return (
    <section
      className="paper-finance-page mandate-page"
      aria-labelledby="mandate-title"
    >
      <FinanceHeading
        id="mandate-title"
        title="Business mandate"
        kicker="Spending rules"
        icon="rules"
        role={role}
        description="Set the boundaries for Wali's financial actions. Draft the rules, then review them before they take effect."
      >
        <span className="paper-finance-pill">Owner approval</span>
      </FinanceHeading>
      <div className="paper-mandate-flow">
        <span className="paper-mandate-icon">
          <ChatIcon name="rules" />
        </span>
        <h2>Draft, then review</h2>
        <p>
          A mandate defines spending rules for verified suppliers in this local
          simulation. Every draft needs a decision.
        </p>
        <ol className="paper-mandate-steps">
          <li>
            <span className="paper-mandate-step-number" aria-hidden="true">
              1
            </span>
            <div>
              <h3>Draft a mandate</h3>
              <p>
                Wali creates a request for the owner to review. Drafting does
                not confirm the rules.
              </p>
            </div>
          </li>
          <li>
            <span className="paper-mandate-step-number" aria-hidden="true">
              2
            </span>
            <div>
              <h3>Review in Approvals</h3>
              <p>
                Check the proposed changes and any risk warnings, then confirm
                or decline the request.
              </p>
            </div>
          </li>
        </ol>
      </div>
      <div className="paper-mandate-action-area">
        {mandateNotice && (
          <div
            className={`paper-finance-notice paper-finance-notice-${mandateNotice.tone}`}
            role={mandateNotice.tone === "error" ? "alert" : "status"}
          >
            {mandateNotice.text}
          </div>
        )}
        {infoError ? (
          <FinanceState
            title="Mandate unavailable"
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
        ) : !info ? (
          <FinanceState
            title="Connecting to Wali"
            description="Loading your simulation role before drafting is available."
            icon="rules"
            role="status"
          />
        ) : role === "owner" ? (
          <div className="paper-mandate-create">
            <button
              className="paper-action paper-action-primary"
              type="button"
              disabled={busy}
              onClick={() => void draftMandate()}
            >
              <ChatIcon name="plus" />
              {mandating ? "Drafting…" : "Draft mandate"}
            </button>
            <p>Creates a request. The rules still need your approval.</p>
          </div>
        ) : (
          <FinanceState
            title="Owner action"
            description="Only the owner can draft a mandate. Use Settings and help to switch to owner in this local simulation."
            icon="settings"
          />
        )}
        {mandateNotice?.tone === "success" && (
          <Link
            className="paper-action paper-action-secondary paper-mandate-review"
            href="/approvals"
          >
            <ChatIcon name="check" />
            Review the request in Approvals
          </Link>
        )}
      </div>
      {info && !infoError && (
        <div className="paper-mandate-status">
          {queueState === "loading" && (
            <p role="status">Checking pending mandates…</p>
          )}
          {queueState === "error" && (
            <div className="paper-mandate-status-error" role="alert">
              <div>
                <strong>Approval status unavailable</strong>
                <p>{queueError}</p>
              </div>
              <button
                className="paper-action paper-action-secondary"
                type="button"
                onClick={() => void retryPending()}
              >
                Retry approvals
              </button>
            </div>
          )}
          {queueState === "ready" &&
            (mandateCount > 0 ? (
              <>
                <span className="paper-finance-pill">
                  {mandateCount} pending{" "}
                  {mandateCount === 1 ? "mandate" : "mandates"}
                </span>
                {mandateNotice?.tone !== "success" && (
                  <Link className="paper-finance-text-link" href="/approvals">
                    Open Approvals
                  </Link>
                )}
              </>
            ) : (
              <p>No mandate requests waiting.</p>
            ))}
        </div>
      )}
    </section>
  );
}
