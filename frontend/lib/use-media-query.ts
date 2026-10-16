"use client";

import { useCallback, useSyncExternalStore } from "react";

export function useMediaQuery(query: string, serverMatches = false) {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const preference = window.matchMedia(query);
      preference.addEventListener("change", onChange);
      return () => preference.removeEventListener("change", onChange);
    },
    [query],
  );
  const getSnapshot = useCallback(
    () => window.matchMedia(query).matches,
    [query],
  );
  const getServerSnapshot = useCallback(() => serverMatches, [serverMatches]);
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
