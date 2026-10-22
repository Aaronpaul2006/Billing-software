import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { useEffect, useState } from "react";
import { useColorScheme } from "react-native";

import { AuthProvider } from "@/auth/AuthProvider";
import { useAuth } from "@/auth/context";

void SplashScreen.preventAutoHideAsync(); // until we know whether someone is signed in

/** Which screens exist depends on the session: the router redirects to the first allowed one. */
function RootStack() {
  const { state } = useAuth();
  const ready = state.status !== "loading";
  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);
  if (!ready) return null;
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={state.status === "signed_in"}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
      <Stack.Protected guard={state.status === "signed_out"}>
        <Stack.Screen name="sign-in" />
      </Stack.Protected>
      <Stack.Protected guard={state.status === "offline"}>
        <Stack.Screen name="offline" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  const scheme = useColorScheme();
  const [queryClient] = useState(
    () =>
      new QueryClient({
        // one retry on a phone network; none in tests, so errors show at once
        defaultOptions: {
          queries: { retry: process.env.NODE_ENV === "test" ? false : 1, staleTime: 30_000 },
        },
      }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ThemeProvider value={scheme === "dark" ? DarkTheme : DefaultTheme}>
          <RootStack />
        </ThemeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
