import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";
const KEY = "axon.theme"; // index.html reads the same key before first paint

export const currentTheme = (): Theme =>
  document.documentElement.dataset.theme === "light" ? "light" : "dark";

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* the choice lasts for this tab only */
  }
}

/** The live theme, wherever it was changed from (rail button, command palette). */
export function useTheme(): Theme {
  return useSyncExternalStore((onChange) => {
    const observer = new MutationObserver(onChange);
    observer.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, currentTheme);
}
