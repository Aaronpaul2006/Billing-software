import { useSyncExternalStore } from "react";

/**
 * True while the media query matches (e.g. "(min-width: 1024px)"). Without
 * matchMedia (tests, very old browsers) it answers `fallback`.
 */
export function useMediaQuery(query: string, fallback = true): boolean {
  return useSyncExternalStore(
    (notify) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", notify);
      return () => {
        list.removeEventListener("change", notify);
      };
    },
    () => (typeof window.matchMedia === "function" ? window.matchMedia(query).matches : fallback),
    () => fallback,
  );
}

/** Wide enough for tables beside the sidebar; narrower screens get cards. */
export const WIDE = "(min-width: 1024px)";
