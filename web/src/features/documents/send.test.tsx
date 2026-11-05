import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { doc, DOC, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

import { whatsappMessage, whatsappNumber } from "./sending";

const ISSUED = { status: "ISSUED" as const, doc_number: "INV/0001", due_date: "2026-11-18" };

function client(overrides: Record<string, unknown> = {}) {
  server.use(
    http.get(`${API}/parties/:id`, () =>
      HttpResponse.json({
        id: doc().party_id,
        display_name: "Skyline Developers",
        email: "accounts@skyline.example",
        phone: "98470 12345",
        ...overrides,
      }),
    ),
  );
}

function pdfServer(asked: string[]) {
  server.use(
    http.get(`${API}/documents/${DOC}/pdf`, ({ request }) => {
      asked.push(new URL(request.url).search);
      return new HttpResponse("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } });
    }),
  );
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:bill"), revokeObjectURL: vi.fn() });
}

describe("sending a bill", () => {
  it("emails the PDF to the client's address with a note", async () => {
    useDoc(doc(ISSUED));
    client();
    let body: unknown = null;
    let key: string | null = null;
    server.use(
      http.post(`${API}/documents/${DOC}/email`, async ({ request }) => {
        body = await request.json();
        key = request.headers.get("Idempotency-Key");
        return HttpResponse.json(
          {
            id: "e1",
            document_id: DOC,
            sent_to: "accounts@skyline.example",
            copy: "original",
            sent_by: "u1",
            sent_at: "2026-11-04T10:00:00Z",
          },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Email…" }));
    const form = screen.getByRole("form", { name: "Email the bill" });
    await waitFor(() => {
      expect(within(form).getByLabelText("To")).toHaveValue("accounts@skyline.example");
    });
    await user.type(within(form).getByLabelText("Note (optional)"), "RA bill 3.");
    await user.click(within(form).getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Sent to accounts@skyline.example.")).toBeInTheDocument();
    expect(body).toEqual({
      to: "accounts@skyline.example",
      copy: "original",
      message: "RA bill 3.",
    });
    expect(key).toBeTruthy();
  });

  it("WhatsApp: downloads the PDF and opens a ready message to the client", async () => {
    useDoc(doc(ISSUED));
    client();
    server.use(
      http.get(`${API}/tenant/print-settings`, () =>
        HttpResponse.json({ layout: "DETAILED", upi_id: "nair@okaxis", version: 2 }),
      ),
    );
    const asked: string[] = [];
    pdfServer(asked);
    const tab = { location: { href: "" }, close: vi.fn() };
    vi.spyOn(window, "open").mockReturnValue(tab as unknown as Window);
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "WhatsApp" }));
    await waitFor(() => {
      expect(tab.location.href).toMatch(/^https:\/\/wa\.me\/919847012345\?text=/);
    });
    const text = decodeURIComponent(tab.location.href.split("?text=")[1] ?? "");
    expect(text).toContain("Tax invoice INV/0001 dated 19 Oct 2026 for ₹3,23,680.00");
    expect(text).toContain("due on 18 Nov 2026");
    expect(text).toContain("Pay by UPI: nair@okaxis");
    expect(asked).toEqual(["?copy=original"]); // the PDF to attach
    expect(screen.getByText(/attach it in WhatsApp/)).toBeInTheDocument();
  });

  it("downloads the chosen copy", async () => {
    useDoc(doc(ISSUED));
    const asked: string[] = [];
    pdfServer(asked);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Copy to print" }),
      "Duplicate",
    );
    await user.click(screen.getByRole("button", { name: "Download" }));
    await waitFor(() => {
      expect(click).toHaveBeenCalled();
    });
    expect(asked).toEqual(["?copy=duplicate"]);
  });

  it("only those who issue bills may email them; drafts have none of this", async () => {
    useDoc(doc(ISSUED));
    renderSignedIn(`/documents/${DOC}`, { role: "VIEWER" }, { role: "VIEWER" });
    expect(await screen.findByRole("button", { name: "Print" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Email…" })).toBeNull();
  });

  it("phone numbers and the message", () => {
    expect(whatsappNumber("98470 12345")).toBe("919847012345");
    expect(whatsappNumber("098470-12345")).toBe("919847012345");
    expect(whatsappNumber("+91 98470 12345")).toBe("919847012345");
    expect(whatsappNumber(null)).toBe("");
    const credit = whatsappMessage(doc({ ...ISSUED, doc_type: "CREDIT_NOTE" }), "nair@okaxis");
    expect(credit).not.toContain("UPI");
  });
});
