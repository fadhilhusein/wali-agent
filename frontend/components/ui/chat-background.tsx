"use client";

import dynamic from "next/dynamic";
import { useMediaQuery } from "@/lib/use-media-query";
import { useWebGlSupport } from "@/lib/use-webgl-support";

const GrainGradient = dynamic(() => import("./grain-gradient"), { ssr: false });

export function ChatBackground() {
  const supported = useWebGlSupport();
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const mobile = useMediaQuery("(max-width: 760px)");

  return (
    <div className="paper-chat-background" aria-hidden="true">
      {supported && (
        <GrainGradient
          className="paper-chat-grain"
          speed={reducedMotion ? 0 : mobile ? 0.07 : 0.12}
          frame={12}
          scale={1}
          rotation={0}
          offsetX={0}
          offsetY={0}
          softness={0.85}
          intensity={0.25}
          noise={0.08}
          shape="corners"
          colors={["#9673C6", "#D5A6DA", "#ACD6F1", "#AAA4DB"]}
          colorBack="#FFFFFF"
          minPixelRatio={1}
          maxPixelCount={mobile ? 240_000 : 480_000}
          style={{ width: "100%", height: "100%" }}
        />
      )}
    </div>
  );
}
