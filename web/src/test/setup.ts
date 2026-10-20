import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";

import { resetSessionForTests } from "@/auth/session";

import { server } from "./server";

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
