/**
 * Keyboard-first billing (B.4): Enter moves to the next field, like Tally.
 * Fields are the form's inputs, selects and text areas, in page order.
 */

const FIELDS =
  "input:not([type=hidden]):not([type=checkbox]):not([disabled]):not([readonly]), select:not([disabled])";

export function fieldsOf(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FIELDS)).filter(
    (el) => el.getAttribute("type") !== "file",
  );
}

/** Where Enter should go from `el`: "next" field, "next-line" or a "new-line". */
export function enterTarget(
  form: HTMLElement,
  el: HTMLElement,
): { kind: "field"; to: HTMLElement } | { kind: "new-line" } | null {
  const line = el.closest("fieldset[data-line]");
  if (line instanceof HTMLElement) {
    const inLine = fieldsOf(line);
    if (inLine.at(-1) === el) {
      const next = line.nextElementSibling;
      if (next instanceof HTMLElement && next.matches("fieldset[data-line]")) {
        const first = fieldsOf(next)[0];
        return first ? { kind: "field", to: first } : null;
      }
      return { kind: "new-line" }; // Enter on the last field of the last line
    }
  }
  const all = fieldsOf(form);
  const next = all[all.indexOf(el) + 1];
  return next ? { kind: "field", to: next } : null;
}

export const SHORTCUTS: { keys: string; what: string }[] = [
  { keys: "Enter", what: "Next box (at the end of the last line: a new line)" },
  { keys: "Alt + N", what: "Add a line" },
  { keys: "↑ ↓ then Enter", what: "Choose an item from the list" },
  { keys: "Ctrl + S", what: "Save the draft and keep working" },
  { keys: "Ctrl + Enter", what: "Save and open the bill to check and issue it" },
  { keys: "Esc", what: "Close a list or popup; otherwise leave the bill" },
  { keys: "Alt + /", what: "Show or hide these shortcuts" },
];
