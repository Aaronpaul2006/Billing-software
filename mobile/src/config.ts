import { Platform } from "react-native";

/**
 * Where the API is (no trailing slash): EXPO_PUBLIC_API_URL, set in
 * mobile/.env for development (see .env.example) and per build for releases.
 * Expo writes the value into the bundle at build time. In a browser on the PC
 * (`expo start --web`) the dev server passes /api to the API (metro.config.js),
 * so the app calls its own origin.
 */
const configured = process.env.EXPO_PUBLIC_API_URL as string | undefined;

export const API_URL =
  Platform.OS === "web" ? "" : (configured ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
