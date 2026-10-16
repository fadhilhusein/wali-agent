"use client";

import { MeshGradient } from "@paper-design/shaders-react";
import { useEffect, useState } from "react";
import { useMediaQuery } from "@/lib/use-media-query";

export default function LandingMesh({ active }: { active: boolean }) {
  const [intro, setIntro] = useState(true);
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)", true);
  const mobile = useMediaQuery("(max-width: 760px)");
  useEffect(() => {
    const timer = window.setTimeout(() => setIntro(false), 1800);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <MeshGradient
      className="wl-mesh"
      speed={!reduced && (intro || active) ? 0.25 : 0}
      scale={1}
      distortion={0.8}
      swirl={0.1}
      frame={24216.3}
      colors={["#E0EAFF", "#6B005F", "#F75092", "#9F50D3"]}
      minPixelRatio={0.5}
      maxPixelCount={mobile ? 240_000 : 480_000}
      style={{ width: "100%", height: "100%" }}
    />
  );
}
