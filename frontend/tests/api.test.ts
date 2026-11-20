import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, setCsrf } from "@/lib/api";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("api client", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    setCsrf("tok-123");
    fetchMock.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("sends the CSRF header on non-GET requests only", async () => {
    fetchMock.mockResolvedValue(json(200, []));
    await api.projects();
    expect(fetchMock.mock.calls[0]?.[1].headers["X-CSRF-Token"]).toBeUndefined();
    fetchMock.mockResolvedValue(json(201, {}));
    await api.chat({ project_id: "p", message: "hi" });
    const init = fetchMock.mock.calls[1]?.[1];
    expect(init.method).toBe("POST");
    expect(init.headers["X-CSRF-Token"]).toBe("tok-123");
    expect(init.credentials).toBe("same-origin");
  });

  it("stores the CSRF token returned by login", async () => {
    fetchMock.mockResolvedValue(json(200, { user: { id: "1" }, csrf_token: "fresh" }));
    await api.login("a@b.c", "pw");
    fetchMock.mockResolvedValue(json(201, {}));
    await api.chat({ project_id: "p", message: "x" });
    expect(fetchMock.mock.calls[1]?.[1].headers["X-CSRF-Token"]).toBe("fresh");
  });

  it("redirects to /login on 401 for normal calls, but not for login/me", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { assign });
    fetchMock.mockResolvedValue(json(401, { detail: { code: "not_authenticated", message: "Please sign in to continue." } }));
    await expect(api.projects()).rejects.toMatchObject({ status: 401, code: "not_authenticated" });
    expect(assign).toHaveBeenCalledWith("/login");
    assign.mockClear();
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    await expect(api.login("a", "b")).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });

  it("maps backend errors to ApiError with the backend message", async () => {
    fetchMock.mockResolvedValue(json(503, { detail: { code: "translation_unavailable", message: "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly." } }));
    const err = await api.translate({ project_id: "p", source_language: "en", target_language: "de", text: "x" }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    expect(err.message).toContain("couldn't complete the translation");
  });

  it("uses a generic message for non-JSON failures and network errors", async () => {
    fetchMock.mockResolvedValue(new Response("<html>boom</html>", { status: 500 }));
    const e1 = await api.projects().catch((e) => e);
    expect(e1.message).toBe("Something went wrong. Please try again shortly.");
    fetchMock.mockRejectedValue(new TypeError("failed"));
    const e2 = await api.projects().catch((e) => e);
    expect(e2).toMatchObject({ status: 0, code: "network_error" });
  });
});
