import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EmergingProcess } from "@/lib/api/client";

import { EmergingPanel } from "./emerging-panel";
import { HotCard } from "./hot-card";
import { RankExplain } from "./rank-explain";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function makeProcess(overrides: Partial<EmergingProcess> = {}): EmergingProcess {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    name: "Domestic strategic-mineral security",
    slug: "minerals",
    description: "…",
    archetype: "commodity_supply_cycle",
    archetype_confidence: 0.85,
    status: "active",
    requires_review: false,
    revision: 1,
    current_state: "supply_tightness",
    state_confidence: 0.82,
    state_observed_at: "2026-07-14T12:00:00Z",
    rank_score: 0.641,
    components: [
      {
        name: "evidence_acceleration",
        raw: 3,
        normalised: 1,
        weight: 0.3,
        contribution: 0.3,
      },
      {
        name: "state_confidence",
        raw: 0.82,
        normalised: 0.82,
        weight: 0.2,
        contribution: 0.164,
      },
      {
        name: "state_recency",
        raw: 3,
        normalised: 0.98,
        weight: 0.15,
        contribution: 0.147,
      },
    ],
    evidence_recent: 4,
    evidence_prior: 1,
    evidence_delta: 3,
    contradiction_count: 2,
    source_breadth: 5,
    capability_count: 2,
    asset_count: 3,
    binding_bottlenecks: ["Heavy rare-earth separation"],
    ...overrides,
  } as EmergingProcess;
}

describe("emerging panel", () => {
  it("gives contradicting evidence its own column rather than netting it off", () => {
    // Ontology §17: contradiction is a scored dimension, not a deduction. A
    // delta of +3 with 2 contradictions is not the same as a delta of +1.
    render(<EmergingPanel processes={[makeProcess()]} />);

    const row = screen.getAllByRole("row")[1];
    const cells = within(row).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("+3");
    expect(cells[4]).toHaveTextContent("2");
  });

  it("flags a Process that is waiting on human review", () => {
    render(<EmergingPanel processes={[makeProcess({ requires_review: true })]} />);

    expect(screen.getByTitle(/human review/i)).toBeInTheDocument();
  });

  it("links each row to its Process", () => {
    render(<EmergingPanel processes={[makeProcess()]} />);

    expect(
      screen.getByRole("link", { name: /Domestic strategic-mineral security/ }),
    ).toHaveAttribute("href", "/processes/11111111-1111-1111-1111-111111111111");
  });
});

describe("hot card", () => {
  it("labels publisher count as sources, never as market attention", () => {
    // Phase 0 has no market data. Calling this "attention" would make §5.2's
    // central claim — evidence moving before attention — untestable.
    render(<HotCard process={makeProcess()} />);

    expect(screen.getByText(/source breadth/i)).toBeInTheDocument();
    expect(screen.queryByText(/market attention/i)).not.toBeInTheDocument();
    expect(screen.getByText(/5 publishers/)).toBeInTheDocument();
  });

  it("shows contradictions on the face of the card, not behind a tab", () => {
    render(<HotCard process={makeProcess()} />);

    expect(screen.getByText(/contradictions/i)).toBeInTheDocument();
  });

  it("omits historical precedent rather than showing it blank", () => {
    // An empty "Historical precedent" row reads as a Process with no
    // precedent, which is a claim. It needs the Phase 2 engine.
    render(<HotCard process={makeProcess()} />);

    expect(screen.queryByText(/precedent/i)).not.toBeInTheDocument();
  });

  it("opens the rank into its components", async () => {
    const user = userEvent.setup();
    render(<HotCard process={makeProcess()} />);

    await user.click(screen.getByRole("button", { name: /explain rank/i }));

    expect(screen.getByText(/Evidence acceleration/)).toBeInTheDocument();
    expect(screen.getByText(/0\.641/)).toBeInTheDocument();
  });

  it("reports deceleration rather than flooring it at zero", () => {
    render(
      <HotCard
        process={makeProcess({
          evidence_delta: -2,
          evidence_recent: 0,
          evidence_prior: 2,
        })}
      />,
    );

    expect(screen.getByLabelText("decelerating")).toBeInTheDocument();
  });
});

describe("rank explain", () => {
  it("charts contributions, not raw values", () => {
    // A component with a large raw value and a small weight looks important on
    // a chart of raw values and is not.
    render(
      <RankExplain
        score={0.5}
        components={[
          { name: "asset_breadth", raw: 30, normalised: 1, weight: 0.15, contribution: 0.15 },
          {
            name: "evidence_acceleration",
            raw: 2,
            normalised: 1,
            weight: 0.3,
            contribution: 0.3,
          },
        ]}
      />,
    );

    const rows = screen.getAllByRole("row");
    // Sorted by contribution, so acceleration outranks the larger raw count.
    expect(rows[0]).toHaveTextContent("Evidence acceleration");
    expect(rows[1]).toHaveTextContent("Asset breadth");
  });

  it("says never rather than Infinity for a State that was never recorded", () => {
    render(
      <RankExplain
        score={0}
        components={[
          {
            name: "state_recency",
            raw: Number.POSITIVE_INFINITY,
            normalised: 0,
            weight: 0.15,
            contribution: 0,
          },
        ]}
      />,
    );

    expect(screen.getByText("never")).toBeInTheDocument();
  });
});
