import { useColorScheme } from "react-native";

const light = {
  text: "#0a0a0a",
  muted: "#60646c",
  background: "#ffffff",
  card: "#f4f4f5",
  border: "#e4e4e7",
  primary: "#1d4ed8",
  primaryText: "#ffffff",
  danger: "#b91c1c",
  dangerBackground: "#fef2f2",
};

const dark: typeof light = {
  text: "#fafafa",
  muted: "#a1a1aa",
  background: "#09090b",
  card: "#18181b",
  border: "#27272a",
  primary: "#3b82f6",
  primaryText: "#ffffff",
  danger: "#f87171",
  dangerBackground: "#2a1215",
};

export type Colors = typeof light;

export function useColors(): Colors {
  return useColorScheme() === "dark" ? dark : light;
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;
