import { screen } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** Open a page's "More" menu (D.8) and choose an item. */
export async function chooseMore(user: UserEvent, item: string | RegExp): Promise<void> {
  await user.click(await screen.findByRole("button", { name: "More" }));
  await user.click(await screen.findByRole("menuitem", { name: item }));
}
