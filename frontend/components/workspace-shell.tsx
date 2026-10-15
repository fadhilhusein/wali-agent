"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import type { Role } from "@/lib/wali-api";
import { useWorkspace } from "@/components/workspace-provider";
import { ChatIcon, type ChatIconName } from "@/components/ui/chat-icon";
import { WaliLogo } from "@/components/ui/wali-logo";
import { useMediaQuery } from "@/lib/use-media-query";
import "./workspace.css";

const destinations: { href: string; label: string; icon: ChatIconName }[] = [
  { href: "/chat", label: "Chat", icon: "chat" },
  { href: "/approvals", label: "Approvals", icon: "check" },
  { href: "/mandate", label: "Mandate", icon: "rules" },
];

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const {
    info,
    role,
    busy,
    resetting,
    requests,
    queueState,
    messages,
    chatNotice,
    changeRole,
    resetConversation,
  } = useWorkspace();
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sidebarState, setSidebarState] = useState("auto");
  const isMobile = useMediaQuery("(max-width: 760px)");
  const compactDefault = useMediaQuery("(max-width: 1100px)");
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const collapsed =
    sidebarState === "closed" || (sidebarState === "auto" && compactDefault);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const settingsRef = useRef<HTMLDivElement>(null);
  const avatarRef = useRef<HTMLButtonElement>(null);
  const settingsTriggerRef = useRef<HTMLElement | null>(null);
  const recentTitle = messages.find(
    (message) => message.author === "you",
  )?.text;

  function closeMenu() {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }

  useEffect(() => {
    const viewport = window.visualViewport;
    function resize() {
      if (!viewport || Math.abs(viewport.scale - 1) < 0.01) {
        const heights = [
          window.innerHeight,
          document.documentElement.clientHeight,
          viewport?.height ?? window.innerHeight,
        ].filter((height) => height > 0);
        shellRef.current?.style.setProperty(
          "--paper-viewport-height",
          `${Math.min(...heights)}px`,
        );
      }
    }
    resize();
    viewport?.addEventListener("resize", resize);
    viewport?.addEventListener("scroll", resize);
    window.addEventListener("resize", resize);
    window.addEventListener("pageshow", resize);
    return () => {
      viewport?.removeEventListener("resize", resize);
      viewport?.removeEventListener("scroll", resize);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pageshow", resize);
    };
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const sidebar = sidebarRef.current;
    const menuButton = menuButtonRef.current;
    const focusables = () =>
      Array.from(
        sidebar?.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled])",
        ) ?? [],
      ).filter((item) => item.getClientRects().length > 0);
    const focusFrame = requestAnimationFrame(() =>
      focusables()[0]?.focus({ preventScroll: true }),
    );
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (event.shiftKey && document.activeElement === items[0]) {
        event.preventDefault();
        items.at(-1)?.focus();
      } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
        event.preventDefault();
        items[0]?.focus();
      }
    }
    const media = window.matchMedia("(min-width: 761px)");
    const onResize = () => {
      if (media.matches) setMenuOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    media.addEventListener("change", onResize);
    return () => {
      cancelAnimationFrame(focusFrame);
      document.removeEventListener("keydown", onKeyDown);
      media.removeEventListener("change", onResize);
      requestAnimationFrame(() => {
        if (!settingsTriggerRef.current) menuButton?.focus();
      });
    };
  }, [menuOpen]);

  function openSettings(trigger: HTMLElement) {
    settingsTriggerRef.current = isMobile ? avatarRef.current : trigger;
    setMenuOpen(false);
    setSettingsOpen(true);
  }

  function closeSettings(restoreFocus = true) {
    setSettingsOpen(false);
    if (restoreFocus) settingsTriggerRef.current?.focus();
    settingsTriggerRef.current = null;
  }

  useEffect(() => {
    if (!settingsOpen) return;
    const frame = requestAnimationFrame(() =>
      settingsRef.current?.focus({ preventScroll: true }),
    );
    function dismiss(event: PointerEvent) {
      const target = event.target as Node;
      if (
        !settingsRef.current?.contains(target) &&
        !avatarRef.current?.contains(target)
      ) {
        setSettingsOpen(false);
        settingsTriggerRef.current = null;
      }
    }
    function escape(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setSettingsOpen(false);
      settingsTriggerRef.current?.focus();
      settingsTriggerRef.current = null;
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [settingsOpen]);

  async function newChat() {
    const reset = await resetConversation();
    if (reset) {
      setMenuOpen(false);
      router.push("/chat");
    }
  }

  return (
    <div
      ref={shellRef}
      className="paper-shell"
      data-sidebar={sidebarState}
      data-mobile={isMobile || undefined}
    >
      <a className="paper-skip" href="#main-content">
        Skip to content
      </a>
      <AnimatePresence initial={false}>
        {menuOpen && (
          <motion.button
            className="paper-backdrop"
            type="button"
            tabIndex={-1}
            aria-label="Dismiss navigation"
            onClick={closeMenu}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.18 }}
          />
        )}
      </AnimatePresence>
      <motion.aside
        ref={sidebarRef}
        id="workspace-navigation"
        className={`paper-sidebar${menuOpen ? " paper-sidebar-open" : ""}`}
        aria-label="Workspace navigation"
        role={menuOpen ? "dialog" : undefined}
        aria-modal={menuOpen ? true : undefined}
        aria-hidden={isMobile && !menuOpen ? true : undefined}
        inert={isMobile && !menuOpen}
        initial={false}
        animate={{
          transform: isMobile
            ? menuOpen
              ? "translateX(0%)"
              : "translateX(-100%)"
            : "none",
        }}
        transition={{
          duration: reduceMotion ? 0 : 0.24,
          ease: [0.22, 1, 0.36, 1],
        }}
      >
        <div className="paper-sidebar-top">
          <button
            className="paper-icon-button paper-collapse"
            type="button"
            aria-label="Toggle sidebar"
            aria-controls="workspace-navigation"
            aria-expanded={!collapsed}
            onClick={() =>
              setSidebarState((current) =>
                current === "auto"
                  ? compactDefault
                    ? "open"
                    : "closed"
                  : current === "open"
                    ? "closed"
                    : "open",
              )
            }
          >
            <ChatIcon name="menu" />
          </button>
          <button
            className="paper-icon-button paper-close-drawer"
            type="button"
            aria-label="Close navigation"
            onClick={closeMenu}
          >
            <ChatIcon name="close" />
          </button>
        </div>
        <button
          className="paper-new-chat"
          type="button"
          disabled={!role || busy}
          aria-label={resetting ? "Starting new chat" : "New chat"}
          title="New chat"
          onClick={() => void newChat()}
        >
          <ChatIcon name="plus" />
          <span className="paper-sidebar-label">
            {resetting ? "Starting…" : "New chat"}
          </span>
        </button>
        <nav className="paper-navigation" aria-label="Pages">
          {destinations.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              title={item.label}
              aria-label={item.label}
              aria-current={pathname === item.href ? "page" : undefined}
              className={`paper-nav-link${pathname === item.href ? " paper-nav-active" : ""}`}
              onClick={() => setMenuOpen(false)}
            >
              <ChatIcon name={item.icon} />
              <span className="paper-sidebar-label">{item.label}</span>
              {item.href === "/approvals" &&
                queueState === "ready" &&
                requests.length > 0 && (
                  <span
                    className="paper-nav-count"
                    aria-label={`${requests.length} pending requests`}
                  >
                    {requests.length}
                  </span>
                )}
            </Link>
          ))}
        </nav>
        <div className="paper-recent paper-sidebar-label">
          <h2>Recent</h2>
          {recentTitle ? (
            <Link
              className={`paper-recent-link${pathname === "/chat" ? " paper-nav-active" : ""}`}
              href="/chat"
              onClick={() => setMenuOpen(false)}
              title={recentTitle}
            >
              <ChatIcon name="chat" />
              <span>{recentTitle}</span>
            </Link>
          ) : (
            <p>No conversation yet</p>
          )}
          <p className="paper-history-note">
            Saved history <span>Coming soon</span>
          </p>
        </div>
        <div className="paper-sidebar-bottom">
          <button
            className="paper-nav-link"
            type="button"
            title="Settings and help"
            aria-label="Settings and help"
            onClick={(event) => openSettings(event.currentTarget)}
          >
            <ChatIcon name="settings" />
            <span className="paper-sidebar-label">Settings and help</span>
          </button>
        </div>
      </motion.aside>
      <div className="paper-main" inert={menuOpen}>
        <header className="paper-header">
          <button
            ref={menuButtonRef}
            className="paper-mobile-menu paper-icon-button"
            type="button"
            aria-label="Open navigation menu"
            aria-controls="workspace-navigation"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}
          >
            <ChatIcon name="menu" />
          </button>
          <div className="paper-product">
            <Link href="/chat">
              <WaliLogo className="paper-brand-logo" decorative />
              <span>Wali</span>
            </Link>
            <span className="paper-simulation">Simulation</span>
            <button
              className="paper-model-placeholder"
              type="button"
              disabled
              aria-label="Model selection, coming soon"
              title="Model selection: Coming soon"
            >
              <ChatIcon name="chevron" />
              <span>Coming soon</span>
            </button>
          </div>
          <button
            ref={avatarRef}
            className="paper-avatar"
            type="button"
            aria-haspopup="dialog"
            aria-expanded={settingsOpen}
            aria-controls="profile-settings"
            aria-label={`Settings, acting as ${role || "connecting"}`}
            title={`Acting as ${role || "connecting"}`}
            onClick={(event) =>
              settingsOpen ? closeSettings() : openSettings(event.currentTarget)
            }
          >
            {role ? role[0].toUpperCase() : "…"}
          </button>
          <AnimatePresence initial={false}>
            {settingsOpen && (
              <motion.div
                ref={settingsRef}
                id="profile-settings"
                className="paper-settings"
                role="dialog"
                aria-labelledby="settings-title"
                tabIndex={-1}
                initial={{
                  opacity: 0,
                  transform: "translateY(-8px) scale(0.98)",
                }}
                animate={{ opacity: 1, transform: "translateY(0px) scale(1)" }}
                exit={{ opacity: 0, transform: "translateY(-6px) scale(0.98)" }}
                transition={{
                  duration: reduceMotion ? 0 : 0.18,
                  ease: [0.22, 1, 0.36, 1],
                }}
                onBlur={(event) => {
                  if (
                    event.relatedTarget &&
                    !event.currentTarget.contains(event.relatedTarget) &&
                    event.relatedTarget !== avatarRef.current
                  )
                    closeSettings(false);
                }}
              >
                <div className="paper-settings-heading">
                  <div>
                    <h2 id="settings-title">Settings and help</h2>
                    <p>Wali workspace</p>
                  </div>
                  <button
                    className="paper-icon-button"
                    type="button"
                    aria-label="Close settings"
                    onClick={() => closeSettings()}
                  >
                    <ChatIcon name="close" />
                  </button>
                </div>
                <div className="paper-settings-role">
                  <label htmlFor="role-select">Acting as</label>
                  <select
                    id="role-select"
                    value={role}
                    disabled={!info || busy}
                    aria-describedby="role-help"
                    onChange={(event) => changeRole(event.target.value as Role)}
                  >
                    {!role && <option value="">Loading roles</option>}
                    {info?.roles.map((availableRole) => (
                      <option key={availableRole} value={availableRole}>
                        {availableRole}
                      </option>
                    ))}
                  </select>
                  <p id="role-help" className="paper-settings-note">
                    For testing, not a login. Switching roles clears the visible
                    conversation.
                  </p>
                </div>
                <section
                  className="paper-settings-simulation"
                  aria-label="Simulation information"
                >
                  <span className="paper-simulation">Local simulation</span>
                  <p>
                    {info?.simulation ||
                      "Synthetic data. No real bank or real money."}
                  </p>
                </section>
                <section
                  className="paper-settings-help"
                  aria-labelledby="wali-help-title"
                >
                  <h3 id="wali-help-title">Using Wali</h3>
                  <p>
                    Ask about transactions, cash flow, or invoices. Review
                    requests in Approvals before confirming. New chat resets
                    your current role’s conversation.
                  </p>
                  <p className="paper-settings-note">
                    Model selection, uploads, voice, feedback, regeneration, and
                    saved history are coming soon.
                  </p>
                </section>
              </motion.div>
            )}
          </AnimatePresence>
        </header>
        {pathname !== "/chat" && chatNotice?.tone === "error" && (
          <div className="paper-shell-notice notice notice-error" role="alert">
            {chatNotice.text}
          </div>
        )}
        <main id="main-content" className="paper-content" tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
