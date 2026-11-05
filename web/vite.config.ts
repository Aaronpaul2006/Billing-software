/// <reference types="vitest/config" />
import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Django API runs on 127.0.0.1:8000 (127.0.0.1, not localhost: on Windows
// localhost resolves to IPv6 first). Proxying /api keeps the app and the API on
// one origin, so the HttpOnly refresh cookie (SameSite=Strict) just works.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // CI runners are several times slower than a desk PC: the longer bill-screen tests
    // (open a menu, fill a form, wait for the server) need more than the default 5 s.
    testTimeout: 20_000,
    css: false,
    restoreMocks: true,
  },
});
