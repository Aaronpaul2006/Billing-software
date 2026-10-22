/**
 * Where the API is (no trailing slash): EXPO_PUBLIC_API_URL, set in
 * mobile/.env for development (see .env.example) and per build for releases.
 * Expo writes the value into the bundle at build time.
 */
const configured = process.env.EXPO_PUBLIC_API_URL as string | undefined;

export const API_URL = (configured ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
