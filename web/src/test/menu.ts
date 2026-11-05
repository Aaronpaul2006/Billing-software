import { screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** Open a page's "More" menu (D.8) and choose an item. */
export async function chooseMore(user: UserEvent, item: string | RegExp): Promise<void> {
  await user.click(await screen.findByRole("button", { name: "More" }));
  await user.click(await screen.findByRole("menuitem", { name: item }));
}

/** A bill line's actions menu in the editor (D.9): "Move up", "Remove line"... */
export async function chooseLineAction(user: UserEvent, line: number, item: string): Promise<void> {
  await user.click(screen.getByRole("button", { name: `Actions for line ${String(line)}` }));
  await user.click(await screen.findByRole("menuitem", { name: item }));
}
