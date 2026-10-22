import { Alert } from "react-native";

/** Ask before an action that cannot be undone; runs `onConfirm` on yes. */
export function confirmAction(
  title: string,
  message: string,
  actionLabel: string,
  onConfirm: () => void,
): void {
  Alert.alert(title, message, [
    { text: "Not now", style: "cancel" },
    { text: actionLabel, onPress: onConfirm },
  ]);
}
