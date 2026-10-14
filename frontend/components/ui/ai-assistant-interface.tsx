"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { useWorkspace } from "@/components/workspace-provider";

const prompts = [
  {
    title: "Reconcile transactions",
    detail: "Find records that need review",
    text: "Reconcile recent transactions and show me anything that needs review.",
  },
  {
    title: "Project cash",
    detail: "Look ahead at cash position",
    text: "Project our cash position for the next few weeks.",
  },
  {
    title: "Review invoices",
    detail: "Check what is due",
    text: "Review outstanding invoices and tell me what needs attention.",
  },
];

export function AIAssistantInterface() {
  const reduceMotion = useReducedMotion();
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const focusVersion = useRef(0);
  const {
    info,
    infoError,
    retryInfo,
    role,
    draft,
    setDraft,
    messages,
    sending,
    busy,
    chatNotice,
    composerFocusVersion,
    sendMessage,
  } = useWorkspace();

  useEffect(() => {
    if (composerFocusVersion === focusVersion.current) return;
    focusVersion.current = composerFocusVersion;
    composerRef.current?.focus();
  }, [composerFocusVersion]);
  useEffect(() => {
    if (messages.length > 0)
      messageEndRef.current?.scrollIntoView({
        behavior: reduceMotion ? "instant" : "smooth",
        block: "end",
      });
  }, [messages, reduceMotion]);

  function submit(event: FormEvent) {
    event.preventDefault();
    void sendMessage();
  }
  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void sendMessage();
    }
  }

  return (
    <section
      className={`chat-page${messages.length ? " chat-page-active" : ""}`}
      aria-labelledby="chat-title"
    >
      <div className="chat-page-top">
        <span className="page-eyebrow">WALI / CONVERSATION</span>
        <span className="page-role">
          {role ? `Acting as ${role}` : "Connecting"}
        </span>
      </div>
      <div className="chat-stage">
        {infoError && (
          <div className="state-panel" role="alert">
            <strong>Unable to connect</strong>
            <p>{infoError}</p>
            <button
              className="button"
              type="button"
              onClick={() => void retryInfo()}
            >
              Retry connection
            </button>
          </div>
        )}
        {!infoError && !info && (
          <div className="state-panel" role="status">
            <strong>Connecting to Wali</strong>
            <p>Loading roles and approval requests.</p>
          </div>
        )}
        {info && messages.length === 0 && (
          <motion.div
            className="empty-state"
            initial={reduceMotion ? false : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28 }}
          >
            <p className="empty-kicker">Ask Wali</p>
            <h1 id="chat-title" className="empty-title">
              What should we check?
            </h1>
            <p className="empty-description">
              Ask Wali about transactions, cash, or invoices. Actions that need
              a decision appear in Approvals.
            </p>
          </motion.div>
        )}
        {messages.length > 0 && (
          <div className="conversation-wrap">
            <h1 id="chat-title" className="conversation-title">
              Conversation
            </h1>
            <ol className="message-list" aria-label="Conversation messages">
              {messages.map((message) => (
                <motion.li
                  key={message.id}
                  className={`message message-${message.author === "you" ? "user" : "assistant"}${message.blocked ? " message-blocked" : ""}`}
                  initial={reduceMotion ? false : { opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.18 }}
                >
                  <span className="message-meta">
                    {message.author === "you" ? "You" : "Wali"}
                  </span>
                  {message.blocked && (
                    <span className="blocked-label">
                      Reply blocked for safety
                    </span>
                  )}
                  <div className="message-bubble">{message.text}</div>
                </motion.li>
              ))}
              {sending && (
                <li className="message message-assistant" role="status">
                  <span className="message-meta">Wali</span>
                  <div className="message-bubble">
                    Thinking through your request…
                  </div>
                </li>
              )}
            </ol>
            <div ref={messageEndRef} />
          </div>
        )}
      </div>
      <div className="chat-dock">
        {chatNotice && (
          <div
            className={`notice notice-${chatNotice.tone}`}
            role={chatNotice.tone === "error" ? "alert" : "status"}
          >
            {chatNotice.text}
          </div>
        )}
        <form className="composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="message-input">
            Message Wali
          </label>
          <textarea
            id="message-input"
            ref={composerRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onComposerKeyDown}
            maxLength={4000}
            placeholder="Ask Wali about your business"
            disabled={!role || busy}
          />
          <div className="composer-footer">
            <span className="composer-hint">
              Enter to send · Shift+Enter for a new line · {draft.length}/4,000
            </span>
            <button
              className="button button-primary send-button"
              type="submit"
              disabled={!role || !draft.trim() || busy}
            >
              {sending ? (
                "Sending…"
              ) : (
                <>
                  Send <span aria-hidden="true">↗</span>
                </>
              )}
            </button>
          </div>
        </form>
        <div className="quick-prompts" aria-label="Suggested prompts">
          {prompts.map((prompt) => (
            <button
              key={prompt.title}
              className="prompt"
              type="button"
              disabled={!role || busy}
              onClick={() => {
                setDraft(prompt.text);
                composerRef.current?.focus();
              }}
            >
              <span className="prompt-title">{prompt.title}</span>
              <span className="prompt-detail">{prompt.detail}</span>
            </button>
          ))}
        </div>
        <p className="roadmap">
          Coming soon: Search · Deep Research · Reason · Microphone · File
          upload
        </p>
      </div>
    </section>
  );
}
