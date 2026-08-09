"use client";

/**
 * Dependency graph explorer (issue #26, ui_concept §9).
 *
 * §9's two instructions are "the user should be able to expand one or two hops
 * at a time" and "do not render the entire graph by default", and they are the
 * same instruction: this graph gets large quickly — one Process reaches a dozen
 * Assets through a handful of Capabilities, and Capabilities are shared between
 * Processes on purpose (ontology §13). Rendering it all produces a hairball in
 * which the confluence that makes the shared Capability interesting is exactly
 * what you cannot see.
 *
 * So the explorer starts at one seed and one hop, and every node carries its
 * own expand control. What is on screen is always something the reader asked
 * for.
 *
 * Layout is by ontology layer (see `layout.ts`) rather than force-directed:
 * deterministic, so expanding a node does not rearrange the picture underneath
 * the reader's cursor.
 */

import {
  Background,
  Controls,
  type Edge,
  Handle,
  MiniMap,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";
import { cn, humanise } from "@/lib/utils";

import { layout } from "./layout";
import {
  EDGE_STYLE,
  type EntityType,
  type GraphEdge,
  type GraphNode,
  NODE_STYLE,
  type RelationshipType,
} from "./types";

import "@xyflow/react/dist/style.css";

interface NodeData extends Record<string, unknown> {
  node: GraphNode;
  isSeed: boolean;
  expanded: boolean;
  onExpand: (id: string) => void;
  onSelect: (node: GraphNode) => void;
}

function OntologyNode({ data }: NodeProps<Node<NodeData>>) {
  const style = NODE_STYLE[data.node.type];
  return (
    <div
      className={cn(
        "w-[13rem] rounded-panel border bg-surface px-3 py-2 text-left",
        data.isSeed ? "border-accent" : "border-border",
      )}
    >
      <Handle type="target" position={Position.Left} className="!bg-border" />
      <div className="flex items-center gap-2">
        <span
          className="rounded px-1 text-[0.5625rem] font-medium tracking-wider"
          style={{ color: style.accent, border: `1px solid ${style.accent}` }}
        >
          {style.abbr}
        </span>
        {!data.expanded ? (
          <button
            type="button"
            onClick={() => data.onExpand(data.node.id)}
            className="ml-auto rounded border border-border p-0.5 text-ink-subtle hover:text-ink"
            aria-label={`Expand ${data.node.label}`}
            title="Expand one hop"
          >
            <Plus aria-hidden className="size-3" />
          </button>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => data.onSelect(data.node)}
        className="mt-1 block w-full text-left text-xs leading-snug text-ink hover:text-accent"
      >
        {data.node.label}
      </button>
      <Handle type="source" position={Position.Right} className="!bg-border" />
    </div>
  );
}

const NODE_TYPES = { ontology: OntologyNode };

export interface GraphExplorerProps {
  /** Where to start. Usually the Process whose screen this is on. */
  seedId: string;
  onSelect?: (node: GraphNode) => void;
  selectedId?: string | null;
  className?: string;
}

export function GraphExplorer(props: GraphExplorerProps) {
  const { asOf } = useAsOf();
  return (
    <ReactFlowProvider>
      {/* Remounted when the seed or the cut-off changes, rather than reset by
          hand. A new cut-off makes every node on screen a claim about a
          different instant, so the whole picture is new — and a manual reset is
          a list of state to clear that the next person adding a field forgets
          to extend. */}
      <Explorer key={`${props.seedId}:${asOf ?? "now"}`} asOf={asOf} {...props} />
    </ReactFlowProvider>
  );
}

function Explorer({
  seedId,
  onSelect,
  selectedId,
  className,
  asOf,
}: GraphExplorerProps & { asOf: string | null }) {
  const { fitView } = useReactFlow();

  const queryClient = useQueryClient();
  // Which nodes the reader has opened. The seed is open from the start; every
  // other id lands here on click, and the union of their hops is the picture.
  const [opened, setOpened] = useState<string[]>([seedId]);
  const [hidden, setHidden] = useState<Set<RelationshipType>>(new Set());
  const [expanding, setExpanding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hops = useQueries({
    queries: opened.map((nodeId) => ({
      queryKey: keyFor(["subgraph", nodeId], { asOf }),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.graph.subgraph({
          asOf,
          query: { node_id: [nodeId], depth: 1, limit: 120 },
          signal,
        }),
      staleTime: 60_000,
    })),
  });

  /**
   * Open one more hop.
   *
   * Cumulative: the reader is building a picture, and replacing the set on each
   * click would throw away the part they had already opened. Prefetched through
   * the query client so an expansion the reader collapses and reopens is free.
   */
  const expand = useCallback(
    async (nodeId: string) => {
      if (opened.includes(nodeId)) return;
      setExpanding(true);
      setError(null);
      try {
        await queryClient.prefetchQuery({
          queryKey: keyFor(["subgraph", nodeId], { asOf }),
          queryFn: () =>
            api.graph.subgraph({
              asOf,
              query: { node_id: [nodeId], depth: 1, limit: 120 },
            }),
        });
        setOpened((current) =>
          current.includes(nodeId) ? current : [...current, nodeId],
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not expand.");
      } finally {
        setExpanding(false);
      }
    },
    [asOf, opened, queryClient],
  );

  // Merged from every opened hop. A node reached from two directions appears
  // once, which is what makes a shared Capability read as confluence rather
  // than as a duplicate.
  const { nodes, edges } = useMemo(() => {
    const nodeMap = new Map<string, GraphNode>();
    const edgeMap = new Map<string, GraphEdge>();
    for (const hop of hops) {
      for (const node of hop.data?.nodes ?? []) {
        nodeMap.set(node.id, {
          id: node.id,
          type: node.type as EntityType,
          label: node.label,
          slug: node.slug,
        });
      }
      for (const edge of hop.data?.edges ?? []) {
        const id = `${edge.source_id}-${edge.relationship_type}-${edge.target_id}`;
        edgeMap.set(id, {
          id,
          source: edge.source_id,
          target: edge.target_id,
          relationship: edge.relationship_type as RelationshipType,
          weight: edge.weight,
          confidence: edge.confidence,
          rationale: edge.rationale,
        });
      }
    }
    return { nodes: nodeMap, edges: edgeMap };
  }, [hops]);

  const expanded = useMemo(() => new Set(opened), [opened]);
  const loading = expanding || hops.some((hop) => hop.isPending);

  const handleSelect = useCallback(
    (node: GraphNode) => onSelect?.(node),
    [onSelect],
  );

  const visibleEdges = useMemo(
    () => [...edges.values()].filter((edge) => !hidden.has(edge.relationship)),
    [edges, hidden],
  );

  const flow = useMemo(() => {
    const nodeList = [...nodes.values()];
    const positions = new Map(
      layout(nodeList, visibleEdges).map((p) => [p.id, p.position]),
    );

    const flowNodes: Node<NodeData>[] = nodeList.map((node) => ({
      id: node.id,
      type: "ontology",
      position: positions.get(node.id) ?? { x: 0, y: 0 },
      selected: node.id === selectedId,
      data: {
        node,
        isSeed: node.id === seedId,
        expanded: expanded.has(node.id),
        onExpand: (id: string) => void expand(id),
        onSelect: handleSelect,
      },
    }));

    const flowEdges: Edge[] = visibleEdges.map((edge) => {
      const style = EDGE_STYLE[edge.relationship];
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: style.label,
        animated: false,
        style: {
          stroke: style.stroke,
          strokeDasharray: style.dashed ? "4 4" : undefined,
          // Edge weight is confidence, so a tentative edge looks tentative.
          strokeWidth: 1 + edge.confidence,
        },
        labelStyle: { fill: "var(--color-ink-subtle)", fontSize: 9 },
        labelBgStyle: { fill: "var(--color-canvas)" },
      };
    });

    return { flowNodes, flowEdges };
  }, [nodes, visibleEdges, selectedId, seedId, expanded, expand, handleSelect]);

  useEffect(() => {
    // Refit only when the node count changes, not on every render: refitting on
    // selection would yank the viewport while the reader is reading.
    const timer = setTimeout(() => void fitView({ duration: 200, padding: 0.2 }), 50);
    return () => clearTimeout(timer);
  }, [nodes.size, fitView]);

  const present = useMemo(
    () => [...new Set([...edges.values()].map((e) => e.relationship))].sort(),
    [edges],
  );

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-ink-subtle">Edges:</span>
        {present.map((relationship) => (
          <button
            key={relationship}
            type="button"
            onClick={() =>
              setHidden((current) => {
                const next = new Set(current);
                if (next.has(relationship)) next.delete(relationship);
                else next.add(relationship);
                return next;
              })
            }
            aria-pressed={!hidden.has(relationship)}
            className={cn(
              "rounded border px-1.5 py-0.5",
              hidden.has(relationship)
                ? "border-border text-ink-subtle line-through"
                : "border-border-strong text-ink-muted",
            )}
            style={
              hidden.has(relationship)
                ? undefined
                : { color: EDGE_STYLE[relationship].stroke }
            }
          >
            {humanise(relationship)}
          </button>
        ))}
        {loading ? <span className="text-ink-subtle">expanding…</span> : null}
        {error ? <span className="text-contradicts">{error}</span> : null}
        <span className="ml-auto text-ink-subtle">
          {nodes.size} node{nodes.size === 1 ? "" : "s"} shown — expand a node for
          one more hop
        </span>
      </div>

      <div className="h-[32rem] rounded-panel border border-border bg-canvas">
        <ReactFlow
          nodes={flow.flowNodes}
          edges={flow.flowEdges}
          nodeTypes={NODE_TYPES}
          // Positions are derived from the ontology, so dragging a node would
          // put it somewhere the layout does not agree with and the next
          // expansion would silently move it back.
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          proOptions={{ hideAttribution: false }}
          minZoom={0.2}
          fitView
        >
          <Background color="var(--color-border)" gap={24} />
          <Controls showInteractive={false} />
          <MiniMap
            pannable
            zoomable
            nodeColor={(node) =>
              NODE_STYLE[(node.data as NodeData).node.type]?.accent ??
              "var(--color-border)"
            }
            maskColor="rgba(0,0,0,0.35)"
          />
        </ReactFlow>
      </div>
    </div>
  );
}
