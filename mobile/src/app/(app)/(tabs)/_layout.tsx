import Ionicons from "@expo/vector-icons/Ionicons";
import { useRouter } from "expo-router";
import { Tabs } from "expo-router/js-tabs";
import type { BottomTabNavigationOptions } from "expo-router/js-tabs";
import type { ComponentProps } from "react";
import { Platform } from "react-native";

import { useSession } from "@/auth/context";
import { Button } from "@/components/ui";
import { useColors } from "@/theme";

type IconName = ComponentProps<typeof Ionicons>["name"];
type TabIcon = NonNullable<BottomTabNavigationOptions["tabBarIcon"]>;

function icon(name: IconName): TabIcon {
  function TabIcon({ color, size }: Parameters<TabIcon>[0]) {
    return (
      <Ionicons name={name} color={typeof color === "string" ? color : undefined} size={size} />
    );
  }
  return TabIcon;
}

export default function TabsLayout() {
  const c = useColors();
  const router = useRouter();
  const session = useSession();
  const company = session.tenants.find((t) => t.id === session.tenant_id)?.legal_name;
  const account = () => (
    <Button
      label="Account"
      variant="ghost"
      onPress={() => {
        router.push("/account");
      }}
    />
  );
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: c.primary,
        headerRight: account,
        // In a browser the default bar (sized for phones) cuts the labels off.
        ...(Platform.OS === "web" ? { tabBarStyle: { height: 64, paddingBottom: 8 } } : {}),
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          headerTitle: company ?? "Home",
          tabBarIcon: icon("home-outline"),
        }}
      />
      <Tabs.Screen
        name="bills"
        options={{ title: "Bills", tabBarIcon: icon("document-text-outline") }}
      />
      <Tabs.Screen
        name="payments"
        options={{ title: "Payments", tabBarIcon: icon("cash-outline") }}
      />
      <Tabs.Screen
        name="projects"
        options={{ title: "Projects", tabBarIcon: icon("business-outline") }}
      />
    </Tabs>
  );
}
