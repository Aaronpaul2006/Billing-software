# Owner mobile app

Expo (SDK 58) + React Native + TypeScript, on the same REST API as the web app
(`docs/02-api-design.md`). Screens live in `src/app/` (expo-router: one file per
route); the code behind them in `src/features/`, `src/auth/`, `src/api/`, `src/lib/`.

## Run it on your phone (development)

1. Install **Expo Go** from the App Store / Play Store.
2. Start the API so the phone can reach it (same Wi-Fi as the PC):

   ```bash
   # in backend/, with your PC's address added to DJANGO_ALLOWED_HOSTS in .env
   uv run python manage.py runserver 0.0.0.0:8000
   ```

3. In `mobile/`: copy `.env.example` to `.env` and set `EXPO_PUBLIC_API_URL` to
   `http://<your PC's address>:8000`, then

   ```bash
   npm ci
   npx expo start            # scan the QR code with the camera (iOS) or Expo Go (Android)
   ```

Sign up and turn on two-step verification in the web app first: the app signs in
existing accounts only.

## Android test build (EAS)

Built in Expo's cloud (EAS); you get a link to an APK to install on the phone.
The app talks to the production API, so deploy that first
(`docs/03-operations.md`).

1. A free account at expo.dev. In `mobile/`: `npx eas-cli@latest login`
   (or set `EXPO_TOKEN` to a robot access token that may build).
2. Once: `npx eas-cli@latest init` links the project (adds its id to `app.json`).
3. The two build values for the `preview` environment (not secrets):

   ```bash
   npx eas-cli@latest env:create --environment preview --visibility plaintext --name APP_ID --value in.<company>.billing
   npx eas-cli@latest env:create --environment preview --visibility plaintext --name EXPO_PUBLIC_API_URL --value https://app.<company>.in
   ```

4. `npx eas-cli@latest build --platform android --profile preview`, then open
   the link on the phone and install (allow "install unknown apps").

`app.config.ts` stops the build when `APP_ID` is missing or the API address is
not `https://`. The app id cannot change once the app is on the Play Store; for
test APKs a new id only means installing again. Store builds use the
`production` profile (an app bundle for the Play Console).

## Checks (what CI runs)

```bash
npm run gen:api              # after backend/openapi.json changes
npm run format:check && npm run lint && npm run typecheck && npm test
npm run export:check         # Android + iOS bundles build
```

## Rules

- Money is a string from the API to the screen: format with `src/lib/money.ts`
  (a copy of the web's, same tests); never `parseFloat` / `Number()`.
- The refresh token lives only in the phone's secure storage
  (`src/auth/refreshToken.ts`: Keychain / Keystore, this device only); the access
  token only in memory. Refreshes go through `refreshSession()` (single flight:
  the API treats two refreshes with one token as theft).
- Tests render the real routes (`renderRouter`) against `src/test/api.ts`, a fetch
  stub that fails the test on any request no handler expected.
