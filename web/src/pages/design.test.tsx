import { screen, within } from "@testing-library/react";

import { renderApp } from "@/test/render";

describe("/design style guide (D.3)", () => {
  it("shows every status and the shared components", async () => {
    renderApp("/design");
    expect(await screen.findByRole("heading", { name: "Design system" })).toBeInTheDocument();
    const statuses = screen.getByRole("region", { name: /Status badges/ });
    for (const word of ["Draft", "Issued", "Part paid", "Paid", "Overdue", "Cancelled"]) {
      expect(within(statuses).getByText(word)).toBeInTheDocument();
    }
    expect(screen.getByRole("region", { name: "Form section and Save bar" })).toBeInTheDocument();
  });
});
