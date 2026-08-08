import type { Ok } from "@/lib/api/client";

export type Subgraph = Ok<"/api/graph/subgraph">;

export type EntityType =
  | "document"
  | "claim"
  | "event"
  | "process"
  | "bottleneck"
  | "capability"
  | "asset";

export type RelationshipType =
  | "influences"
  | "creates"
  | "requires"
  | "expressed_by"
  | "affects"
  | "supports"
  | "contradicts"
  | "supersedes";

export interface GraphNode {
  id: string;
  type: EntityType;
  label: string;
  slug?: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  relationship: RelationshipType;
  weight: number;
  confidence: number;
  rationale?: string | null;
}

/**
 * Visual language per edge type (ui_concept §9.1: "the visual language should
 * make these distinctions clear").
 *
 * The distinction that carries meaning is *causal versus evidential*. `creates`,
 * `requires` and `expressed_by` are the structural chain — they are what the
 * graph is for. `supports` and `contradicts` are evidence pointing at a claim,
 * and `contradicts` is the only edge type that argues with the graph rather
 * than building it, so it is the only one drawn in the contradiction colour.
 */
export const EDGE_STYLE: Record<
  RelationshipType,
  { stroke: string; dashed: boolean; label: string }
> = {
  influences: { stroke: "var(--color-ink-subtle)", dashed: true, label: "influences" },
  creates: { stroke: "var(--color-accent)", dashed: false, label: "creates" },
  requires: { stroke: "var(--color-accent)", dashed: false, label: "requires" },
  expressed_by: { stroke: "var(--color-accent)", dashed: false, label: "expressed by" },
  affects: { stroke: "var(--color-ink-subtle)", dashed: true, label: "affects" },
  supports: { stroke: "var(--color-supports)", dashed: true, label: "supports" },
  contradicts: { stroke: "var(--color-contradicts)", dashed: true, label: "contradicts" },
  supersedes: { stroke: "var(--color-ink-subtle)", dashed: true, label: "supersedes" },
};

export const NODE_STYLE: Record<EntityType, { accent: string; abbr: string }> = {
  document: { accent: "var(--color-ink-subtle)", abbr: "DOC" },
  claim: { accent: "var(--color-ink-subtle)", abbr: "CLM" },
  event: { accent: "var(--color-ink-muted)", abbr: "EVT" },
  process: { accent: "var(--color-accent)", abbr: "PRC" },
  bottleneck: { accent: "var(--color-contradicts)", abbr: "BTL" },
  capability: { accent: "var(--color-estimated)", abbr: "CAP" },
  asset: { accent: "var(--color-supports)", abbr: "AST" },
};
