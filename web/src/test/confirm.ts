import { screen, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** Answer the app's confirm dialog (D.3) by clicking one of its buttons. */
export async function answerConfirm(user: UserEvent, button: string | RegExp): Promise<void> {
  const dialog = await screen.findByRole("alertdialog");
  await user.click(within(dialog).getByRole("button", { name: button }));
}
