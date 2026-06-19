"use client";

import { useState, useEffect } from "react";

/**
 * useState that syncs to sessionStorage so data survives page navigation.
 * Handles Next.js hydration by using initial default on server,
 * then hydrating from sessionStorage in useEffect on the client.
 * Clears when the user explicitly calls setValue(null) or setValue(undefined).
 */
export function usePersistState<T>(key: string, initial: T): [T, (val: T | ((prev: T) => T)) => void, () => void] {
  const storageKey = `fb-scrape:${key}`;

  // Always start with initial to avoid hydration mismatch
  const [state, setState] = useState<T>(initial);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate from sessionStorage once on mount (client only)
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw !== null) {
        const parsed = JSON.parse(raw) as T;
        if (parsed !== null && parsed !== undefined) {
          setState(parsed);
        }
      }
    } catch {
      // ignore parse errors
    }
    setHydrated(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist to sessionStorage whenever state changes (after hydration)
  useEffect(() => {
    if (!hydrated) return;
    if (state === null || state === undefined || (Array.isArray(state) && state.length === 0)) {
      try {
        sessionStorage.removeItem(storageKey);
      } catch { /* ignore */ }
    } else {
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(state));
      } catch { /* quota exceeded */ }
    }
  }, [state, storageKey, hydrated]);

  const clear = () => {
    setState(initial);
    try {
      sessionStorage.removeItem(storageKey);
    } catch { /* ignore */ }
  };

  return [state, setState, clear];
}
