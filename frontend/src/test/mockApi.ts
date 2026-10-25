import { vi } from "vitest";

export interface MockResponse {
  status?: number;
  body: unknown;
}
export type Handler = MockResponse | ((url: URL, init?: RequestInit) => MockResponse | Promise<MockResponse>);

export interface FetchMock {
  calls: Array<{ method: string; path: string; search: string; body?: unknown }>;
  count: (method: string, path: string) => number;
}

/** Stub global fetch with a route table keyed "METHOD /path". Unknown routes fail the test loudly. */
export function mockFetch(routes: Record<string, Handler>): FetchMock {
  const calls: FetchMock["calls"] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      calls.push({ method, path: url.pathname, search: url.search, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      const handler = routes[`${method} ${url.pathname}`];
      if (!handler) throw new Error(`Unmocked request: ${method} ${url.pathname}`);
      const r = typeof handler === "function" ? await handler(url, init) : handler;
      return new Response(JSON.stringify(r.body), { status: r.status ?? 200, headers: { "Content-Type": "application/json" } });
    }),
  );
  return {
    calls,
    count: (method, path) => calls.filter((c) => c.method === method && c.path === path).length,
  };
}

export const errorBody = (code: string, message: string) => ({ error: { code, message, details: {} } });
