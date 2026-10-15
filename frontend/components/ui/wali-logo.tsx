"use client";

import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import type { AnimationItem } from "lottie-web";
import animationData from "@/lib/wali-logo-animation.json";
import { useMediaQuery } from "@/lib/use-media-query";

export function WaliLogo({
  state = "idle",
  className = "",
  decorative = false,
}: {
  state?: "idle" | "processing" | "reply";
  className?: string;
  decorative?: boolean;
}) {
  const reduceMotion = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const containerRef = useRef<HTMLSpanElement>(null);
  const [playback, setPlayback] = useState("static");
  const shouldAnimate = state !== "idle" && !reduceMotion;

  useEffect(() => {
    const container = containerRef.current;
    if (!shouldAnimate || !container) return;
    let cancelled = false;
    let animation: AnimationItem | undefined;
    import("lottie-web/build/player/lottie_light")
      .then(({ default: lottie }) => {
        if (cancelled) return;
        animation = lottie.loadAnimation({
          container,
          renderer: "svg",
          autoplay: false,
          loop: state === "processing",
          animationData: structuredClone(animationData),
          rendererSettings: {
            viewBoxSize: "160 160 760 760",
            preserveAspectRatio: "xMidYMid meet",
          },
        });
        animation.addEventListener("DOMLoaded", () => {
          if (cancelled) return;
          setPlayback("playing");
          animation?.play();
        });
        animation.addEventListener("complete", () => {
          if (cancelled) return;
          animation?.goToAndStop(0, true);
          setPlayback("complete");
        });
        animation.addEventListener("data_failed", () => {
          if (!cancelled) setPlayback("error");
        });
        animation.addEventListener("error", () => {
          if (!cancelled) setPlayback("error");
        });
      })
      .catch(() => {
        if (!cancelled) setPlayback("error");
      });
    return () => {
      cancelled = true;
      animation?.destroy();
    };
  }, [shouldAnimate, state]);

  return (
    <span
      className={`wali-logo ${className}`}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "Wali"}
      aria-hidden={decorative ? true : undefined}
      data-playback={shouldAnimate ? playback : "static"}
    >
      <Image
        className="wali-logo-fallback"
        src="/brand/wali.svg"
        alt=""
        width={32}
        height={32}
        unoptimized
      />
      <span
        className="wali-logo-player"
        ref={containerRef}
        aria-hidden="true"
      />
    </span>
  );
}
