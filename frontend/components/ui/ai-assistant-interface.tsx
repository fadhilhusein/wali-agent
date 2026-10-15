"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import { useWorkspace, type Message } from "@/components/workspace-provider";
import { ChatIcon, type ChatIconName } from "./chat-icon";
import { WaliLogo } from "./wali-logo";

const prompts: { text: string; icon: ChatIconName }[] = [
  {
    text: "Reconcile recent transactions and flag anything that needs review",
    icon: "chart",
  },
  {
    text: "Project our cash position for the next four weeks",
    icon: "calendar",
  },
  {
    text: "Review outstanding invoices and tell me what is due",
    icon: "invoice",
  },
  { text: "Suggest ways to improve our business cash flow", icon: "bulb" },
];

function FutureControl({
  icon,
  label,
  text,
}: {
  icon: ChatIconName;
  label: string;
  text?: string;
}) {
  return (
    <button
      className="paper-future-control paper-icon-button"
      type="button"
      disabled
      aria-label={`${label}, coming soon`}
      title={`${label}: Coming soon`}
    >
      <ChatIcon name={icon} />
      {text && <span>{text}</span>}
    </button>
  );
}

function AssistantMessage({ message }: { message: Message }) {
  const [copyStatus, setCopyStatus] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(message.text);
      setCopyStatus("Copied to clipboard");
    } catch {
      setCopyStatus(
        "Could not copy. Select the reply text and copy it manually.",
      );
    }
  }
  return (
    <li
      className={`paper-message paper-message-assistant${message.blocked ? " paper-message-blocked" : ""}`}
    >
      <WaliLogo className="paper-assistant-mark" state="reply" />
      <div className="paper-reply">
        {message.blocked && (
          <strong className="paper-blocked-label">
            Reply blocked for safety
          </strong>
        )}
        <div className="paper-message-text">{message.text}</div>
        <div className="paper-reply-actions" aria-label="Reply actions">
          <FutureControl icon="up" label="Helpful" />
          <FutureControl icon="down" label="Not helpful" />
          <FutureControl icon="refresh" label="Regenerate" />
          <button
            className="paper-icon-button"
            type="button"
            aria-label="Copy reply"
            title="Copy reply"
            onClick={() => void copy()}
          >
            <ChatIcon name="copy" />
          </button>
          <span className="paper-coming-soon">
            Feedback & retry: Coming soon
          </span>
        </div>
        <p className="paper-copy-status" role="status">
          {copyStatus}
        </p>
      </div>
    </li>
  );
}

export function AIAssistantInterface() {
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
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
    composerRef.current?.focus({ preventScroll: true });
  }, [composerFocusVersion]);

  useEffect(() => {
    const scroll = scrollRef.current;
    if (scroll && followMessages.current)
      scroll.scrollTop = scroll.scrollHeight;
  }, [messages, sending]);

  useEffect(() => {
    const input = composerRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  }, [draft]);

  function submit(event: FormEvent) {
    event.preventDefault();
    followMessages.current = true;
    void sendMessage();
  }
  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      followMessages.current = true;
      void sendMessage();
    }
  }

  return (
    <section
      className={`paper-chat${messages.length ? " paper-chat-active" : ""}`}
      aria-labelledby="chat-title"
    >
      <div
        ref={scrollRef}
        className="paper-chat-scroll"
        onScroll={(event) => {
          const el = event.currentTarget;
          followMessages.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 100;
        }}
      >
        {infoError && (
          <div className="paper-chat-state state-panel" role="alert">
            <h1 id="chat-title">Unable to connect</h1>
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
          <div className="paper-chat-state state-panel" role="status">
            <h1 id="chat-title">Connecting to Wali</h1>
            <p>Loading roles and approval requests.</p>
          </div>
        )}
        {info && !infoError && messages.length === 0 && (
          <div className="paper-welcome">
            <h1 id="chat-title">
              <span>Hello</span>
              <span>How can I help you today?</span>
            </h1>
            <div className="paper-prompts" aria-label="Suggested prompts">
              {prompts.map((prompt) => (
                <button
                  key={prompt.icon}
                  className="paper-prompt"
                  type="button"
                  disabled={!role || busy}
                  onClick={() => {
                    setDraft(`${prompt.text}.`);
                    composerRef.current?.focus();
                  }}
                >
                  <span>{prompt.text}</span>
                  <span className="paper-prompt-icon">
                    <ChatIcon name={prompt.icon} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.length > 0 && (
          <div className="paper-conversation">
            <h1 id="chat-title" className="sr-only">
              Conversation with Wali
            </h1>
            <ol className="paper-messages" aria-label="Conversation messages">
              {messages.map((message) =>
                message.author === "you" ? (
                  <li
                    key={message.id}
                    className="paper-message paper-message-user"
                  >
                    <span className="sr-only">You</span>
                    <div className="paper-user-bubble">{message.text}</div>
                  </li>
                ) : (
                  <AssistantMessage key={message.id} message={message} />
                ),
              )}
              {sending && (
                <li
                  className="paper-message paper-message-assistant"
                  role="status"
                >
                  <WaliLogo
                    className="paper-assistant-mark"
                    state="processing"
                    decorative
                  />
                  <p className="paper-thinking">
                    Thinking through your request…
                  </p>
                </li>
              )}
            </ol>
          </div>
        )}
      </div>
      <div className="paper-chat-dock">
        {chatNotice && (
          <div
            className={`notice notice-${chatNotice.tone}`}
            role={chatNotice.tone === "error" ? "alert" : "status"}
          >
            {chatNotice.text}
          </div>
        )}
        <form className="paper-composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="message-input">
            Message Wali
          </label>
          <textarea
            id="message-input"
            ref={composerRef}
            value={draft}
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onComposerKeyDown}
            maxLength={4000}
            placeholder="Ask Wali about your business"
            aria-describedby="composer-instructions"
            disabled={!role || busy}
          />
          <div className="paper-composer-toolbar">
            <div className="paper-composer-options">
              <FutureControl icon="plus" label="Attach file" />
              <FutureControl icon="tools" label="Tools" text="Tools" />
              <span className="paper-coming-soon">Coming soon</span>
            </div>
            <div className="paper-composer-options">
              <FutureControl icon="mic" label="Microphone" />
              <button
                className="paper-send paper-icon-button"
                type="submit"
                disabled={!role || !draft.trim() || busy}
                aria-label={sending ? "Sending message" : "Send message"}
                title="Send message"
              >
                <ChatIcon name="arrow" />
              </button>
            </div>
          </div>
        </form>
        <p className="paper-disclaimer my-4 opacity-50">
          Wali can make mistakes. Check its answers. Local simulation only.
          Attachments, tools & voice: Coming soon
        </p>
        <div id="composer-instructions" className="paper-input-hint">
          <span>Enter to send · Shift+Enter for a new line</span>
          <span>{draft.length.toLocaleString("en-US")}/4,000</span>
        </div>
      </div>
    </section>
  );
}
