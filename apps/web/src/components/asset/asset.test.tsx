import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryChain } from "@/lib/api/client";

import { DiscoveryChainView } from "./discovery-chain";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const CHAIN: DiscoveryChain = [
  {
    start: { id: "p1", type: "process", label: "Domestic mineral security", slug: null },
    steps: [
      {
        relationship_type: "creates",
        rationale: "The buildout cannot proceed without separation capacity.",
        to: { id: "b1", type: "bottleneck", label: "Separation capacity", slug: null },
      },
      {
        relationship_type: "requires",
        rationale: "Separation is the binding step.",
        to: { id: "c1", type: "capability", label: "Solvent extraction", slug: null },
      },
      {
        relationship_type: "expressed_by",
        rationale: "Operates the only train at scale.",
        to: { id: "a1", type: "asset", label: "MP Materials", slug: null },
      },
    ],
    depth: 3,
    weight: 0.72,
  },
] as DiscoveryChain;

describe("discovery chain", () => {
  it("renders the chain in order rather than a list of related objects", () => {
    // ui_concept §12: the order is the argument. This Asset is here *because* a
    // Process created a constraint needing a Capability it has.
    render(<DiscoveryChainView paths={CHAIN} />);

    const labels = screen
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels).toEqual([
      "Domestic mineral security",
      "Separation capacity",
      "Solvent extraction",
      "MP Materials",
    ]);
  });

  it("shows the rationale for every edge, not only the endpoints", () => {
    render(<DiscoveryChainView paths={CHAIN} />);

    expect(
      screen.getByText(/cannot proceed without separation capacity/),
    ).toBeInTheDocument();
    expect(screen.getByText(/only train at scale/)).toBeInTheDocument();
  });

  it("reports the weakest edge, because a chain is only as good as it", () => {
    render(<DiscoveryChainView paths={CHAIN} />);

    expect(screen.getByText("0.72")).toBeInTheDocument();
  });

  it("calls an Asset with no chain a defect rather than an absence", () => {
    // An Asset nobody can explain is what the discovery chain exists to prevent.
    render(<DiscoveryChainView paths={[]} />);

    expect(screen.getByText(/defect rather than an absence/)).toBeInTheDocument();
  });
});
