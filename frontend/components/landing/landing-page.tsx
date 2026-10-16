import Image from "next/image";
import Link from "next/link";
import { ChatIcon, type ChatIconName } from "@/components/ui/chat-icon";
import {
  LandingEntrance,
  LandingHeader,
  LandingHeroVisual,
} from "./landing-interactions";
import "./landing.css";

const capabilities: {
  title: string;
  description: string;
  icon: ChatIconName;
}[] = [
  {
    title: "Transaction reconciliation",
    description:
      "Compare transactions and identify records that need a closer look.",
    icon: "chart",
  },
  {
    title: "Cash-flow forecasting",
    description:
      "Explore your cash position over the coming weeks with the records available.",
    icon: "calendar",
  },
  {
    title: "Invoice review",
    description:
      "Review outstanding invoices, due dates and details before making a decision.",
    icon: "invoice",
  },
  {
    title: "Financial recommendations",
    description:
      "Discuss practical next steps in the context of your business finances.",
    icon: "bulb",
  },
];

const steps = [
  {
    title: "Start with a conversation",
    description:
      "Ask Wali about transactions, invoices or cash flow. Keep the questions and their context together in Chat.",
    label: "Chat",
  },
  {
    title: "Set the boundaries",
    description:
      "Draft spending rules in Mandate. A draft needs the owner’s review before the rules take effect.",
    label: "Mandate",
  },
  {
    title: "Review the requests",
    description:
      "Requests that need a decision appear in Approvals. Inspect the details and warnings, then confirm or decline.",
    label: "Approvals",
  },
];

export function LandingPage() {
  return (
    <div className="wl-landing" id="top">
      <a className="wl-skip" href="#landing-main">
        Skip to content
      </a>
      <LandingHeader />
      <main id="landing-main" tabIndex={-1}>
        <LandingEntrance>
          <section
            className="wl-hero wl-container"
            aria-labelledby="landing-title"
          >
            <h1 id="landing-title" data-landing-enter>
              Clearer finances.
              <br />
              <span>One conversation.</span>
            </h1>
            <p className="wl-hero-description" data-landing-enter>
              Reconcile transactions, explore cash flow, and review financial
              requests with Wali.
            </p>
            <div className="wl-hero-actions" data-landing-enter>
              <Link className="wl-button wl-button-primary" href="/chat">
                Open Wali
              </Link>
              <a className="wl-button wl-button-secondary" href="#how-it-works">
                Explore the workflow
              </a>
            </div>
          </section>
          <section
            className="wl-showcase wl-container"
            aria-label="Wali workspace preview"
            data-landing-enter
          >
            <LandingHeroVisual>
              <span className="wl-preview-label">Simulation preview</span>
              <div className="wl-preview-card">
                <div className="wl-preview-card-heading">
                  <Image src="/brand/wali.svg" alt="" width={24} height={24} />
                  <span>Example prompt</span>
                </div>
                <p>
                  Reconcile recent transactions and flag anything that needs
                  review.
                </p>
                <div className="wl-preview-card-bottom">
                  <span>Your next question starts here.</span>
                  <Link className="wl-button wl-button-primary" href="/chat">
                    Open chat
                  </Link>
                </div>
              </div>
            </LandingHeroVisual>
            <p className="wl-showcase-caption">
              Explore the workspace with synthetic business data.
            </p>
          </section>
        </LandingEntrance>

        <section
          id="capabilities"
          className="wl-capabilities wl-container wl-section"
          aria-labelledby="capabilities-title"
        >
          <div className="wl-section-heading">
            <h2 id="capabilities-title">
              Make sense of
              <br />
              everyday finance.
            </h2>
            <p>
              Bring your financial questions into one conversation, from
              matching transactions to considering what comes next.
            </p>
          </div>
          <div className="wl-capability-grid">
            {capabilities.map((item) => (
              <article key={item.title}>
                <ChatIcon name={item.icon} />
                <h3>{item.title}</h3>
                <p>{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          id="how-it-works"
          className="wl-workflow wl-container wl-section"
          aria-labelledby="workflow-title"
        >
          <div className="wl-workflow-heading">
            <h2 id="workflow-title">
              Ask.
              <br />
              Set boundaries.
              <br />
              <span>Review.</span>
            </h2>
            <p>
              A conversation to understand the numbers. A place to define rules
              and review the decisions that need you.
            </p>
          </div>
          <ol className="wl-steps">
            {steps.map((step, index) => (
              <li key={step.label}>
                <span className="wl-step-number" aria-hidden="true">
                  0{index + 1}
                </span>
                <div>
                  <span className="wl-step-label">{step.label}</span>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section
          id="simulation"
          className="wl-simulation wl-container wl-section"
          aria-labelledby="simulation-title"
        >
          <div className="wl-simulation-inner">
            <div>
              <span className="wl-simulation-label">Local simulation</span>
              <h2 id="simulation-title">
                Room to explore.
                <br />
                With simulated data.
              </h2>
              <p>
                Wali currently runs on synthetic business data. There are no
                real bank connections and no real money is moved. Role selection
                is part of the demo.
              </p>
            </div>
            <Link className="wl-button wl-button-primary" href="/chat">
              Open Wali
            </Link>
          </div>
        </section>
      </main>
      <footer className="wl-footer">
        <div className="wl-container wl-footer-inner">
          <Link className="wl-brand" href="/" aria-label="Wali home">
            <Image src="/brand/wali.svg" alt="" width={28} height={28} />
            <span>Wali</span>
          </Link>
          <p>A conversational finance assistant. Simulation only.</p>
          <nav aria-label="Footer navigation">
            <a href="#capabilities">Capabilities</a>
            <a href="#simulation">Simulation</a>
            <Link href="/chat">Open chat</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
