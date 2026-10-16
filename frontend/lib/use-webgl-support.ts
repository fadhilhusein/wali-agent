"use client";

import { useEffect, useState } from "react";

let supported: boolean | undefined;

export function useWebGlSupport() {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (supported === undefined) {
        try {
          const context = document.createElement("canvas").getContext("webgl2");
          supported = !!context;
          context?.getExtension("WEBGL_lose_context")?.loseContext();
        } catch {
          supported = false;
        }
      }
      setAvailable(supported);
    });
    return () => cancelAnimationFrame(frame);
  }, []);
  return available;
}
