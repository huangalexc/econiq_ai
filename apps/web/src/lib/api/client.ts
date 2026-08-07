/**
 * Typed client over the domain API.
 *
 * Every type here comes from `schema.d.ts`, which is generated from the
 * FastAPI OpenAPI document (`npm run api:types`). Nothing about the response
 * shape is written by hand, so a field the API renames breaks the build rather
 * than rendering as `undefined`.
 *
 * The one piece of behaviour this file adds is `asOf`. Every read in the domain
 * API accepts a point-in-time cut-off, and the terminal is expected to be able
 * to answer "what did the system believe on July 14?" (ui_concept §32). That
 * only works if the cut-off is threaded through *every* request rather than
 * remembered per screen, so it lives in the client and not in the call sites.
 */

import type { paths } from "./schema";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly path: string,
  ) {
    super(`${status} on ${path}: ${detail}`);
    this.name = "ApiError";
  }
}

export type Query = Record<
  string,
  string | number | boolean | string[] | null | undefined
>;

export interface RequestOptions {
  query?: Query;
  /**
   * Reconstruct the graph as it was at this instant. Omitted means now.
   *
   * Carried as an explicit argument rather than read from a module-level
   * variable: a stale global cut-off would silently serve historical data as
   * current, which is the one failure mode this whole mechanism exists to
   * prevent.
   */
  asOf?: string | null;
  signal?: AbortSignal;
}

function buildQuery(query: Query | undefined, asOf: string | null | undefined) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === null || value === undefined) continue;
    // FastAPI reads repeated keys as a list; a comma-joined string would be
    // one value containing a comma.
    if (Array.isArray(value)) {
      for (const item of value) params.append(key, String(item));
    } else {
      params.append(key, String(value));
    }
  }
  if (asOf) params.set("as_of", asOf);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = `${API_BASE_URL}${path}${buildQuery(options.query, options.asOf)}`;
  const response = await fetch(url, {
    signal: options.signal,
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    // The API returns `{detail: …}`; anything else means we are not talking to
    // the API at all, and saying so beats reporting "undefined".
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      detail = `non-JSON response (${response.headers.get("content-type") ?? "unknown"})`;
    }
    throw new ApiError(response.status, detail, path);
  }

  return (await response.json()) as T;
}

/** Response body of a GET path, straight from the generated schema. */
type Ok<P extends keyof paths> = paths[P] extends {
  get: { responses: { 200: { content: { "application/json": infer R } } } };
}
  ? R
  : never;

export const api = {
  health: (options?: RequestOptions) => request<Ok<"/health">>("/health", options),

  processes: {
    list: (options?: RequestOptions) =>
      request<Ok<"/api/processes">>("/api/processes", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/processes/{process_id}">>(`/api/processes/${id}`, options),
    states: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/processes/{process_id}/states">>(
        `/api/processes/${id}/states`,
        options,
      ),
    journal: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/processes/{process_id}/journal">>(
        `/api/processes/${id}/journal`,
        options,
      ),
    critiques: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/processes/{process_id}/critiques">>(
        `/api/processes/${id}/critiques`,
        options,
      ),
  },

  events: {
    list: (options?: RequestOptions) =>
      request<Ok<"/api/events">>("/api/events", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/events/{event_id}">>(`/api/events/${id}`, options),
  },

  bottlenecks: {
    list: (options?: RequestOptions) =>
      request<Ok<"/api/bottlenecks">>("/api/bottlenecks", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/bottlenecks/{bottleneck_id}">>(
        `/api/bottlenecks/${id}`,
        options,
      ),
    requirements: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/bottlenecks/{bottleneck_id}/requirements">>(
        `/api/bottlenecks/${id}/requirements`,
        options,
      ),
  },

  capabilities: {
    list: (options?: RequestOptions) =>
      request<Ok<"/api/capabilities">>("/api/capabilities", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/capabilities/{capability_id}">>(
        `/api/capabilities/${id}`,
        options,
      ),
  },

  assets: {
    list: (options?: RequestOptions) =>
      request<Ok<"/api/assets">>("/api/assets", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/assets/{asset_id}">>(`/api/assets/${id}`, options),
  },

  graph: {
    subgraph: (options?: RequestOptions) =>
      request<Ok<"/api/graph/subgraph">>("/api/graph/subgraph", options),
    reach: (options?: RequestOptions) =>
      request<Ok<"/api/graph/reach">>("/api/graph/reach", options),
    paths: (options?: RequestOptions) =>
      request<Ok<"/api/graph/paths">>("/api/graph/paths", options),
    integrity: (options?: RequestOptions) =>
      request<Ok<"/api/graph/integrity">>("/api/graph/integrity", options),
  },

  /** The chain from Process to instrument, which is what makes an Asset
      explainable rather than merely listed (ui_concept §12). */
  discoveryChain: (assetId: string, options?: RequestOptions) =>
    request<Ok<"/api/assets/{asset_id}/discovery-chain">>(
      `/api/assets/${assetId}/discovery-chain`,
      options,
    ),

  evidence: (nodeId: string, options?: RequestOptions) =>
    request<Ok<"/api/evidence/{node_id}">>(`/api/evidence/${nodeId}`, options),

  scores: (subjectId: string, options?: RequestOptions) =>
    request<Ok<"/api/scores/{subject_id}">>(`/api/scores/${subjectId}`, options),

  runs: {
    list: (options?: RequestOptions) => request<Ok<"/api/runs">>("/api/runs", options),
    get: (id: string, options?: RequestOptions) =>
      request<Ok<"/api/runs/{run_id}">>(`/api/runs/${id}`, options),
  },

  pipeline: {
    stages: (options?: RequestOptions) =>
      request<Ok<"/api/pipeline">>("/api/pipeline", options),
    queue: (options?: RequestOptions) =>
      request<Ok<"/api/pipeline/queue">>("/api/pipeline/queue", options),
  },
};

export type ProcessSummary = Ok<"/api/processes">[number];
export type ProcessDetail = Ok<"/api/processes/{process_id}">;
export type EventSummary = Ok<"/api/events">[number];
export type BottleneckSummary = Ok<"/api/bottlenecks">[number];
export type CapabilitySummary = Ok<"/api/capabilities">[number];
export type AssetSummary = Ok<"/api/assets">[number];
