import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import type { TextInputProps, ViewProps } from "react-native";

import { errorMessage } from "@/lib/errors";
import { space, useColors } from "@/theme";

export function Title({ children }: { children: string }) {
  const c = useColors();
  return (
    <Text accessibilityRole="header" style={[styles.title, { color: c.text }]}>
      {children}
    </Text>
  );
}

export function Body({ children, muted = false }: { children: React.ReactNode; muted?: boolean }) {
  const c = useColors();
  return <Text style={[styles.body, { color: muted ? c.muted : c.text }]}>{children}</Text>;
}

export function Button({
  label,
  onPress,
  disabled = false,
  busy = false,
  variant = "primary",
  accessibilityLabel,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  busy?: boolean;
  variant?: "primary" | "secondary" | "ghost";
  accessibilityLabel?: string;
}) {
  const c = useColors();
  const inactive = disabled || busy;
  const background =
    variant === "primary" ? c.primary : variant === "secondary" ? c.card : "transparent";
  const color = variant === "primary" ? c.primaryText : variant === "ghost" ? c.primary : c.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled: inactive, busy }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        { backgroundColor: background, opacity: inactive ? 0.5 : pressed ? 0.8 : 1 },
        variant === "secondary" && { borderColor: c.border, borderWidth: 1 },
      ]}
    >
      {busy ? (
        <ActivityIndicator color={color} />
      ) : (
        <Text style={[styles.buttonText, { color }]}>{label}</Text>
      )}
    </Pressable>
  );
}

export function TextField({
  label,
  error,
  hint,
  ...input
}: TextInputProps & { label: string; error?: string | undefined; hint?: string }) {
  const c = useColors();
  return (
    <View style={styles.field}>
      <Text style={[styles.label, { color: c.text }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        placeholderTextColor={c.muted}
        style={[
          styles.input,
          {
            color: c.text,
            borderColor: error ? c.danger : c.border,
            backgroundColor: c.background,
          },
        ]}
        {...input}
      />
      {error ? (
        <Text style={[styles.small, { color: c.danger }]}>{error}</Text>
      ) : hint ? (
        <Text style={[styles.small, { color: c.muted }]}>{hint}</Text>
      ) : null}
    </View>
  );
}

/** One choice out of a few, as a row of chips. */
export function Choice<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}) {
  const c = useColors();
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={styles.chips}>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <Pressable
            key={o.value}
            accessibilityRole="radio"
            accessibilityLabel={o.label}
            accessibilityState={{ checked: selected }}
            onPress={() => {
              onChange(o.value);
            }}
            style={[
              styles.chip,
              {
                backgroundColor: selected ? c.primary : c.card,
                borderColor: selected ? c.primary : c.border,
              },
            ]}
          >
            <Text style={[styles.small, { color: selected ? c.primaryText : c.text }]}>
              {o.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Card({ style, ...props }: ViewProps) {
  const c = useColors();
  return (
    <View
      style={[styles.card, { backgroundColor: c.card, borderColor: c.border }, style]}
      {...props}
    />
  );
}

export function Notice({ text, tone = "danger" }: { text: string; tone?: "danger" | "info" }) {
  const c = useColors();
  return (
    <View
      accessible
      accessibilityRole="alert"
      style={[
        styles.notice,
        tone === "danger"
          ? { backgroundColor: c.dangerBackground, borderColor: c.danger }
          : { backgroundColor: c.card, borderColor: c.border },
      ]}
    >
      <Text style={[styles.body, { color: tone === "danger" ? c.danger : c.text }]}>{text}</Text>
    </View>
  );
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <View style={styles.gap}>
      <Notice text={errorMessage(error)} />
      {onRetry && <Button label="Try again" variant="secondary" onPress={onRetry} />}
    </View>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <ActivityIndicator accessibilityLabel={label} style={styles.loading} />;
}

export const styles = StyleSheet.create({
  title: { fontSize: 24, fontWeight: "700" },
  body: { fontSize: 16, lineHeight: 22 },
  small: { fontSize: 13, lineHeight: 18 },
  label: { fontSize: 14, fontWeight: "600" },
  field: { gap: space.xs },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: space.md,
    paddingVertical: 10,
    fontSize: 16,
  },
  button: {
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: space.lg,
    alignItems: "center",
  },
  buttonText: { fontSize: 16, fontWeight: "600" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.sm },
  chip: { borderWidth: 1, borderRadius: 16, paddingVertical: 6, paddingHorizontal: space.md },
  card: { borderWidth: 1, borderRadius: 12, padding: space.lg, gap: space.xs },
  notice: { borderWidth: 1, borderRadius: 8, padding: space.md },
  gap: { gap: space.md },
  loading: { padding: space.xl },
});
