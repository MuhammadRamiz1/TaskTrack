import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authFetch } from "@/lib/api/client";
import { getAccessToken, setAccessToken } from "@/lib/auth/token";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("authFetch", () => {
  beforeEach(() => {
    setAccessToken("old-token");
    document.cookie = "csrftoken=csrf123";
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the bearer token and CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await authFetch(new Request("http://localhost/api/v1/tasks/", { method: "POST", body: "{}" }));
    const sent = fetchMock.mock.calls[0][0] as Request;
    expect(sent.headers.get("Authorization")).toBe("Bearer old-token");
    expect(sent.headers.get("X-CSRFToken")).toBe("csrf123");
  });

  it("refreshes once on an expired token and retries with the new one", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: "token_expired", message: "Token expired." } }))
      .mockResolvedValueOnce(json(200, { access: "new-token", user: { id: "u1" } }))
      .mockResolvedValueOnce(json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await authFetch(new Request("http://localhost/api/v1/tasks/"));
    expect(res.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/auth/refresh/");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("Authorization")).toBe("Bearer new-token");
    expect(getAccessToken()).toBe("new-token");
  });

  it("does not retry a 403", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(403, { error: { code: "permission_denied", message: "No." } }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await authFetch(new Request("http://localhost/api/v1/hr/employees/"));
    expect(res.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears the in-memory token when the refresh fails", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(401, { error: { code: "session_revoked", message: "Ended." } }))
      .mockResolvedValueOnce(json(401, { error: { code: "session_revoked", message: "Ended." } }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await authFetch(new Request("http://localhost/api/v1/tasks/"));
    expect(res.status).toBe(401);
    expect(getAccessToken()).toBeNull();
  });
});
