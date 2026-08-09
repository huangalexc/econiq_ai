import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ArchetypeMachine, EmergingProcess } from "@/lib/api/client";

import { EmergenceRadar, toPoints } from "./emergence-radar";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const MACHINE = {
  archetype: "commodity_supply_cycle",
  cyclical: false,
  states: [
    { state: "supply_tightness", ordinal: 0, maturity: 0, transitions_to: [], is_terminal: false },
    {
      state: "price_acceleration",
      ordinal: 1,
      maturity: 0.5,
      transitions_to: [],
      is_terminal: false,
    },
    { state: "downcycle", ordinal: 2, maturity: 1, transitions_to: [], is_terminal: true },
  ],
} as ArchetypeMachine;

function process(overrides: Partial<EmergingProcess> = {}): EmergingProcess {
  return {
    id: "p1",
    name: "Minerals",
    slug: "minerals",
    description: "…",
    archetype: "commodity_supply_cycle",
    archetype_confidence: 0.8,
    status: "active",
    requires_review: false,
    revision: 1,
    current_state: "price_acceleration",
    state_confidence: 0.8,
    state_observed_at: "2026-07-01T00:00:00Z",
    rank_score: 0.5,
    components: [
      { name: "evidence_acceleration", raw: 3, normalised: 0.9, weight: 0.3, contribution: 0.27 },
    ],
    evidence_recent: 4,
    evidence_prior: 1,
    evidence_delta: 3,
    contradiction_count: 0,
    source_breadth: 3,
    capability_count: 2,
    asset_count: 4,
    binding_bottlenecks: [],
    ...overrides,
  } as EmergingProcess;
}

describe("radar positioning", () => {
  it("takes maturity from the archetype's machine, not from age", () => {
    // A Process discovered yesterday can be in Saturation. The machine
    // position is the claim being made; elapsed time is not.
    const [point] = toPoints([process()], [MACHINE]);

    expect(point.maturity).toBe(0.5);
    expect(point.acceleration).toBe(0.9);
  });

  it("drops a Process whose State is not on its archetype's machine", () => {
    // That is a data defect, not a point at the origin. Drawing it somewhere
    // arbitrary invites someone to read meaning into the position.
    const points = toPoints([process({ current_state: "discovery" })], [MACHINE]);

    expect(points).toEqual([]);
  });

  it("drops a Process with no archetype rather than guessing one", () => {
    expect(toPoints([process({ archetype: null })], [MACHINE])).toEqual([]);
  });

  it("sizes by downstream breadth, summing Capabilities and Assets", () => {
    const [point] = toPoints([process()], [MACHINE]);

    expect(point.breadth).toBe(6);
    expect(point.sourceBreadth).toBe(3);
  });
});

describe("radar framing", () => {
  it("says it is a discovery view rather than a forecast", () => {
    // ui_concept §5.2 is explicit that this is not a predictive claim.
    render(<EmergenceRadar points={toPoints([process()], [MACHINE])} />);

    expect(screen.getByText(/discovery view, not a forecast/i)).toBeInTheDocument();
  });

  it("labels the proxies as proxies", () => {
    render(<EmergenceRadar points={toPoints([process()], [MACHINE])} />);

    expect(screen.getByText(/graph breadth/i)).toBeInTheDocument();
    expect(
      screen.getByText(/media coverage, not market attention/i),
    ).toBeInTheDocument();
  });

  it("gives every point a name a screen reader can read", () => {
    render(<EmergenceRadar points={toPoints([process()], [MACHINE])} />);

    expect(
      screen.getByRole("button", { name: /Minerals, Price acceleration/ }),
    ).toBeInTheDocument();
  });

  it("says why it is empty rather than drawing empty axes", () => {
    render(<EmergenceRadar points={[]} />);

    expect(screen.getByText(/nothing to place on the machine/i)).toBeInTheDocument();
  });
});
