import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api } from "./client";

function mockFetch(body: unknown, init: { status?: number; type?: string } = {}) {
  // Typed so `mock.calls[0][0]` is a string rather than never.
  const spy = vi.fn(async (_url: string) =>
    new Response(typeof body === "string" ? body : JSON.stringify(body), {
      status: init.status ?? 200,
      headers: { "content-type": init.type ?? "application/json" },
    }),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
}

function requestedUrl(spy: ReturnType<typeof mockFetch>): URL {
  return new URL(spy.mock.calls[0][0]);
}

afterEach(() => vi.unstubAllGlobals());

describe("as_of", () => {
  it("is sent on every read that is given one", async () => {
    const fetchSpy = mockFetch([]);

    await api.processes.list({ asOf: "2026-07-14T12:00:00Z" });

    expect(requestedUrl(fetchSpy).searchParams.get("as_of")).toBe(
      "2026-07-14T12:00:00Z",
    );
  });

  it("is omitted entirely when reading the present", async () => {
    // Not `as_of=` or `as_of=null` — the API treats an absent parameter as
    // "now", and an empty one would be a parse error.
    const fetchSpy = mockFetch([]);

    await api.processes.list();

    expect(requestedUrl(fetchSpy).searchParams.has("as_of")).toBe(false);
  });

  it("reaches nested resources, not only list endpoints", async () => {
    const fetchSpy = mockFetch([]);

    await api.processes.journal("abc", { asOf: "2026-07-14T12:00:00Z" });

    const url = requestedUrl(fetchSpy);
    expect(url.pathname).toBe("/api/processes/abc/journal");
    expect(url.searchParams.get("as_of")).toBe("2026-07-14T12:00:00Z");
  });
});

describe("query encoding", () => {
  it("repeats a key per array item so FastAPI reads a list", async () => {
    const fetchSpy = mockFetch([]);

    await api.processes.list({ query: { status: ["active", "dormant"] } });

    expect(requestedUrl(fetchSpy).searchParams.getAll("status")).toEqual([
      "active",
      "dormant",
    ]);
  });

  it("drops undefined and null rather than sending the words", async () => {
    const fetchSpy = mockFetch([]);

    await api.processes.list({
      query: { limit: 10, requires_review: undefined, archetype: null },
    });

    const params = requestedUrl(fetchSpy).searchParams;
    expect(params.get("limit")).toBe("10");
    expect(params.has("requires_review")).toBe(false);
    expect(params.has("archetype")).toBe(false);
  });

  it("keeps false, which is a filter value and not an absence", async () => {
    const fetchSpy = mockFetch([]);

    await api.processes.list({ query: { requires_review: false } });

    expect(requestedUrl(fetchSpy).searchParams.get("requires_review")).toBe(
      "false",
    );
  });
});

describe("errors", () => {
  it("carries the API's detail rather than a generic message", async () => {
    mockFetch({ detail: "process not found" }, { status: 404 });

    await expect(api.processes.get("missing")).rejects.toThrow(ApiError);
    await expect(api.processes.get("missing")).rejects.toMatchObject({
      status: 404,
      detail: "process not found",
    });
  });

  it("says it reached something other than the API when the body is not JSON", async () => {
    // The usual cause is a dev server proxying to nothing and returning HTML.
    // "undefined" would send someone looking in the wrong place.
    mockFetch("<!doctype html><title>502</title>", {
      status: 502,
      type: "text/html",
    });

    await expect(api.health()).rejects.toMatchObject({
      status: 502,
      detail: expect.stringContaining("text/html"),
    });
  });
});
