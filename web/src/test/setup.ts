import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";

import { resetSessionForTests } from "@/auth/session";

import { server } from "./server";

// Pages load lazily; with every test file running in parallel (and on a cold CI
// runner) the first import of a page can take over the default 1 s of findBy*.
configure({ asyncUtilTimeout: 5000 });

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" }); // an unmocked API call fails the test
});

afterEach(() => {
  cleanup();
  server.resetHandlers();
  resetSessionForTests();
});

afterAll(() => {
  server.close();
});
