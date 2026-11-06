import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server, TENANT_B, tokens } from "@/test/server";

describe("switching company", () => {
  it("shows the other company's data, not what was on screen", async () => {
    server.use(
      http.get(`${API}/parties`, ({ request }) => {
        const second = request.headers.get("Authorization") === "Bearer access-2";
        return HttpResponse.json({
          results: [
            {
              id: second ? "p2" : "p1",
              display_name: second ? "Infra Client" : "Skyline Developers",
              legal_name: null,
              gstin: null,
              gst_treatment: "UNREGISTERED",
              state_code: "32",
              pan: null,
              email: null,
              phone: null,
              is_customer: true,
              is_vendor: false,
              is_active: true,
              version: 1,
              created_at: "",
              updated_at: "",
            },
          ],
          next_cursor: null,
        });
      }),
      http.post(`${API}/auth/switch-tenant`, () =>
        HttpResponse.json(tokens({ access_token: "access-2", tenant_id: TENANT_B })),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/parties");
    expect(await screen.findByText("Skyline Developers")).toBeInTheDocument();
    const nav = screen.getAllByRole("complementary")[0] ?? document.body;
    await user.click(within(nav).getByRole("button", { name: /, company$/ }));
    await user.click(await screen.findByRole("menuitemcheckbox", { name: /Nair Infra/ }));
    expect(await screen.findByText("Infra Client")).toBeInTheDocument();
    expect(screen.queryByText("Skyline Developers")).not.toBeInTheDocument();
  });
});
