"use client";

import Image from "next/image";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { animate } from "motion/react";
import { ChatIcon } from "@/components/ui/chat-icon";
import { useWebGlSupport } from "@/lib/use-webgl-support";

const LandingMesh = dynamic(() => import("./landing-mesh"), { ssr: false });
const links = [
  { href: "#capabilities", label: "Capabilities" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#simulation", label: "Simulation" },
];

export function LandingHeader() {
  const menuRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  useEffect(() => {
    function close(event: KeyboardEvent) {
      if (event.key === "Escape" && menuRef.current?.open) {
        menuRef.current.open = false;
        summaryRef.current?.focus();
      }
    }
    function outside(event: PointerEvent) {
      if (
        menuRef.current?.open &&
        !menuRef.current.contains(event.target as Node)
      )
        menuRef.current.open = false;
    }
    const wide = window.matchMedia("(min-width: 900px)");
    const resize = () => {
      if (wide.matches && menuRef.current) menuRef.current.open = false;
    };
    document.addEventListener("keydown", close);
    document.addEventListener("pointerdown", outside);
    wide.addEventListener("change", resize);
    return () => {
      document.removeEventListener("keydown", close);
      document.removeEventListener("pointerdown", outside);
      wide.removeEventListener("change", resize);
    };
  }, []);
  return (
    <header className="wl-header">
      <div className="wl-container wl-header-inner">
        <Link className="wl-brand" href="/" aria-label="Wali home">
          <Image src="/brand/wali.svg" alt="" width={28} height={28} priority />
          <span>Wali</span>
        </Link>
        <nav className="wl-desktop-nav" aria-label="Main navigation">
          {links.map((link) => (
            <a key={link.href} href={link.href}>
              {link.label}
            </a>
          ))}
        </nav>
        <div className="wl-header-actions">
          <Link className="wl-button wl-button-primary" href="/chat">
            Open Wali
          </Link>
          <details
            className="wl-mobile-menu"
            ref={menuRef}
            onBlur={(event) => {
              if (
                event.relatedTarget &&
                !event.currentTarget.contains(event.relatedTarget)
              )
                event.currentTarget.open = false;
            }}
          >
            <summary ref={summaryRef} aria-label="Navigation menu">
              <span className="wl-menu-open-icon">
                <ChatIcon name="menu" />
              </span>
              <span className="wl-menu-close-icon">
                <ChatIcon name="close" />
              </span>
            </summary>
            <nav aria-label="Mobile navigation">
              {links.map((link) => (
                <a
                  key={link.href}
                  href={link.href}
                  onClick={() => {
                    if (menuRef.current) menuRef.current.open = false;
                    requestAnimationFrame(() =>
                      summaryRef.current?.focus({ preventScroll: true }),
                    );
                  }}
                >
                  {link.label}
                </a>
              ))}
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}

export function LandingEntrance({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = root.current;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!node || preference.matches) return;
    const controls: Array<ReturnType<typeof animate>> = [];
    const finish = () => controls.forEach((control) => control.complete());
    const frame = requestAnimationFrame(() => {
      if (preference.matches) return;
      node
        .querySelectorAll<HTMLElement>("[data-landing-enter]")
        .forEach((element, index) =>
          controls.push(
            animate(
              element,
              {
                opacity: [0, 1],
                transform: ["translateY(12px)", "translateY(0px)"],
              },
              {
                duration: 0.45,
                delay: Math.min(index * 0.08, 0.24),
                ease: [0.22, 1, 0.36, 1],
              },
            ),
          ),
        );
    });
    const onPreference = () => {
      if (preference.matches) finish();
    };
    node.addEventListener("focusin", finish);
    node.addEventListener("pointerdown", finish);
    preference.addEventListener("change", onPreference);
    return () => {
      cancelAnimationFrame(frame);
      finish();
      node.removeEventListener("focusin", finish);
      node.removeEventListener("pointerdown", finish);
      preference.removeEventListener("change", onPreference);
    };
  }, []);
  return <div ref={root}>{children}</div>;
}

export function LandingHeroVisual({ children }: { children: ReactNode }) {
  const supported = useWebGlSupport();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <div
      className="wl-hero-visual"
      onPointerEnter={(event) => {
        if (event.pointerType === "mouse") setHovered(true);
      }}
      onPointerLeave={() => setHovered(false)}
      onPointerCancel={() => setHovered(false)}
      onFocusCapture={() => setFocused(true)}
      onBlurCapture={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget))
          setFocused(false);
      }}
    >
      <div className="wl-mesh-layer" aria-hidden="true">
        {supported && <LandingMesh active={hovered || focused} />}
      </div>
      {children}
    </div>
  );
}
