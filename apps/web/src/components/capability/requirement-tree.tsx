"use client";

/**
 * The AND/OR requirement structure (ui_concept §11; ontology §12).
 *
 * Rendered as a tree, never flattened. AND and OR over the same Capabilities
 * describe completely different worlds — "we need transmission *and*
 * transformers" versus "either would do" — and a flat list of four Capabilities
 * cannot answer the question the tree was built to answer.
 *
 * Optional Capabilities are marked rather than hidden: they do not block
 * satisfaction, but they are still where an Asset may sit.
 */

import Link from "next/link";

import type { Requirement } from "@/lib/api/client";
import { cn } from "@/lib/utils";

type Node = Requirement["root"];

export function RequirementTree({ node, depth = 0 }: { node: Node; depth?: number }) {
  if (node.kind === "capability") {
    return (
      <div className="flex items-baseline gap-2 py-0.5">
        <span className="text-sm text-ink">
          {node.capability ? (
            <Link
              href={`/capabilities/${node.capability.id}`}
              className="hover:text-accent"
            >
              {node.capability.label}
            </Link>
          ) : (
            <span className="text-ink-subtle">(unresolved Capability)</span>
          )}
        </span>
        {node.necessity === "optional" ? (
          <span className="text-[0.625rem] uppercase tracking-wider text-ink-subtle">
            optional
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <div className={cn(depth > 0 && "ml-4 border-l border-border pl-3")}>
      <p className="py-0.5 text-[0.6875rem] uppercase tracking-wider text-estimated">
        {node.operator === "or" ? "any of" : "all of"}
        {node.label ? <span className="text-ink-subtle"> — {node.label}</span> : null}
      </p>
      {(node.children ?? []).map((child, index) => (
        <RequirementTree key={index} node={child} depth={depth + 1} />
      ))}
    </div>
  );
}
