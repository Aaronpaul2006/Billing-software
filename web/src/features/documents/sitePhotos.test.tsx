import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DOC, doc, PROJECT, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const DAY = {
  id: "e1",
  version: 1,
  project_id: PROJECT,
  entry_date: "2026-10-15",
  weather: null,
  workers: null,
  work_done: "Slab",
  hold_ups: null,
  photos: [
    {
      id: "p1",
      attachment_id: "a1",
      caption: "Shuttering",
      url: "https://img.test/1.jpg",
      created_at: "",
    },
    {
      id: "p2",
      attachment_id: "a2",
      caption: "Concreting",
      url: "https://img.test/2.jpg",
      created_at: "",
    },
  ],
  written_by: "Ravi",
  created_at: "",
  updated_at: "",
};

describe("site photos with a bill (proof of work)", () => {
  it("chooses photos from the project's diary, in the order tapped", async () => {
    useDoc(doc({ status: "ISSUED" }));
    let sent: unknown = null;
    server.use(
      http.get(`${API}/projects/${PROJECT}/diary`, () =>
        HttpResponse.json({ results: [DAY], next_cursor: null }),
      ),
      http.put(`${API}/documents/${DOC}/photos`, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({
          results: [
            {
              id: "p2",
              caption: "Concreting",
              entry_date: "2026-10-15",
              url: "https://img.test/2.jpg",
            },
            {
              id: "p1",
              caption: "Shuttering",
              entry_date: "2026-10-15",
              url: "https://img.test/1.jpg",
            },
          ],
        });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn(`/documents/${DOC}`);
    await user.click(await screen.findByRole("button", { name: "Choose site photos…" }));
    const sheet = await screen.findByRole("dialog", { name: "Choose site photos" });
    await user.click(await within(sheet).findByRole("button", { name: "Concreting" }));
    await user.click(within(sheet).getByRole("button", { name: "Shuttering" }));
    expect(within(sheet).getByRole("button", { name: "Concreting" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(within(sheet).getByRole("button", { name: "Show 2 photos with the bill" }));
    await waitFor(() => {
      expect(sent).toEqual({ diary_photo_ids: ["p2", "p1"] });
    });
    const grid = await screen.findByRole("list", { name: "Site photos with this bill" });
    expect(
      within(grid)
        .getAllByRole("img")
        .map((i) => i.getAttribute("alt")),
    ).toEqual(["Concreting", "Shuttering"]);
  });

  it("a viewer sees nothing to choose when no photos are chosen", async () => {
    useDoc(doc({ status: "ISSUED" }));
    renderSignedIn(`/documents/${DOC}`, { role: "VIEWER" });
    expect(await screen.findByText("Place of supply")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose site photos…" })).not.toBeInTheDocument();
  });
});
