"use client";

import { MeshGradient } from "@paper-design/shaders-react";
import { useEffect, useState } from "react";
import { useMediaQuery } from "@/lib/use-media-query";

export default function PromptMesh({ active }: { active: boolean }) {
  const [intro, setIntro] = useState(true);
  const reducedMotion = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  useEffect(() => {
    const timer = window.setTimeout(() => setIntro(false), 1800);
    return () => window.clearTimeout(timer);
  }, []);
  const playing = !reducedMotion && (intro || active);
  return (
    <MeshGradient
      className="paper-prompt-mesh"
      data-playing={playing}
      speed={playing ? 1 : 0}
      scale={1}
      distortion={0.8}
      swirl={0.1}
      frame={24216.3}
      colors={["#E0EAFF", "#6B005F", "#F75092", "#9F50D3"]}
      minPixelRatio={1}
      maxPixelCount={60_000}
      style={{ width: "100%", height: "100%" }}
    />
  );
}
