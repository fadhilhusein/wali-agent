import type { ReactNode, Ref } from "react";
import { ChatIcon, type ChatIconName } from "@/components/ui/chat-icon";
import "./finance-pages.css";

export function FinanceHeading({
  id,
  title,
  description,
  kicker,
  icon,
  role,
  headingRef,
  children,
}: {
  id: string;
  title: string;
  description: string;
  kicker: string;
  icon: ChatIconName;
  role: string;
  headingRef?: Ref<HTMLHeadingElement>;
  children?: ReactNode;
}) {
  return (
    <header className="paper-finance-heading">
      <span className="paper-finance-kicker">
        <ChatIcon name={icon} />
        {kicker}
      </span>
      <h1 id={id} ref={headingRef} tabIndex={-1}>
        {title}
      </h1>
      <p>{description}</p>
      <div className="paper-finance-context">
        <span>
          {role ? (
            <>
              Acting as <strong>{role}</strong>
            </>
          ) : (
            "Connecting to Wali"
          )}
        </span>
        {children}
      </div>
    </header>
  );
}

export function FinanceState({
  title,
  description,
  icon,
  tone = "neutral",
  role,
  children,
}: {
  title: string;
  description: string;
  icon: ChatIconName;
  tone?: "neutral" | "error";
  role?: "alert" | "status";
  children?: ReactNode;
}) {
  return (
    <div
      className={`paper-finance-state paper-finance-state-${tone}`}
      role={role}
    >
      <span className="paper-finance-state-icon">
        <ChatIcon name={icon} />
      </span>
      <h2>{title}</h2>
      <p>{description}</p>
      {children}
    </div>
  );
}
