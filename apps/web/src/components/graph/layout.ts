/**
 * Layout for the dependency graph (issue #26, ui_concept §9).
 *
 * **The ontology is the layout.** §9 gives a fixed hierarchy — upstream
 * Processes, then Process, Bottleneck, Capability, Asset — and `ALLOWED_EDGES`
 * makes that hierarchy structural rather than conventional: a Bottleneck cannot
 * point at an Asset, so the layers cannot interleave. Placing nodes in columns
 * by entity type therefore encodes real information, and it has two properties
 * a force-directed layout does not:
 *
 * * **Deterministic.** The same graph draws identically every time. A force
 *   layout settles differently on each render, so a user who expands a node
 *   loses the mental map they had just built of the rest.
 * * **Confluence is visible by construction.** Several Processes in the first
 *   column converging on one Capability in the third *is* the picture ontology
 *   §13 is about, and a layout that optimised for edge crossings would scatter
 *   them.
 *
 * Nothing here needs a layout library, which is the point of §28's "avoid
 * introducing custom visualization types for every feature".
 */

import type { EntityType, GraphEdge, GraphNode } from "./types";

/** Column order, straight from ui_concept §9's hierarchy. */
export const LAYERS: EntityType[] = [
  "event",
  "process",
  "bottleneck",
  "capability",
  "asset",
];

const COLUMN_WIDTH = 260;
const ROW_HEIGHT = 92;

export interface Positioned {
  id: string;
  position: { x: number; y: number };
}

/**
 * Place nodes in columns by type, ordered within a column to keep the edges
 * that cross between columns as short as we can manage in one pass.
 *
 * The ordering heuristic is the barycentre of a node's neighbours in the
 * previous column — one pass, not iterated to convergence. Iterating would
 * produce a marginally tidier picture and a layout that shifts when a node is
 * expanded, and stability is worth more here than tidiness.
 */
export function layout(nodes: GraphNode[], edges: GraphEdge[]): Positioned[] {
  const byLayer = new Map<number, GraphNode[]>();
  for (const node of nodes) {
    const layer = LAYERS.indexOf(node.type);
    // Types outside the chain (Document, Claim) are pinned left of everything.
    // They are provenance rather than structure, and giving them a column of
    // their own beats dropping them silently.
    const index = layer === -1 ? -1 : layer;
    const bucket = byLayer.get(index);
    if (bucket) bucket.push(node);
    else byLayer.set(index, [node]);
  }

  const order = new Map<string, number>();
  const positioned: Positioned[] = [];

  for (const layerIndex of [...byLayer.keys()].sort((a, b) => a - b)) {
    const layerNodes = byLayer.get(layerIndex) ?? [];

    const ranked = layerNodes
      .map((node) => {
        const parents = edges
          .filter((edge) => edge.target === node.id)
          .map((edge) => order.get(edge.source))
          .filter((value): value is number => value !== undefined);
        return {
          node,
          // No parent placed yet: sort by label so the order is at least
          // stable across renders rather than dependent on API row order.
          key:
            parents.length > 0
              ? parents.reduce((a, b) => a + b, 0) / parents.length
              : Number.MAX_SAFE_INTEGER,
        };
      })
      .sort((a, b) => a.key - b.key || a.node.label.localeCompare(b.node.label));

    ranked.forEach(({ node }, row) => {
      order.set(node.id, row);
      positioned.push({
        id: node.id,
        position: {
          x: (layerIndex + 1) * COLUMN_WIDTH,
          // Centre each column vertically so a single Capability sits opposite
          // the middle of the six Bottlenecks that require it.
          y: (row - (ranked.length - 1) / 2) * ROW_HEIGHT,
        },
      });
    });
  }

  return positioned;
}
