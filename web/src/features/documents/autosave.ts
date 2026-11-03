/**
 * Drafts save themselves (B.6): a moment after typing stops, the bill is sent
 * to the server, so nothing is lost if the browser closes. Tests turn it off
 * (src/test/setup.ts) unless they are about autosave.
 */
export const AUTOSAVE = { enabled: true, delayMs: 2000 };
