"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { motion, useInView } from "motion/react";
import { Pause, Play, RotateCcw } from "lucide-react";
import { WaliLogo } from "@/components/ui/wali-logo";
import { useMediaQuery } from "@/lib/use-media-query";

const messages = [
  {
    role: "You",
    start: 400,
    duration: 0,
    text: "Help me review outstanding invoices.",
  },
  {
    role: "Wali",
    start: 2300,
    duration: 2700,
    text: "Let’s review due dates and payment details before deciding what to do.",
  },
  { role: "You", start: 6500, duration: 0, text: "Can I set spending rules?" },
  {
    role: "Wali",
    start: 8500,
    duration: 3900,
    text: "Draft them in Mandate. The Owner reviews the draft before the rules take effect.",
  },
];
const duration = 14_000;
const subscribeReady = () => () => {};
const clientReady = () => true;
const serverReady = () => false;
const subscribeVisibility = (callback: () => void) => {
  document.addEventListener("visibilitychange", callback);
  return () => document.removeEventListener("visibilitychange", callback);
};
const tabVisible = () => document.visibilityState === "visible";

export function WorkflowDemo() {
  const root = useRef<HTMLDivElement>(null);
  const ready = useSyncExternalStore(subscribeReady, clientReady, serverReady);
  const visible = useInView(root, { amount: 0.15 });
  const foreground = useSyncExternalStore(
    subscribeVisibility,
    tabVisible,
    serverReady,
  );
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const [elapsed, setElapsed] = useState(0);
  const [paused, setPaused] = useState(false);
  const finished = elapsed >= duration;
  const staticView = !ready || reduced;
  const running =
    ready && visible && foreground && !paused && !reduced && !finished;
  const processing =
    !staticView &&
    ((elapsed >= 1000 && elapsed < 2300) ||
      (elapsed >= 7000 && elapsed < 8500));

  useEffect(() => {
    if (!running) return;
    let previous = performance.now();
    const timer = window.setInterval(() => {
      const now = performance.now();
      const delta = now - previous;
      previous = now;
      setElapsed((value) => Math.min(duration, value + delta));
    }, 80);
    return () => window.clearInterval(timer);
  }, [running]);

  return (
    <div
      className="wl-demo"
      ref={root}
      role="region"
      aria-label="Illustrative conversation with Wali"
      data-elapsed={Math.round(elapsed)}
      data-running={running}
    >
      <div className="wl-demo-header">
        <div className="wl-demo-agent">
          <WaliLogo
            decorative
            state={processing && running ? "processing" : "idle"}
          />
          <span>Wali</span>
        </div>
        <span className="wl-demo-label">Illustrative conversation</span>
      </div>
      <ol className="wl-demo-accessible">
        {messages.map((message, index) => (
          <li key={index}>
            {message.role}: {message.text}
          </li>
        ))}
      </ol>
      <ol className="wl-demo-transcript" aria-hidden="true">
        {messages.map((message, index) => {
          const shown = staticView || elapsed >= message.start;
          const words = message.text.split(" ");
          const count =
            staticView || !message.duration
              ? words.length
              : Math.max(
                  1,
                  Math.ceil(
                    (words.length * (elapsed - message.start)) /
                      message.duration,
                  ),
                );
          return (
            <motion.li
              key={index}
              className={`wl-demo-message wl-demo-${message.role === "You" ? "user" : "assistant"}`}
              initial={false}
              animate={{
                opacity: shown ? 1 : 0,
                transform: shown ? "translateY(0px)" : "translateY(8px)",
              }}
              transition={{ duration: staticView ? 0 : 0.24 }}
            >
              <span className="wl-demo-speaker">{message.role}</span>
              <div className="wl-demo-bubble">
                <div className="wl-demo-text">
                  <span className="wl-demo-measure">{message.text}</span>
                  <span className="wl-demo-copy">
                    {shown ? words.slice(0, count).join(" ") : ""}
                  </span>
                </div>
              </div>
            </motion.li>
          );
        })}
      </ol>
      <div className="wl-demo-processing" aria-hidden="true">
        {processing && (
          <span>
            Wali is reviewing
            <span className={running ? "wl-demo-dots" : ""}>…</span>
          </span>
        )}
      </div>
      <div className="wl-demo-footer">
        <span>Scripted demo. No requests are sent.</span>
        {ready && !reduced && (
          <div className="wl-demo-controls">
            {!finished && (
              <button
                type="button"
                onClick={() => setPaused((value) => !value)}
                aria-label={
                  paused
                    ? "Resume conversation demo"
                    : "Pause conversation demo"
                }
              >
                {paused ? (
                  <Play size={16} strokeWidth={1.75} aria-hidden="true" />
                ) : (
                  <Pause size={16} strokeWidth={1.75} aria-hidden="true" />
                )}
                {paused ? "Resume" : "Pause"}
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setElapsed(0);
                setPaused(false);
              }}
            >
              <RotateCcw size={16} strokeWidth={1.75} aria-hidden="true" />
              Replay demo
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
