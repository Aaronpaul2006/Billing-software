/** In a browser React Native's Alert shows nothing: use the browser's own dialog. */
export function confirmAction(
  title: string,
  message: string,
  _actionLabel: string,
  onConfirm: () => void,
): void {
  if (window.confirm(`${title}\n\n${message}`)) onConfirm();
}
