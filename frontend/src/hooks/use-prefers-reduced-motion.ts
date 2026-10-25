"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const media = window.matchMedia(QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(QUERY).matches;
}

/**
 * Whether the user asked for reduced motion. The server snapshot is `true`, so the
 * server render is the static, complete view and animation only starts on the client.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => true);
}

function subscribeNothing(): () => void {
  return () => {};
}

/**
 * Whether `ResizeObserver` exists: in every supported browser, but not on the server
 * or in jsdom. React Flow measures its nodes with it.
 */
export function useHasResizeObserver(): boolean {
  return useSyncExternalStore(
    subscribeNothing,
    () => typeof ResizeObserver !== "undefined",
    () => false,
  );
}
