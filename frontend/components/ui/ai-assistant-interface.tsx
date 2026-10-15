"use client";

import { useEffect, useRef, useState } from "react";
import { animate, motion } from "motion/react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";
import { useWorkspace, type Message } from "@/components/workspace-provider";
import { ChatIcon, type ChatIconName } from "./chat-icon";
import { WaliLogo } from "./wali-logo";
import { ChatBackground } from "./chat-background";
import { PromptCard } from "./prompt-card";
import { useMediaQuery } from "@/lib/use-media-query";

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

function MessageRow({
  children,
  className,
  reducedMotion,
  animateEntry = true,
  role,
}: {
  children: ReactNode;
  className: string;
  reducedMotion: boolean;
  animateEntry?: boolean;
  role?: "status";
}) {
  return (
    <motion.li
      className={className}
      role={role}
      initial={
        animateEntry && !reducedMotion
          ? { opacity: 0, transform: "translateY(8px)" }
          : false
      }
      animate={{ opacity: 1, transform: "translateY(0px)" }}
      transition={{
        duration: reducedMotion ? 0 : 0.24,
        ease: [0.22, 1, 0.36, 1],
      }}
    >
      {children}
    </motion.li>
  );
}

function AssistantMessage({
  message,
  reducedMotion,
  animateEntry,
}: {
  message: Message;
  reducedMotion: boolean;
  animateEntry: boolean;
}) {
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
    <MessageRow
      reducedMotion={reducedMotion}
      animateEntry={animateEntry}
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
    </MessageRow>
  );
}

export function AIAssistantInterface() {
  const pageRef = useRef<HTMLElement>(null);
  const introPlayed = useRef(false);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)");
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const autoScrolling = useRef(false);
  const scrollInitialized = useRef(false);
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
  const [existingMessageIds] = useState(
    () => new Set(messages.map((message) => message.id)),
  );

  useEffect(() => {
    if (!info || infoError || introPlayed.current) return;
    if (
      reducedMotion ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      introPlayed.current = true;
      return;
    }
    const page = pageRef.current;
    if (!page) return;
    const controls: Array<ReturnType<typeof animate>> = [];
    const finish = () => controls.forEach((control) => control.complete());
    const frame = requestAnimationFrame(() => {
      introPlayed.current = true;
      if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      let cardIndex = 0;
      Array.from(page.querySelectorAll<HTMLElement>("[data-chat-intro]"))
        .filter((element) => element.getClientRects().length > 0)
        .forEach((element) => {
          const part = element.dataset.chatIntro;
          const delay =
            part === "greeting"
              ? 0
              : part === "question"
                ? 0.08
                : part === "prompt"
                  ? 0.16 + cardIndex++ * 0.06
                  : part === "composer"
                    ? 0.4
                    : 0.48;
          controls.push(
            animate(
              element,
              {
                opacity: [0, Number(getComputedStyle(element).opacity)],
                transform: ["translateY(10px)", "translateY(0px)"],
              },
              { duration: 0.4, delay, ease: [0.22, 1, 0.36, 1] },
            ),
          );
        });
      page.addEventListener("focusin", finish);
      page.addEventListener("pointerdown", finish);
    });
    return () => {
      cancelAnimationFrame(frame);
      finish();
      page.removeEventListener("focusin", finish);
      page.removeEventListener("pointerdown", finish);
    };
  }, [info, infoError, reducedMotion]);

  useEffect(() => {
    if (composerFocusVersion === focusVersion.current) return;
    focusVersion.current = composerFocusVersion;
    composerRef.current?.focus({ preventScroll: true });
  }, [composerFocusVersion]);

  useEffect(() => {
    const scroll = scrollRef.current;
    const firstScroll = !scrollInitialized.current;
    scrollInitialized.current = true;
    if (!scroll || !messages.length || !followMessages.current) return;
    const smooth = !reducedMotion && !firstScroll;
    autoScrolling.current = smooth;
    scroll.scrollTo({
      top: scroll.scrollHeight,
      behavior: smooth ? "smooth" : "instant",
    });
    if (scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 2)
      autoScrolling.current = false;
  }, [messages, sending, reducedMotion]);

  function interruptAutoScroll() {
    const scroll = scrollRef.current;
    if (!scroll) return;
    if (autoScrolling.current)
      scroll.scrollTo({ top: scroll.scrollTop, behavior: "instant" });
    autoScrolling.current = false;
    followMessages.current =
      scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
  }

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
      ref={pageRef}
      className={`paper-chat${messages.length ? " paper-chat-active" : ""}`}
      aria-labelledby="chat-title"
    >
      <ChatBackground />
      <div
        ref={scrollRef}
        className="paper-chat-scroll"
        onScroll={(event) => {
          const el = event.currentTarget;
          const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
          if (autoScrolling.current) {
            if (distance < 2) {
              autoScrolling.current = false;
              followMessages.current = true;
            }
            return;
          }
          followMessages.current = distance < 100;
        }}
        onWheel={(event) => {
          if (event.deltaY < 0) interruptAutoScroll();
        }}
        onPointerDown={interruptAutoScroll}
        onTouchStart={interruptAutoScroll}
        onKeyDown={(event) => {
          if (["ArrowUp", "PageUp", "Home"].includes(event.key))
            interruptAutoScroll();
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
              <span data-chat-intro="greeting">{"Hello, i'm Wali"}</span>
              <span data-chat-intro="question">How can I help you today?</span>
            </h1>
            <div className="paper-prompts" aria-label="Suggested prompts">
              {prompts.map((prompt) => (
                <PromptCard
                  key={prompt.icon}
                  text={prompt.text}
                  icon={prompt.icon}
                  disabled={!role || busy}
                  onSelect={() => {
                    setDraft(`${prompt.text}.`);
                    composerRef.current?.focus();
                  }}
                />
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
                  <MessageRow
                    key={message.id}
                    reducedMotion={reducedMotion}
                    animateEntry={!existingMessageIds.has(message.id)}
                    className="paper-message paper-message-user"
                  >
                    <span className="sr-only">You</span>
                    <div className="paper-user-bubble">{message.text}</div>
                  </MessageRow>
                ) : (
                  <AssistantMessage
                    key={message.id}
                    message={message}
                    reducedMotion={reducedMotion}
                    animateEntry={!existingMessageIds.has(message.id)}
                  />
                ),
              )}
              {sending && (
                <MessageRow
                  reducedMotion={reducedMotion}
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
                </MessageRow>
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
        <form
          className="paper-composer"
          data-chat-intro="composer"
          onSubmit={submit}
        >
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
        <p
          className="paper-disclaimer my-4 opacity-50"
          data-chat-intro="caption"
        >
          Wali can make mistakes. Check its answers. Local simulation only.
          Attachments, tools & voice: Coming soon
        </p>
        <div
          id="composer-instructions"
          className="paper-input-hint"
          data-chat-intro="caption"
        >
          <span>Enter to send · Shift+Enter for a new line</span>
          <span>{draft.length.toLocaleString("en-US")}/4,000</span>
        </div>
      </div>
    </section>
  );
}
