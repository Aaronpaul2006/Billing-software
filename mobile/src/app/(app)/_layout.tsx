import { Stack } from "expo-router";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth, useSession } from "@/auth/context";
import { Body, Button, Title } from "@/components/ui";
import { space, useColors } from "@/theme";

/** Owners and admins must turn on 2-step verification first; the app leaves that to the web. */
function FinishSetupOnWeb() {
  const c = useColors();
  const { logout } = useAuth();
  return (
    <SafeAreaView style={[styles.page, { backgroundColor: c.background }]}>
      <View style={styles.gap}>
        <Title>Turn on two-step verification</Title>
        <Body>
          Owners and admins need two-step verification. Turn it on in the web app (sign in there and
          follow the steps), then sign in here again.
        </Body>
        <Button label="Sign out" variant="secondary" onPress={() => void logout()} />
      </View>
    </SafeAreaView>
  );
}

/** The tabs, with the detail screens opening over them. */
export default function AppLayout() {
  const session = useSession();
  if (session.mfa_enrollment_required) return <FinishSetupOnWeb />;
  return (
    <Stack>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="account" options={{ title: "Account" }} />
      <Stack.Screen name="documents/[id]" options={{ title: "Bill" }} />
      <Stack.Screen name="clients/[id]" options={{ title: "Client" }} />
      <Stack.Screen name="projects/[id]" options={{ title: "Project" }} />
      <Stack.Screen name="payments/[id]" options={{ title: "Payment" }} />
      <Stack.Screen name="payments/new" options={{ title: "Record a payment" }} />
    </Stack>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "center", padding: space.xl },
  gap: { gap: space.lg },
});
