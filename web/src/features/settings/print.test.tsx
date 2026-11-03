import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

import { checkImage } from "./printSettings";

const STORAGE = "https://storage.example.test/bucket/tenants/t/uploads/1.png";

const DEFAULTS = {
  layout: "DETAILED",
  logo_attachment_id: null,
  signature_attachment_id: null,
  bank_account_name: null,
  bank_name: null,
  bank_account_number: null,
  bank_ifsc: null,
  bank_branch: null,
  upi_id: null,
  default_terms: null,
  version: 1,
};

function logo(status: string) {
  return {
    id: "logo1",
    filename: "logo.png",
    content_type: "image/png",
    size_bytes: 3,
    status,
    uploaded_by: "0192f5c4-0000-7000-8000-000000000002",
    created_at: "",
    download_url: status === "AVAILABLE" ? "https://storage.example.test/get/logo.png" : null,
  };
}

// Node's File, not jsdom's: in tests fetch comes from Node (see upload.test.tsx).
async function nodeFile(bytes: string, name: string, type: string): Promise<File> {
  const nodeBuffer = "node:buffer";
  const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
    File: typeof File;
  };
  return new NodeFile([bytes], name, { type });
}

describe("bill printing settings", () => {
  it("saves the layout, logo, bank details and UPI ID", async () => {
    const sent: { body?: Record<string, unknown>; match?: string | null } = {};
    server.use(
      http.post(`${API}/attachments`, () =>
        HttpResponse.json(
          {
            attachment: logo("PENDING"),
            upload_url: STORAGE,
            upload_headers: { "Content-Type": "image/png" },
            expires_in: 300,
          },
          { status: 201 },
        ),
      ),
      http.put(STORAGE, () => new HttpResponse(null, { status: 200 })),
      http.post(`${API}/attachments/logo1/complete`, () =>
        HttpResponse.json(logo("PENDING"), { status: 202 }),
      ),
      http.get(`${API}/attachments/logo1`, () => HttpResponse.json(logo("AVAILABLE"))),
      http.patch(`${API}/tenant/print-settings`, async ({ request }) => {
        sent.body = (await request.json()) as Record<string, unknown>;
        sent.match = request.headers.get("If-Match");
        return HttpResponse.json({ ...DEFAULTS, ...sent.body, version: 2 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/print");
    await user.click(await screen.findByRole("radio", { name: /Simple/ }));
    await user.upload(
      screen.getByLabelText("Logo"),
      await nodeFile("png", "logo.png", "image/png"),
    );
    expect(await screen.findByRole("img", { name: "Logo" })).toHaveAttribute(
      "src",
      "https://storage.example.test/get/logo.png",
    );
    await user.type(screen.getByLabelText("Account name"), "Nair Constructions");
    await user.type(screen.getByLabelText("Account number"), "301234567890");
    await user.type(screen.getByLabelText("IFSC"), "SBIN0070123");
    await user.type(screen.getByLabelText("UPI ID"), "nair@okaxis");
    await user.type(screen.getByLabelText("Terms on new bills and quotations"), "15 days.");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Saved\. New PDFs use these settings/)).toBeInTheDocument();
    expect(sent.match).toBe('"v1"');
    expect(sent.body).toEqual({
      layout: "SIMPLE",
      logo_attachment_id: "logo1",
      signature_attachment_id: null,
      bank_account_name: "Nair Constructions",
      bank_name: "",
      bank_account_number: "301234567890",
      bank_ifsc: "SBIN0070123",
      bank_branch: "",
      upi_id: "nair@okaxis",
      default_terms: "15 days.",
    });
  });

  it("shows a wrong IFSC next to the field", async () => {
    server.use(
      http.patch(`${API}/tenant/print-settings`, () =>
        HttpResponse.json(
          {
            type: "/errors/validation_error",
            title: "validation_error",
            status: 422,
            code: "validation_error",
            detail: "Check the fields.",
            request_id: null,
            errors: [
              {
                field: "bank_ifsc",
                code: "invalid_ifsc",
                message: "An IFSC is 11 characters, like SBIN0001234 (the 5th is a zero).",
              },
            ],
          },
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/settings/print");
    await user.type(await screen.findByLabelText("IFSC"), "SBIN1070123");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/the 5th is a zero/)).toBeInTheDocument();
    expect(screen.getByLabelText("IFSC")).toHaveAttribute("aria-invalid", "true");
  });

  it("a new bill starts with the default terms", async () => {
    server.use(
      http.get(`${API}/tenant/print-settings`, () =>
        HttpResponse.json({ ...DEFAULTS, default_terms: "Payment within 15 days." }),
      ),
      http.get(`${API}/parties`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    renderSignedIn("/documents/new");
    await waitFor(async () => {
      expect(await screen.findByLabelText("Terms")).toHaveValue("Payment within 15 days.");
    });
  });

  it("only small PNG or JPEG images", () => {
    expect(checkImage(new File(["%PDF"], "a.pdf", { type: "application/pdf" }))).toMatch(/PNG/);
    expect(checkImage(new File(["x"], "a.png", { type: "image/png" }))).toBeNull();
    const big = new File([new Uint8Array(1024 * 1024 + 1)], "big.jpg", { type: "image/jpeg" });
    expect(checkImage(big)).toMatch(/1 MB/);
  });
});
