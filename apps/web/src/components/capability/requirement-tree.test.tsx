import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Requirement } from "@/lib/api/client";

import { RequirementTree } from "./requirement-tree";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

type Node = Requirement["root"];

const leaf = (label: string, necessity = "required"): Node =>
  ({
    kind: "capability",
    capability: { id: label, type: "capability", label, slug: null },
    necessity,
    weight: 1,
  }) as Node;

describe("requirement tree", () => {
  it("says all of for AND and any of for OR", () => {
    // Ontology §12: the same two Capabilities under AND and under OR describe
    // completely different worlds, and a flat list cannot tell them apart.
    const { rerender } = render(
      <RequirementTree
        node={
          {
            kind: "group",
            operator: "and",
            necessity: "required",
            weight: 1,
            children: [leaf("Separation"), leaf("Feedstock")],
          } as Node
        }
      />,
    );
    expect(screen.getByText(/all of/i)).toBeInTheDocument();

    rerender(
      <RequirementTree
        node={
          {
            kind: "group",
            operator: "or",
            necessity: "required",
            weight: 1,
            children: [leaf("Separation"), leaf("Feedstock")],
          } as Node
        }
      />,
    );
    expect(screen.getByText(/any of/i)).toBeInTheDocument();
  });

  it("marks optional Capabilities rather than hiding them", () => {
    // They do not block satisfaction, but they are still where an Asset sits.
    render(
      <RequirementTree
        node={
          {
            kind: "group",
            operator: "and",
            necessity: "required",
            weight: 1,
            children: [leaf("Separation"), leaf("Recycling", "optional")],
          } as Node
        }
      />,
    );

    expect(screen.getByText("Recycling")).toBeInTheDocument();
    expect(screen.getByText("optional")).toBeInTheDocument();
  });

  it("renders nested structure rather than flattening it", () => {
    render(
      <RequirementTree
        node={
          {
            kind: "group",
            operator: "and",
            necessity: "required",
            weight: 1,
            children: [
              leaf("Separation"),
              {
                kind: "group",
                operator: "or",
                necessity: "required",
                weight: 1,
                children: [leaf("Domestic feedstock"), leaf("Allied feedstock")],
              },
            ],
          } as Node
        }
      />,
    );

    expect(screen.getByText(/all of/i)).toBeInTheDocument();
    expect(screen.getByText(/any of/i)).toBeInTheDocument();
    expect(screen.getByText("Allied feedstock")).toBeInTheDocument();
  });

  it("says so when a Capability could not be resolved", () => {
    render(
      <RequirementTree
        node={
          {
            kind: "capability",
            capability: null,
            necessity: "required",
            weight: 1,
          } as Node
        }
      />,
    );

    expect(screen.getByText(/unresolved Capability/i)).toBeInTheDocument();
  });
});
