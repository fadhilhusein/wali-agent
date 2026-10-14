"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { Role } from "@/lib/wali-api";
import { useWorkspace } from "@/components/workspace-provider";

const destinations = [
  { href: "/chat", label: "Chat", mark: "↗" },
  { href: "/approvals", label: "Approvals", mark: "✓" },
  { href: "/mandate", label: "Mandate", mark: "≡" },
];

export function WorkspaceShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const {
    info,
    role,
    busy,
    resetting,
    requests,
    queueState,
    changeRole,
    resetConversation,
  } = useWorkspace();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const sidebar = sidebarRef.current;
    const focusables = () =>
      Array.from(
        sidebar?.querySelectorAll<HTMLElement>(
          "a[href], button:not([disabled]), select:not([disabled])",
        ) ?? [],
      );
    focusables()[0]?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
      if (event.key === "Tab") {
        const items = focusables();
        if (!items.length) return;
        if (event.shiftKey && document.activeElement === items[0]) {
          event.preventDefault();
          items[items.length - 1].focus();
        } else if (
          !event.shiftKey &&
          document.activeElement === items[items.length - 1]
        ) {
          event.preventDefault();
          items[0].focus();
        }
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  async function newChat() {
    setMenuOpen(false);
    await resetConversation();
    router.push("/chat");
  }

  return (
    <div className="app-shell">
      <div className="mobile-bar">
        <button
          ref={menuButtonRef}
          className="mobile-menu-button"
          type="button"
          aria-controls="workspace-navigation"
          aria-expanded={menuOpen}
          onClick={() => setMenuOpen(true)}
        >
          <span aria-hidden="true">☰</span> Menu
        </button>
        <span className="mobile-wordmark">Wali</span>
        <span className="mobile-page-name">
          {destinations.find((item) => item.href === pathname)?.label ??
            "Workspace"}
        </span>
      </div>
      {menuOpen && (
        <button
          className="sidebar-backdrop"
          type="button"
          tabIndex={-1}
          aria-label="Close menu"
          onClick={() => {
            setMenuOpen(false);
            menuButtonRef.current?.focus();
          }}
        />
      )}
      <aside
        ref={sidebarRef}
        id="workspace-navigation"
        className={`sidebar${menuOpen ? " sidebar-open" : ""}`}
        aria-label="Workspace navigation"
      >
        <div className="sidebar-top">
          <Link
            className="wordmark"
            href="/chat"
            onClick={() => setMenuOpen(false)}
            aria-label="Wali, open chat"
          >
            Wali
            <span className="wordmark-point" aria-hidden="true">
              .
            </span>
          </Link>
          <button
            className="sidebar-close"
            type="button"
            aria-label="Close menu"
            onClick={() => {
              setMenuOpen(false);
              menuButtonRef.current?.focus();
            }}
          >
            ×
          </button>
        </div>
        <div className="sidebar-project">
          Financial workspace <span className="sidebar-project-line" />
        </div>
        <button
          className="new-chat-button"
          type="button"
          disabled={!role || busy}
          onClick={() => void newChat()}
        >
          <span aria-hidden="true">＋</span>{" "}
          {resetting ? "Starting…" : "New chat"}
        </button>
        <nav className="sidebar-nav" aria-label="Pages">
          <p className="nav-caption">WORKSPACE</p>
          {destinations.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`nav-link${pathname === item.href ? " nav-link-active" : ""}`}
              aria-current={pathname === item.href ? "page" : undefined}
              onClick={() => setMenuOpen(false)}
            >
              <span className="nav-mark" aria-hidden="true">
                {item.mark}
              </span>
              <span>{item.label}</span>
              {item.href === "/approvals" && queueState === "ready" && (
                <span
                  className="nav-count"
                  aria-label={`${requests.length} pending`}
                >
                  {requests.length}
                </span>
              )}
            </Link>
          ))}
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-context">
          <span className="simulation-chip">
            <span className="simulation-dot" /> Local simulation
          </span>
          <p>This role selector is for testing. It is not a login.</p>
          <label htmlFor="role-select">Acting as</label>
          <select
            id="role-select"
            value={role}
            disabled={!info || busy}
            onChange={(event) => {
              changeRole(event.target.value as Role);
              setMenuOpen(false);
            }}
          >
            {!role && <option value="">Loading roles</option>}
            {info?.roles.map((availableRole) => (
              <option key={availableRole} value={availableRole}>
                {availableRole}
              </option>
            ))}
          </select>
        </div>
      </aside>
      <main id="main-content" className="main-panel">
        <motion.div
          key={pathname}
          className="page-transition"
          initial={reduceMotion ? false : { opacity: 0, y: 7 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.18 }}
        >
          {children}
        </motion.div>
      </main>
    </div>
  );
}
