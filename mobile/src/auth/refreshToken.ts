/**
 * The refresh token, in the phone's secure storage (iOS Keychain / Android
 * Keystore), readable only while the phone is unlocked and never backed up
 * to another device. The access token is never stored: memory only.
 */

import * as SecureStore from "expo-secure-store";

const KEY = "billing.refresh_token";
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function readRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEY, OPTIONS);
}

export async function saveRefreshToken(token: string): Promise<void> {
  await SecureStore.setItemAsync(KEY, token, OPTIONS);
}

export async function forgetRefreshToken(): Promise<void> {
  await SecureStore.deleteItemAsync(KEY, OPTIONS);
}
