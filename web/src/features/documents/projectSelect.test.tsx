import { screen, waitFor } from "@testing-library/react";
import { delay } from "msw";

import { doc, DOC, PROJECT, useDoc } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

describe("bill editor (D.1)", () => {
  it("shows the bill's project even when the project list arrives late", async () => {
    useDoc(doc());
    server.use(
      http.get(`${API}/projects`, async () => {
        await delay(150); // after the form has been drawn
        return HttpResponse.json({
          results: [{ id: PROJECT, code: "VILLA-1", name: "Villa at Kakkanad" }],
          next_cursor: null,
        });
      }),
      http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
      http.get(`${API}/projects/:id/boq-items`, () =>
        HttpResponse.json({ results: [], next_cursor: null }),
      ),
      http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
    );
    renderSignedIn(`/documents/${DOC}/edit`);
    await waitFor(() => {
      expect(screen.getByLabelText("Project")).toHaveDisplayValue("VILLA-1 · Villa at Kakkanad");
    });
  });
});
