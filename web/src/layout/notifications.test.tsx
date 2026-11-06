import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderSignedIn } from "@/test/render";
import { API, http, HttpResponse, server } from "@/test/server";

const ITEM = {
  id: "n1",
  kind: "QUOTATION_ACCEPTED",
  title: "Skyline Developers accepted QT/0001",
  body: "Quotation for ₹3,41,020.00. Make the bill from it when the work starts.",
  link: "/documents/d1",
  read_at: null,
  created_at: "2026-11-06T10:00:00Z",
};

describe("notifications (Part B)", () => {
  it("shows the unread count, opens one and marks it read", async () => {
    let unread = 1;
    const marked: string[] = [];
    server.use(
      http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ count: unread })),
      http.get(`${API}/notifications`, () =>
        HttpResponse.json({ results: [ITEM], next_cursor: null }),
      ),
      http.post(`${API}/notifications/:id/read`, ({ params }) => {
        marked.push(String(params.id));
        unread = 0;
        return HttpResponse.json({ ...ITEM, read_at: "2026-11-06T10:05:00Z" });
      }),
    );
    const user = userEvent.setup();
    const router = renderSignedIn("/account");
    const bells = await screen.findAllByRole("button", { name: "Notifications, 1 unread" });
    await user.click(bells[0] as HTMLElement);
    await user.click(await screen.findByRole("menuitem", { name: /accepted QT\/0001/ }));
    await waitFor(() => {
      expect(marked).toEqual(["n1"]);
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/documents/d1");
    });
  });

  it("marks all read", async () => {
    let posted = false;
    server.use(
      http.get(`${API}/notifications/unread-count`, () =>
        HttpResponse.json({ count: posted ? 0 : 3 }),
      ),
      http.get(`${API}/notifications`, () =>
        HttpResponse.json({ results: [ITEM], next_cursor: null }),
      ),
      http.post(`${API}/notifications/read-all`, () => {
        posted = true;
        return HttpResponse.json({ count: 3 });
      }),
    );
    const user = userEvent.setup();
    renderSignedIn("/account");
    const bells = await screen.findAllByRole("button", { name: "Notifications, 3 unread" });
    await user.click(bells[0] as HTMLElement);
    await user.click(await screen.findByRole("menuitem", { name: "Mark all read" }));
    await waitFor(() => {
      expect(posted).toBe(true);
    });
    await user.keyboard("{Escape}");
    expect(
      (await screen.findAllByRole("button", { name: "Notifications" })).length,
    ).toBeGreaterThan(0);
  });
});
