import { useState } from "react";
import { StyleSheet, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/auth/context";
import { Body, Button, Title } from "@/components/ui";
import { space, useColors } from "@/theme";

/** Signed in before, but the server cannot be reached: keep the session, offer to retry. */
export default function OfflineScreen() {
  const c = useColors();
  const { retry, logout } = useAuth();
  const [busy, setBusy] = useState(false);
  return (
    <SafeAreaView style={[styles.page, { backgroundColor: c.background }]}>
      <View style={styles.gap}>
        <Title>Cannot reach the server</Title>
        <Body muted>Check your internet connection. You are still signed in.</Body>
        <Button
          label="Try again"
          busy={busy}
          onPress={() => {
            setBusy(true);
            void retry().finally(() => {
              setBusy(false);
            });
          }}
        />
        <Button label="Sign out" variant="ghost" onPress={() => void logout()} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, justifyContent: "center", padding: space.xl },
  gap: { gap: space.lg },
});
