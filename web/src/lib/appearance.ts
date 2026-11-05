/**
 * Theme (system / light / dark) and text size (normal / large), chosen in the
 * user menu and remembered in this browser only (D.2). Storage may be blocked
 * (private windows, strict settings): every read and write is guarded, and the
 * defaults (follow the system, normal text) apply without it.
 */

export type ThemeChoice = "system" | "light" | "dark";
export type TextSize = "normal" | "large";

const THEME_KEY = "app.theme";
const TEXT_KEY = "app.textSize";

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // not remembered; the choice still applies until the page is closed
  }
}

export function themeChoice(): ThemeChoice {
  const value = read(THEME_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

export function textSize(): TextSize {
  return read(TEXT_KEY) === "large" ? "large" : "normal";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : false;
}

/** Put the choices on <html>: the "dark" and "text-large" classes drive the tokens in index.css. */
export function applyAppearance(): void {
  const choice = themeChoice();
  const dark = choice === "dark" || (choice === "system" && systemPrefersDark());
  const html = document.documentElement;
  html.classList.toggle("dark", dark);
  html.classList.toggle("text-large", textSize() === "large");
}

export function setThemeChoice(choice: ThemeChoice): void {
  write(THEME_KEY, choice);
  applyAppearance();
}

export function setTextSize(size: TextSize): void {
  write(TEXT_KEY, size);
  applyAppearance();
}

/** Once at start-up: apply the choices, and follow the system when it switches. */
export function startAppearance(): void {
  applyAppearance();
  if (typeof window.matchMedia === "function") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyAppearance);
  }
}
