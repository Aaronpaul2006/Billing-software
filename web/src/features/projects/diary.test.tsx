import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const PID = "0192f5c4-0000-7000-8000-0000000000p1";
const STORAGE = "https://storage.example.test/bucket/u/1.jpg";

const project = {
  id: PID,
  code: "VILLA-1",
  name: "Villa at Kakkanad",
  client_party_id: "c1",
  client_name: "Skyline Developers",
  gst_registration_id: "r1",
  site_address: null,
  site_state_code: "32",
  contract_value: "4500000.00",
  retention_pct: "5.00",
  income_tax_tds_pct: "1.00",
  gst_tds_applicable: false,
  mobilisation_advance: "0.00",
  advance_recovery_pct: "0.00",
  status: "ACTIVE",
  start_date: null,
  end_date: null,
  version: 1,
  created_at: "",
  updated_at: "",
};

function entry(over: Record<string, unknown> = {}) {
  return {
    id: "e1",
    version: 1,
    project_id: PID,
    entry_date: "2026-11-05",
    weather: "RAIN",
    workers: 14,
    work_done: "First floor slab shuttering",
    hold_ups: "Rain from 2 pm",
    photos: [
      {
        id: "ph1",
        attachment_id: "a0",
        caption: "Grid B",
        url: "https://img.test/1.jpg",
        created_at: "",
      },
    ],
    written_by: "Ravi",
    created_at: "",
    updated_at: "",
    ...over,
  };
}

// Node's File (fetch in tests is Node's, which cannot read a jsdom File).
async function nodeFile(bytes: string, name: string, type: string): Promise<File> {
  const nodeBuffer = "node:buffer";
  const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
    File: typeof File;
  };
  return new NodeFile([bytes], name, { type });
}

describe("site diary (Part B)", () => {
  it("shows the days with their photos", async () => {
    server.use(
      http.get(`${API}/projects/${PID}`, () => HttpResponse.json(project)),
      http.get(`${API}/projects/${PID}/diary`, () =>
        HttpResponse.json({ results: [entry()], next_cursor: null }),
      ),
    );
    renderSignedIn(`/projects/${PID}/diary`);
    expect(await screen.findByText("First floor slab shuttering")).toBeInTheDocument();
    expect(screen.getByText(/14 on site/)).toBeInTheDocument();
    expect(screen.getByText("Rain from 2 pm")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Grid B" })).toHaveAttribute(
      "src",
      "https://img.test/1.jpg",
    );
  });

  it("writes the day with a photo from the camera", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get(`${API}/projects/${PID}`, () => HttpResponse.json(project)),
      http.get(`${API}/projects/${PID}/diary`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.post(`${API}/attachments`, () =>
        HttpResponse.json(
          {
            attachment: { id: "a1", status: "PENDING" },
            upload_url: STORAGE,
            upload_headers: { "Content-Type": "image/jpeg" },
            expires_in: 300,
          },
          { status: 201 },
        ),
      ),
      http.put(STORAGE, () => new HttpResponse(null, { status: 200 })),
      http.post(`${API}/attachments/a1/complete`, () => HttpResponse.json({}, { status: 202 })),
      http.get(`${API}/attachments/a1`, () =>
        HttpResponse.json({ id: "a1", status: "AVAILABLE", download_url: STORAGE }),
      ),
      http.post(`${API}/projects/${PID}/diary`, async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(entry(), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/projects/${PID}/diary`);
    expect(await screen.findByText(/No diary yet/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Write today's diary" }));
    const form = screen.getByRole("form", { name: "Write the day" });
    await user.type(within(form).getByLabelText("Work done"), "Shuttering grids A to C");
    await user.type(within(form).getByLabelText("Workers on site"), "12");
    await user.selectOptions(within(form).getByLabelText("Weather"), "SUNNY");
    await user.upload(
      within(form).getByLabelText("Add photos"),
      await nodeFile("jpeg", "IMG_0001.jpg", "image/jpeg"),
    );
    await user.type(within(form).getByLabelText("Caption for photo 1"), "Grid A");
    await user.click(within(form).getByRole("button", { name: "Save the day" }));
    await waitFor(() => {
      expect(sent).toMatchObject({
        work_done: "Shuttering grids A to C",
        workers: 12,
        weather: "SUNNY",
        photos: [{ attachment_id: "a1", caption: "Grid A" }],
      });
    });
  });
});
