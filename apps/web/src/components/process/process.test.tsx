import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProcessState, StateNode, TimelineEntry } from "@/lib/api/client";

import { EvidenceTimeline } from "./evidence-timeline";
import { StateBelief } from "./state-belief";
import { StateMachineTrack } from "./state-machine";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/processes/p1",
  useSearchParams: () => new URLSearchParams(),
}));

const STATES: StateNode[] = [
  { state: "supply_tightness", ordinal: 0, maturity: 0, transitions_to: ["price_acceleration"], is_terminal: false },
  { state: "price_acceleration", ordinal: 1, maturity: 0.5, transitions_to: ["downcycle"], is_terminal: false },
  { state: "downcycle", ordinal: 2, maturity: 1, transitions_to: [], is_terminal: true },
];

function observation(overrides: Partial<ProcessState> = {}): ProcessState {
  return {
    id: "s1",
    archetype: "commodity_supply_cycle",
    categorical_state: "supply_tightness",
    state_confidence: 0.82,
    observed_at: "2026-05-04T00:00:00Z",
    recorded_at: "2026-05-04T00:00:00Z",
    features: [],
    transition_beliefs: { price_acceleration: 0.55, downcycle: 0.1 },
    transition_indicators: ["Spot premia widening"],
    reversal_indicators: ["New capacity commissioned"],
    ...overrides,
  } as ProcessState;
}

describe("state machine track", () => {
  it("shows a State the Process left, not only where it is now", () => {
    // The append-only history is the record (ui_concept §32).
    render(
      <StateMachineTrack
        states={STATES}
        history={[
          observation(),
          observation({
            id: "s2",
            categorical_state: "price_acceleration",
            observed_at: "2026-06-10T00:00:00Z",
            state_confidence: 0.71,
          }),
        ]}
        current="price_acceleration"
      />,
    );

    const items = screen.getAllByRole("listitem");
    expect(within(items[0]).getByText("2026-05-04")).toBeInTheDocument();
    expect(within(items[1]).getByText(/current/i)).toBeInTheDocument();
  });

  it("records the date and confidence of each arrival", () => {
    render(
      <StateMachineTrack states={STATES} history={[observation()]} current="supply_tightness" />,
    );

    const first = screen.getAllByRole("listitem")[0];
    expect(within(first).getByText("2026-05-04")).toBeInTheDocument();
    expect(within(first).getByText("0.82")).toBeInTheDocument();
  });

  it("marks unreached States as not reached rather than as future", () => {
    // They are the machine's shape, not a claim about where it will go.
    render(
      <StateMachineTrack states={STATES} history={[observation()]} current="supply_tightness" />,
    );

    expect(screen.getAllByText("not reached")).toHaveLength(2);
  });

  it("uses the first arrival at a State, not the latest re-observation", () => {
    render(
      <StateMachineTrack
        states={STATES}
        history={[
          observation({ id: "later", observed_at: "2026-08-01T00:00:00Z" }),
          observation({ id: "first", observed_at: "2026-05-04T00:00:00Z" }),
        ]}
        current="supply_tightness"
      />,
    );

    const first = screen.getAllByRole("listitem")[0];
    expect(within(first).getByText("2026-05-04")).toBeInTheDocument();
  });
});

describe("state belief", () => {
  it("is headed transition belief, never state distribution", () => {
    // §6.3's distribution over the *current* State is not computed. Rendering
    // transition beliefs under that heading would be a claim the system never
    // made.
    render(<StateBelief state={observation()} />);

    expect(screen.getByText(/transition belief/i)).toBeInTheDocument();
    expect(screen.queryByText(/state distribution/i)).not.toBeInTheDocument();
  });

  it("says the numbers are uncalibrated", () => {
    render(<StateBelief state={observation()} />);

    expect(screen.getByText(/not calibrated probability/i)).toBeInTheDocument();
  });

  it("never renders a belief as a percentage", () => {
    // A percent sign implies a normalised distribution. These do not sum to one.
    const { container } = render(<StateBelief state={observation()} />);

    expect(screen.getByText("0.55")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/\d\s*%/);
  });

  it("shows what would confirm and what would reverse the estimate", () => {
    render(<StateBelief state={observation()} />);

    expect(screen.getByText(/Spot premia widening/)).toBeInTheDocument();
    expect(screen.getByText(/New capacity commissioned/)).toBeInTheDocument();
  });
});

describe("evidence timeline", () => {
  const entries: TimelineEntry[] = [
    {
      kind: "journal",
      occurred_at: "2026-05-25T00:00:00Z",
      recorded_at: "2026-05-25T00:00:00Z",
      title: "supply_tightness weakened",
      detail: "belief_change",
      subject_id: null,
      supports: null,
      confidence_before: 0.86,
      confidence_after: 0.8,
      state_label: null,
    },
    {
      kind: "evidence",
      occurred_at: "2026-05-04T00:00:00Z",
      recorded_at: "2026-06-01T00:00:00Z",
      title: "Pentagon takes a stake",
      detail: "2 independent source(s)",
      subject_id: "e1",
      supports: true,
      confidence_before: null,
      confidence_after: null,
      state_label: null,
    },
  ];

  it("surfaces the ingestion lag where it differs from the event date", () => {
    // A document published in July and ingested in August could not have
    // informed a belief formed in July.
    render(<EvidenceTimeline entries={entries} />);

    expect(screen.getByText(/learned 2026-06-01/)).toBeInTheDocument();
  });

  it("shows the direction a confidence moved, not just the new number", () => {
    render(<EvidenceTimeline entries={entries} />);

    expect(screen.getByText("0.80")).toBeInTheDocument();
    expect(screen.getByText(/0\.86/)).toBeInTheDocument();
  });

  it("distinguishes supporting from contradicting entries", () => {
    render(<EvidenceTimeline entries={entries} />);

    expect(screen.getByText("Evidence")).toHaveClass("text-supports");
  });
});
