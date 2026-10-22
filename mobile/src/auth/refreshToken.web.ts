/**
 * In a browser (trying the app on the PC with `expo start --web`) there is no
 * Keychain / Keystore: the refresh token stays in memory only, never in
 * localStorage, so reloading the page signs you out.
 */

let token: string | null = null;

export function readRefreshToken(): Promise<string | null> {
  return Promise.resolve(token);
}

export function saveRefreshToken(value: string): Promise<void> {
  token = value;
  return Promise.resolve();
}

export function forgetRefreshToken(): Promise<void> {
  token = null;
  return Promise.resolve();
}
