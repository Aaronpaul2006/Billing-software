import { authFetch } from "@/api/client";
import { API, http, HttpResponse, problem, server, tokens } from "@/test/server";

import { getAccessToken, refreshSession, setSession } from "./session";

describe("refreshSession", () => {
  it("sends one refresh for concurrent callers (the API treats two as token theft)", async () => {
    let calls = 0;
    server.use(
      http.post(`${API}/auth/token/refresh`, async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 20));
        return HttpResponse.json(tokens({ access_token: `access-${calls + 1}` }));
      }),
    );
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(calls).toBe(1);
    expect(results.map((s) => s?.access_token)).toEqual(["access-2", "access-2", "access-2"]);
    expect(getAccessToken()).toBe("access-2");
  });

  it("signs out when the server refuses the refresh", async () => {
    setSession(tokens());
    server.use(http.post(`${API}/auth/token/refresh`, () => problem(401, "refresh_token_reused")));
    expect(await refreshSession()).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("keeps the session through a network failure", async () => {
    setSession(tokens());
    server.use(http.post(`${API}/auth/token/refresh`, () => HttpResponse.error()));
    expect((await refreshSession())?.access_token).toBe("access-1");
    expect(getAccessToken()).toBe("access-1");
  });
});

describe("authFetch", () => {
  it("adds the token, and on token_expired refreshes once and retries", async () => {
    setSession(tokens({ access_token: "old" }));
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${API}/me`, ({ request }) => {
        const auth = request.headers.get("Authorization");
        seen.push(auth);
        return auth === "Bearer new"
          ? HttpResponse.json({ ok: true })
          : problem(401, "token_expired");
      }),
      http.post(`${API}/auth/token/refresh`, () =>
        HttpResponse.json(tokens({ access_token: "new" })),
      ),
    );
    const response = await authFetch(new Request(`${API}/me`));
    expect(response.status).toBe(200);
    expect(seen).toEqual(["Bearer old", "Bearer new"]);
  });

  it("does not retry other 401s (a revoked session stays revoked)", async () => {
    setSession(tokens());
    let refreshed = false;
    server.use(
      http.get(`${API}/me`, () => problem(401, "session_revoked")),
      http.post(`${API}/auth/token/refresh`, () => {
        refreshed = true;
        return HttpResponse.json(tokens());
      }),
    );
    expect((await authFetch(new Request(`${API}/me`))).status).toBe(401);
    expect(refreshed).toBe(false);
  });

  it("retries a POST with its body intact", async () => {
    setSession(tokens({ access_token: "old" }));
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/parties`, async ({ request }) => {
        bodies.push(await request.json());
        return request.headers.get("Authorization") === "Bearer new"
          ? HttpResponse.json({ id: "x" }, { status: 201 })
          : problem(401, "token_expired");
      }),
      http.post(`${API}/auth/token/refresh`, () =>
        HttpResponse.json(tokens({ access_token: "new" })),
      ),
    );
    const response = await authFetch(
      new Request(`${API}/parties`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: "Skyline" }),
      }),
    );
    expect(response.status).toBe(201);
    expect(bodies).toEqual([{ display_name: "Skyline" }, { display_name: "Skyline" }]);
  });
});
