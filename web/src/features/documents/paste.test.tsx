import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { components } from "@/api/schema";
import { CLIENT } from "@/test/documents";
import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, problem, server } from "@/test/server";

type ParsedLine = components["schemas"]["ParsedLine"];

function parsed(over: Partial<ParsedLine> = {}): ParsedLine {
  return {
    description: "Brickwork in CM 1:6",
    sac_hsn: "9954",
    unit: "sqm",
    quantity: "300.000",
    rate: "850.00",
    discount_amount: null,
    discount_pct: null,
    gst_rate: "18.00",
    ...over,
  };
}

function base() {
  server.use(
    http.get(`${API}/parties`, () =>
      HttpResponse.json({
        results: [{ id: CLIENT, display_name: "Skyline Developers", gstin: null }],
        next_cursor: null,
      }),
    ),
    http.get(`${API}/projects`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.get(`${API}/catalog-items`, () => HttpResponse.json({ results: [], next_cursor: null })),
    http.post(`${API}/documents:preview-totals`, () => problem(422, "validation_error")),
  );
}

function pasteInto(el: HTMLElement, text: string) {
  fireEvent.paste(el, { clipboardData: { getData: () => text } });
}

describe("lines from Excel", () => {
  it("pasting copied rows into an empty line makes the lines", async () => {
    base();
    const sent: unknown[] = [];
    server.use(
      http.post(`${API}/documents:parse-lines`, async ({ request }) => {
        sent.push(await request.json());
        return HttpResponse.json({
          dry_run: true,
          count: 2,
          skipped_rows: [],
          ignored_columns: [],
          lines: [
            parsed(),
            parsed({ description: "Plastering", quantity: "280.500", discount_pct: "5.00" }),
          ],
        });
      }),
    );
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    const cells = "Brickwork in CM 1:6\t300\tsqm\t850\nPlastering\t280.5\tsqm\t310";
    pasteInto(within(line).getByLabelText("Description"), cells);

    const second = await screen.findByRole("group", { name: "Line 2" });
    expect(sent).toEqual([{ text: cells }]);
    expect(
      within(screen.getByRole("group", { name: "Line 1" })).getByLabelText("Description"),
    ).toHaveValue("Brickwork in CM 1:6"); // the empty line was replaced
    expect(within(second).getByLabelText("Quantity")).toHaveValue("280.500");
    expect(within(second).getByLabelText("Discount")).toHaveValue("5.00");
    expect(within(second).getByLabelText("Discount of line 2 in")).toHaveValue("pct");
    expect(screen.queryByRole("group", { name: "Line 3" })).not.toBeInTheDocument();
  });

  it("names the rows that are wrong and adds nothing", async () => {
    base();
    server.use(
      http.post(`${API}/documents:parse-lines`, () =>
        HttpResponse.json(
          {
            type: "/errors/validation_error",
            title: "Invalid",
            status: 422,
            code: "validation_error",
            detail: "Check the rows.",
            request_id: null,
            errors: [{ field: "rows[2].rate", code: "required", message: "A rate is required." }],
          },
          { status: 422, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    pasteInto(within(line).getByLabelText("Description"), "A\t1\nB\t2");
    expect(await screen.findByText("Row 2 · Rate: A rate is required.")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Line 2" })).not.toBeInTheDocument();
  });

  it("a single value pastes as usual", async () => {
    base();
    let calls = 0;
    server.use(
      http.post(`${API}/documents:parse-lines`, () => {
        calls += 1;
        return HttpResponse.json({});
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    const line = await screen.findByRole("group", { name: "Line 1" });
    await user.click(within(line).getByLabelText("Description"));
    await user.paste("RCC work");
    expect(within(line).getByLabelText("Description")).toHaveValue("RCC work");
    expect(calls).toBe(0);
  });

  it("imports lines from a file and adds them", async () => {
    base();
    const nodeBuffer = "node:buffer";
    const { File: NodeFile } = (await import(/* @vite-ignore */ nodeBuffer)) as {
      File: typeof File;
    };
    server.use(
      http.post(`${API}/documents:parse-lines`, () =>
        HttpResponse.json({
          dry_run: true,
          count: 1,
          skipped_rows: [5],
          ignored_columns: [],
          lines: [parsed({ description: "Waterproofing", quantity: "40.000", rate: "220.00" })],
        }),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/documents/new");
    await user.click(await screen.findByRole("button", { name: "Import lines from Excel" }));
    const region = screen.getByRole("region", { name: "Import lines" });
    await user.upload(
      within(region).getByLabelText("Lines file (CSV or Excel)"),
      new NodeFile(["Description,Quantity\n"], "lines.csv", { type: "text/csv" }),
    );
    await user.click(within(region).getByRole("button", { name: "Check file" }));
    expect(await within(region).findByText("Waterproofing")).toBeInTheDocument();
    await user.click(within(region).getByRole("button", { name: "Import 1 line" }));
    await waitFor(() => {
      expect(
        within(screen.getByRole("group", { name: "Line 1" })).getByLabelText("Description"),
      ).toHaveValue("Waterproofing");
    });
  });
});
