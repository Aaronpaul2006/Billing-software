import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";

import { resetSessionForTests } from "@/auth/session";
import { AUTOSAVE } from "@/features/documents/autosave";

import { server } from "./server";

// Pages load lazily; with every test file running in parallel (and on a cold CI
// runner) the first import of a page can take over the default 1 s of findBy*.
configure({ asyncUtilTimeout: 5000 });

// jsdom lays nothing out, so it has no scrollIntoView (the command palette keeps
// the chosen row in view with it).
Element.prototype.scrollIntoView = () => undefined;

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" }); // an unmocked API call fails the test
});

beforeEach(() => {
  // drafts do not save themselves in tests, except where a test turns it on (autosave.test.tsx)
  AUTOSAVE.enabled = false;
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetSessionForTests();
});

afterAll(() => {
  server.close();
});
