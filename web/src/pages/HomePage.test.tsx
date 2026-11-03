import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BRAND } from "@/brand";
import { renderApp } from "@/test/render";

describe("public home page", () => {
  it("is what a visitor who is not signed in sees at /", async () => {
    renderApp("/");
    expect(await screen.findByRole("heading", { level: 1, name: BRAND.tagline })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Everything a construction business bills" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "RA bills against your BOQ" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "How it works" })).toBeVisible();
    expect(screen.getByText("Does it follow Indian GST rules?")).toBeVisible();

    const contact = screen.getByRole("region", { name: "Talk to us" });
    expect(within(contact).getByRole("link", { name: /WhatsApp/ })).toHaveAttribute(
      "href",
      `https://wa.me/${BRAND.contact.whatsapp}`,
    );
    expect(
      within(contact).getByRole("link", { name: new RegExp(BRAND.contact.email) }),
    ).toHaveAttribute("href", `mailto:${BRAND.contact.email}`);
  });

  it("leads to sign-up and sign-in", async () => {
    const user = userEvent.setup();
    const router = renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Home" });
    await user.click(within(nav).getByRole("link", { name: "Create your account" }));
    expect(await screen.findByRole("heading", { name: "Create your account" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/signup");
  });

  it("other pages still ask a visitor to sign in", async () => {
    const router = renderApp("/payments");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/login");
  });
});
