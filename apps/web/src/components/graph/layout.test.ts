import { describe, expect, it } from "vitest";

import { layout } from "./layout";
import type { GraphEdge, GraphNode } from "./types";

function node(id: string, type: GraphNode["type"], label = id): GraphNode {
  return { id, type, label };
}

function edge(source: string, target: string): GraphEdge {
  return {
    id: `${source}-${target}`,
    source,
    target,
    relationship: "requires",
    weight: 1,
    confidence: 0.9,
  };
}

describe("ontology layout", () => {
  it("places nodes in columns following the §9 hierarchy", () => {
    const nodes = [
      node("a", "asset"),
      node("p", "process"),
      node("c", "capability"),
      node("b", "bottleneck"),
    ];

    const x = new Map(layout(nodes, []).map((p) => [p.id, p.position.x]));

    expect(x.get("p")!).toBeLessThan(x.get("b")!);
    expect(x.get("b")!).toBeLessThan(x.get("c")!);
    expect(x.get("c")!).toBeLessThan(x.get("a")!);
  });

  it("is deterministic, so expanding a node does not rearrange the picture", () => {
    // A force layout settles differently every render, and a reader who has
    // just built a mental map loses it on every click.
    const nodes = [node("p1", "process"), node("p2", "process"), node("b", "bottleneck")];
    const edges = [edge("p1", "b"), edge("p2", "b")];

    const first = layout(nodes, edges);
    const second = layout([...nodes].reverse(), edges);

    expect(new Map(first.map((p) => [p.id, p.position]))).toEqual(
      new Map(second.map((p) => [p.id, p.position])),
    );
  });

  it("puts a shared Capability opposite the middle of what requires it", () => {
    // Confluence (ontology §13) is the picture: several independent Processes
    // needing one Capability. A layout optimising edge crossings would scatter
    // them and the convergence would stop being legible.
    const nodes = [
      node("b1", "bottleneck"),
      node("b2", "bottleneck"),
      node("b3", "bottleneck"),
      node("c", "capability"),
    ];
    const edges = [edge("b1", "c"), edge("b2", "c"), edge("b3", "c")];

    const positions = new Map(layout(nodes, edges).map((p) => [p.id, p.position]));
    const bottleneckYs = ["b1", "b2", "b3"].map((id) => positions.get(id)!.y);
    const middle = bottleneckYs.reduce((a, b) => a + b, 0) / 3;

    expect(positions.get("c")!.y).toBeCloseTo(middle, 5);
  });

  it("gives Documents and Claims a column left of the chain rather than dropping them", () => {
    // They are provenance rather than structure, but a node the API returned
    // and the canvas silently discarded is worse than one placed oddly.
    const nodes = [node("d", "document"), node("p", "process")];

    const x = new Map(layout(nodes, []).map((p) => [p.id, p.position.x]));

    expect(x.get("d")!).toBeLessThan(x.get("p")!);
  });

  it("orders a column by its parents so edges do not cross needlessly", () => {
    const nodes = [
      node("p1", "process"),
      node("p2", "process"),
      node("b1", "bottleneck"),
      node("b2", "bottleneck"),
    ];
    // p1 is above p2; b1 hangs off p2 and b2 off p1, so the barycentre pass
    // should put b2 above b1.
    const edges = [edge("p2", "b1"), edge("p1", "b2")];

    const positions = new Map(layout(nodes, edges).map((p) => [p.id, p.position]));

    expect(positions.get("b2")!.y).toBeLessThan(positions.get("b1")!.y);
  });
});
