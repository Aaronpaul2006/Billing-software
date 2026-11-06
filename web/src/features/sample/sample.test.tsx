import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server, TENANT_A, TENANT_B, tokens } from "@/test/server";

const SAMPLE = "0192f5c4-0000-7000-8000-0000000000aa";

function tenant(isSample: boolean) {
  return HttpResponse.json({
    id: TENANT_A,
    legal_name: isSample ? "Sample: Green Valley Builders" : "Nair Constructions",
    trade_name: null,
    pan: null,
    status: "ACTIVE",
    plan: "FREE",
    timezone: "Asia/Kolkata",
    approval_limit: null,
    is_sample: isSample,
    version: 1,
    created_at: "",
    updated_at: "",
  });
}

describe("sample business (Part B)", () => {
  it("makes the sample business, waits for it, and opens it", async () => {
    let polls = 0;
    const switched: string[] = [];
    server.use(
      http.get(`${API}/tenant/setup`, () =>
        HttpResponse.json({
          gst_registration: false,
          number_series: false,
          client: false,
          project: false,
          first_bill: false,
          team: false,
          complete: false,
        }),
      ),
      http.post(`${API}/sample-business`, () =>
        HttpResponse.json({ status: "MAKING", tenant_id: null, legal_name: null }, { status: 202 }),
      ),
      http.get(`${API}/sample-business`, () => {
        polls += 1;
        return HttpResponse.json(
          polls < 2
            ? { status: "NONE", tenant_id: null, legal_name: null }
            : { status: "READY", tenant_id: SAMPLE, legal_name: "Sample: Green Valley Builders" },
        );
      }),
      http.post(`${API}/auth/switch-tenant`, async ({ request }) => {
        const body = (await request.json()) as { tenant_id: string };
        switched.push(body.tenant_id);
        return HttpResponse.json(tokens({ tenant_id: SAMPLE }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/");
    await user.click(await screen.findByRole("button", { name: "Explore with sample data" }));
    await waitFor(
      () => {
        expect(switched).toEqual([SAMPLE]);
      },
      { timeout: 8000 },
    );
  });

  it("in the sample: back to the real business, or remove it", async () => {
    const switched: string[] = [];
    let removed = false;
    server.use(
      http.get(`${API}/tenant`, () => tenant(true)),
      http.post(`${API}/sample-business/remove`, () => {
        removed = true;
        return new HttpResponse(null, { status: 204 });
      }),
      http.post(`${API}/auth/switch-tenant`, async ({ request }) => {
        const body = (await request.json()) as { tenant_id: string };
        switched.push(body.tenant_id);
        return HttpResponse.json(tokens({ tenant_id: body.tenant_id }));
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    const banner = await screen.findByRole("region", { name: "Sample business" });
    expect(banner).toHaveTextContent("nothing here is real");
    await user.click(screen.getByRole("button", { name: "Remove the sample" }));
    await waitFor(() => {
      expect(removed).toBe(true);
    });
    await waitFor(() => {
      expect(switched).toEqual([TENANT_B]); // the first business that is not this one
    });
  });

  it("no banner in a real business", async () => {
    server.use(http.get(`${API}/tenant`, () => tenant(false)));
    renderSignedIn("/account");
    expect(await screen.findByRole("heading", { name: "Your account" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Sample business" })).not.toBeInTheDocument();
  });
});
