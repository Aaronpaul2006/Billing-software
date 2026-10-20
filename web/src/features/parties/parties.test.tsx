import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type Party = components["schemas"]["Party"];

const ID = "0192f5c4-0000-7000-8000-0000000000c1";

function party(overrides: Partial<Party> = {}): Party {
  return {
    id: ID,
    display_name: "Skyline Developers",
    legal_name: "Skyline Developers Pvt Ltd",
    is_customer: true,
    is_vendor: false,
    gst_treatment: "REGISTERED",
    gstin: "32AAACS4321K1Z5",
    pan: "AAACS4321K",
    state_code: "32",
    state_name: "Kerala",
    billing_address: {
      line1: "MG Road",
      city: "Kochi",
      state_code: "32",
      pincode: "682016",
      country: "IN",
    },
    email: null,
    phone: "9847012345",
    is_active: true,
    version: 3,
    created_at: "2026-10-19T10:00:00Z",
    updated_at: "2026-10-19T10:00:00Z",
    ...overrides,
  };
}

describe("parties list", () => {
  it("searches, filters and loads more", async () => {
    const user = userEvent.setup();
    const seen: URLSearchParams[] = [];
    server.use(
      http.get(`${API}/parties`, ({ request }) => {
        const q = new URL(request.url).searchParams;
        seen.push(q);
        if (q.get("cursor") === "page-2") {
          return HttpResponse.json({
            results: [party({ id: "p2", display_name: "Coastal Cement", is_vendor: true })],
            next_cursor: null,
          });
        }
        return HttpResponse.json({ results: [party()], next_cursor: "page-2" });
      }),
    );
    renderSignedIn("/parties");
    expect(await screen.findByRole("link", { name: "Skyline Developers" })).toBeInTheDocument();
    expect(screen.getByText("32AAACS4321K1Z5")).toBeInTheDocument();
    expect(seen[0]?.get("is_active")).toBe("true");

    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByRole("link", { name: "Coastal Cement" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Search parties"), "sky");
    await waitFor(() => {
      expect(seen.at(-1)?.get("q")).toBe("sky");
    });
    await user.selectOptions(screen.getByLabelText("Show"), "vendors");
    await waitFor(() => {
      expect(seen.at(-1)?.get("is_vendor")).toBe("true");
    });
  });
});

describe("party form", () => {
  it("creates a party with one Idempotency-Key and opens it", async () => {
    const user = userEvent.setup();
    const posts: { key: string | null; body: unknown }[] = [];
    server.use(
      http.post(`${API}/parties`, async ({ request }) => {
        const body = await request.json();
        posts.push({ key: request.headers.get("Idempotency-Key"), body });
        if (posts.length === 1) {
          return HttpResponse.json(
            {
              type: "/errors/validation_error",
              title: "Validation failed",
              status: 422,
              code: "validation_error",
              detail: "1 field is invalid.",
              errors: [{ field: "gstin", code: "invalid_gstin", message: "Check digit is wrong." }],
            },
            { status: 422 },
          );
        }
        return HttpResponse.json(party({ id: "new-id" }), { status: 201 });
      }),
      http.get(`${API}/parties/new-id`, () => HttpResponse.json(party({ id: "new-id" }))),
    );
    const router = renderSignedIn("/parties/new");
    await user.type(await screen.findByLabelText("Name"), "Skyline Developers");
    await user.click(screen.getByRole("button", { name: "Create party" }));
    expect(await screen.findByText("This party needs its GSTIN.")).toBeInTheDocument();
    expect(posts).toHaveLength(0); // checked before sending

    await user.type(screen.getByLabelText("GSTIN"), "32aaacs4321k1z4");
    await user.click(screen.getByRole("button", { name: "Create party" }));
    expect(await screen.findByText("Check digit is wrong.")).toBeInTheDocument();
    expect(posts[0]?.body).toMatchObject({
      display_name: "Skyline Developers",
      gst_treatment: "REGISTERED",
      gstin: "32AAACS4321K1Z4",
      pan: null,
      state_code: null,
      billing_address: null,
      is_customer: true,
    });

    await user.clear(screen.getByLabelText("GSTIN"));
    await user.type(screen.getByLabelText("GSTIN"), "32AAACS4321K1Z5");
    await user.click(screen.getByRole("button", { name: "Create party" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/parties/new-id");
    });
    expect(posts[0]?.key).toMatch(/^[0-9a-f-]{36}$/); // sent at all
    expect(posts[1]?.key).toBe(posts[0]?.key); // the same action, retried
  });

  it("saves with If-Match and explains a conflicting edit", async () => {
    const user = userEvent.setup();
    let ifMatch: string | null = null;
    let version = 3;
    server.use(
      http.get(`${API}/parties/${ID}`, () => HttpResponse.json(party({ version }))),
      http.patch(`${API}/parties/${ID}`, ({ request }) => {
        ifMatch = request.headers.get("If-Match");
        return problem(412, "stale_version", "This was changed by someone else.");
      }),
    );
    renderSignedIn(`/parties/${ID}`);
    const phone = await screen.findByLabelText("Phone");
    expect(phone).toHaveValue("9847012345");
    await user.clear(phone);
    await user.type(phone, "9847000000");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Someone else changed this party/)).toBeInTheDocument();
    expect(ifMatch).toBe('"v3"');

    version = 4;
    await user.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Phone")).toHaveValue("9847012345");
    });
  });

  it("archives and restores", async () => {
    const user = userEvent.setup();
    const bodies: unknown[] = [];
    server.use(
      http.get(`${API}/parties/${ID}`, () => HttpResponse.json(party())),
      http.patch(`${API}/parties/${ID}`, async ({ request }) => {
        const body = (await request.json()) as { is_active: boolean };
        bodies.push(body);
        return HttpResponse.json(party({ is_active: body.is_active, version: 4 }));
      }),
    );
    renderSignedIn(`/parties/${ID}`);
    await user.click(await screen.findByRole("button", { name: "Archive" }));
    expect(await screen.findByText("Archived.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(bodies).toEqual([{ is_active: false }]);
  });
});
