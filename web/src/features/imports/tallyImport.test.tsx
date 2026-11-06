import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const PREVIEW = {
  dry_run: true,
  clients: { new: 2, exists: 1, problems: 1 },
  vendors: { new: 1, exists: 0, problems: 0 },
  items: { new: 0, exists: 3, problems: 0 },
  other_ledgers: 38,
  rows: [
    {
      kind: "CLIENT",
      name: "Wrong GSTIN Builders",
      status: "PROBLEM",
      message: "GSTIN: This GSTIN is not valid.",
      detail: "32AAAAA0000A1Z0",
    },
    {
      kind: "CLIENT",
      name: "Skyline Developers",
      status: "NEW",
      message: "",
      detail: "32AAACS4321K1ZO · Kerala",
    },
    { kind: "ITEM", name: "OPC 53 Cement", status: "EXISTS", message: "Already here", detail: "" },
  ],
  added: null,
};

function file() {
  return new File(["<ENVELOPE/>"], "Master.xml", { type: "text/xml" });
}

describe("import from Tally (Part B)", () => {
  it("previews the file, then imports only the kinds chosen", async () => {
    const appended = vi.spyOn(FormData.prototype, "append");
    let imported = false;
    server.use(
      http.post(`${API}/tally-imports`, () => {
        const last = appended.mock.calls.filter((c) => c[0] === "dry_run").at(-1);
        const dryRun: unknown = last?.[1];
        if (dryRun === "true") return HttpResponse.json(PREVIEW);
        imported = true;
        return HttpResponse.json(
          { ...PREVIEW, dry_run: false, added: { CLIENT: 2, VENDOR: 0, ITEM: 0 } },
          { status: 201 },
        );
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/tally-import");
    await user.upload(await screen.findByLabelText("Tally masters file (XML)"), file());

    expect(await screen.findByText(/38 other ledgers/)).toBeInTheDocument();
    const clients = screen.getByRole("checkbox", { name: /Add 2 new clients/ });
    const vendors = screen.getByRole("checkbox", { name: /Add 1 new vendor/ });
    expect(clients).toBeChecked();
    expect(vendors).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Add 0 new items/ })).toBeDisabled();
    // problems are shown first
    const table = screen.getByRole("table", { name: "Masters in the file" });
    expect(within(table).getByText("GSTIN: This GSTIN is not valid.")).toBeInTheDocument();
    expect(within(table).queryByText("Skyline Developers")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Which masters to show"), "ALL");
    expect(within(table).getByText("Skyline Developers")).toBeInTheDocument();

    await user.click(vendors);
    appended.mockClear();
    await user.click(screen.getByRole("button", { name: "Import 2 masters" }));
    const result = (await screen.findByText("Imported: 2 clients")).closest(
      "[role=alert], [data-slot=alert]",
    ) as HTMLElement;
    expect(imported).toBe(true);
    const kinds = appended.mock.calls.filter((c) => c[0] === "kinds").map((c) => c[1]);
    expect(kinds).toEqual(["CLIENT"]);
    expect(within(result).getByRole("link", { name: "Clients & vendors" })).toHaveAttribute(
      "href",
      "/parties",
    );
  });

  it("says plainly when the file is not a Tally export", async () => {
    server.use(
      http.post(`${API}/tally-imports`, () =>
        HttpResponse.json(
          {
            type: "about:blank",
            title: "Invalid input",
            status: 422,
            code: "validation_error",
            errors: [{ field: "file", code: "not_tally_xml", message: "This is not an XML file." }],
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSignedIn("/tally-import");
    await user.upload(await screen.findByLabelText("Tally masters file (XML)"), file());
    await waitFor(() => {
      expect(screen.getByText(/Export the masters as XML \(Data Interchange\)/)).toBeVisible();
    });
  });
});
