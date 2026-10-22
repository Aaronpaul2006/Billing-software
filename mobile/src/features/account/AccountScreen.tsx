import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, unwrap } from "@/api/client";
import { useAuth, useSession } from "@/auth/context";
import { Body, Button, Card, ErrorView } from "@/components/ui";
import { space, useColors } from "@/theme";

function roleName(role: string): string {
  return role.replace("_", " ").toLowerCase();
}

/** Who is signed in, the companies to switch between, and sign-out. */
export function AccountScreen() {
  const c = useColors();
  const router = useRouter();
  const session = useSession();
  const { switchTenant, logout } = useAuth();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me")),
  });
  const switching = useMutation({
    mutationFn: switchTenant,
    onSuccess: () => {
      router.dismissTo("/");
    },
  });

  return (
    <ScrollView style={{ backgroundColor: c.background }} contentContainerStyle={styles.page}>
      {me.data && (
        <Card>
          <Text style={[styles.name, { color: c.text }]}>{me.data.full_name}</Text>
          <Body muted>{me.data.email}</Body>
        </Card>
      )}
      <Text accessibilityRole="header" style={[styles.heading, { color: c.text }]}>
        Companies
      </Text>
      {switching.error && <ErrorView error={switching.error} />}
      <Card style={styles.list}>
        {session.tenants.map((t) => {
          const current = t.id === session.tenant_id;
          return (
            <Pressable
              key={t.id}
              accessibilityRole="button"
              accessibilityLabel={
                current ? `${t.legal_name}, current company` : `Switch to ${t.legal_name}`
              }
              accessibilityState={{ selected: current, disabled: current || switching.isPending }}
              disabled={current || switching.isPending}
              onPress={() => {
                switching.mutate(t.id);
              }}
              style={[styles.company, { borderColor: c.border }]}
            >
              <View style={styles.fill}>
                <Text style={[styles.name, { color: c.text }]}>{t.legal_name}</Text>
                <Text style={[styles.note, { color: c.muted }]}>{roleName(t.role)}</Text>
              </View>
              {current && <Text style={[styles.note, { color: c.primary }]}>Current</Text>}
            </Pressable>
          );
        })}
      </Card>
      <Button label="Sign out" variant="secondary" onPress={() => void logout()} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  page: { padding: space.lg, gap: space.md },
  heading: { fontSize: 18, fontWeight: "700", marginTop: space.sm },
  list: { paddingVertical: 0 },
  company: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  fill: { flex: 1 },
  name: { fontSize: 16, fontWeight: "600" },
  note: { fontSize: 13 },
});
