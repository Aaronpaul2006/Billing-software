import { Stack, useRouter } from "expo-router";
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

export default function AppLayout() {
  const session = useSession();
  const router = useRouter();
  if (session.mfa_enrollment_required) return <FinishSetupOnWeb />;
  const company = session.tenants.find((t) => t.id === session.tenant_id)?.legal_name;
  return (
    <Stack>
      <Stack.Screen
        name="index"
        options={{
          title: company ?? "Dashboard",
          headerRight: () => (
            <Button
              label="Account"
              variant="ghost"
              onPress={() => {
                router.push("/account");
              }}
            />
          ),
        }}
      />
      <Stack.Screen name="account" options={{ title: "Account" }} />
    </Stack>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "center", padding: space.xl },
  gap: { gap: space.lg },
});
