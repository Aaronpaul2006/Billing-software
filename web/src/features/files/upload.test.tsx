import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

import { checkFile } from "./upload";

type Attachment = components["schemas"]["Attachment"];

const STORAGE = "https://storage.example.test/bucket/tenants/t/uploads/1.jpg?X-Amz-Signature=abc";

function attachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    id: "a1",
    filename: "bill.jpg",
    content_type: "image/jpeg",
    size_bytes: 4,
    status: "PENDING",
    uploaded_by: "0192f5c4-0000-7000-8000-000000000002",
    created_at: "",
    download_url: null,
    ...overrides,
  };
}

// Node's File, not jsdom's: in tests fetch comes from Node, which cannot read a
// jsdom File. Browsers are fine.
async function nodeFile(bytes: string, name: string, type: string): Promise<File> {
  const nodeBuffer = "node:buffer";
  const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
    File: typeof File;
  };
  return new NodeFile([bytes], name, { type });
}

function storage(finalStatus: Attachment["status"], calls: string[]) {
  server.use(
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/attachments`, async ({ request }) => {
      calls.push(`start ${JSON.stringify(await request.json())}`);
      return HttpResponse.json(
        {
          attachment: attachment(),
          upload_url: STORAGE,
          upload_headers: { "Content-Type": "image/jpeg" },
          expires_in: 300,
        },
        { status: 201 },
      );
    }),
    http.put(STORAGE.split("?")[0] ?? "", async ({ request }) => {
      calls.push(
        `put ${request.headers.get("Content-Type") ?? ""} auth=${String(request.headers.has("Authorization"))} ${await request.text()}`,
      );
      return new HttpResponse(null, { status: 200 });
    }),
    http.post(`${API}/attachments/a1/complete`, () => {
      calls.push("complete");
      return HttpResponse.json(attachment(), { status: 202 });
    }),
    http.get(`${API}/attachments/a1`, () =>
      HttpResponse.json(
        attachment({
          status: finalStatus,
          download_url: finalStatus === "AVAILABLE" ? "https://storage.example.test/get" : null,
        }),
      ),
    ),
  );
}

describe("uploads", () => {
  it("attaches a bill to a new expense: start, PUT to storage, complete, checked", async () => {
    const calls: string[] = [];
    storage("AVAILABLE", calls);
    let body: Record<string, unknown> | null = null;
    server.use(
      http.post(`${API}/expenses`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({}, { status: 201 });
      }),
      http.get(`${API}/expenses`, () => HttpResponse.json({ results: [], next_cursor: null })),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/expenses/new");
    await user.upload(
      await screen.findByLabelText("Bill or receipt"),
      await nodeFile("jpeg", "bill.jpg", "image/jpeg"),
    );
    expect(await screen.findByRole("link", { name: "bill.jpg" })).toHaveAttribute(
      "href",
      "https://storage.example.test/get",
    );
    expect(calls).toEqual([
      'start {"filename":"bill.jpg","content_type":"image/jpeg","size_bytes":4}',
      "put image/jpeg auth=false jpeg",
      "complete",
    ]);

    await user.type(screen.getByLabelText("Description"), "Cement");
    await user.type(screen.getByLabelText("Amount before GST (₹)"), "100");
    await user.click(screen.getByRole("button", { name: "Record expense" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/expenses");
    });
    expect(body).toMatchObject({ attachment_id: "a1" });
  });

  it("explains a file the virus check rejected", async () => {
    const calls: string[] = [];
    storage("QUARANTINED", calls);
    const user = userEvent.setup();
    renderSignedIn("/expenses/new");
    await user.upload(
      await screen.findByLabelText("Bill or receipt"),
      await nodeFile("jpeg", "bill.jpg", "image/jpeg"),
    );
    expect(
      await screen.findByText("The file was rejected by the virus check."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "bill.jpg" })).not.toBeInTheDocument();
  });

  it("checks type and size before uploading", async () => {
    expect(checkFile(await nodeFile("x", "a.exe", "application/x-msdownload"))).toBe(
      "Choose a PDF or a photo (JPEG, PNG or WebP).",
    );
    expect(checkFile(await nodeFile("", "a.pdf", "application/pdf"))).toBe("The file is empty.");
    expect(checkFile(await nodeFile("%PDF", "a.pdf", "application/pdf"))).toBeNull();
  });
});
