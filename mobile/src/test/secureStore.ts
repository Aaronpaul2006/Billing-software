/** expo-secure-store in memory, for tests (the real one needs the phone's keychain). */

export const secureStore = new Map<string, string>();

export const mockModule = {
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 5,
  getItemAsync: (key: string) => Promise.resolve(secureStore.get(key) ?? null),
  setItemAsync: (key: string, value: string) => {
    secureStore.set(key, value);
    return Promise.resolve();
  },
  deleteItemAsync: (key: string) => {
    secureStore.delete(key);
    return Promise.resolve();
  },
};
