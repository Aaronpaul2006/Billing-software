/**
 * Build-time settings on top of app.json. EAS cloud builds set
 * EAS_BUILD_PROFILE; a test or store build must name its app id and talk to
 * the real API over HTTPS, or the build stops here (never a test build that
 * quietly points at a developer's PC).
 *
 *   APP_ID               Android package / iOS bundle id, e.g. in.nairconstructions.billing
 *   EXPO_PUBLIC_API_URL  https://app.<company>.in (see .env.example for development)
 */

import type { ConfigContext, ExpoConfig } from "expo/config";

const DEV_APP_ID = "dev.billing.owner"; // Expo Go and local runs only

export default ({ config }: ConfigContext): ExpoConfig => {
  const profile = process.env.EAS_BUILD_PROFILE as string | undefined;
  const appId = process.env.APP_ID as string | undefined;
  const apiUrl = process.env.EXPO_PUBLIC_API_URL as string | undefined;
  if (profile && profile !== "development") {
    if (!appId)
      throw new Error(`Set APP_ID for "${profile}" builds (e.g. in.yourcompany.billing).`);
    if (!apiUrl?.startsWith("https://")) {
      throw new Error(
        `EXPO_PUBLIC_API_URL must be the https:// address of the API for "${profile}" builds (got ${apiUrl ?? "nothing"}).`,
      );
    }
  }
  return {
    ...config,
    name: config.name ?? "Billing",
    slug: config.slug ?? "billing-owner",
    android: { ...config.android, package: appId ?? DEV_APP_ID },
    ios: { ...config.ios, bundleIdentifier: appId ?? DEV_APP_ID },
  };
};
