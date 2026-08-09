import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Provenance, Scorecard } from "@/lib/api/client";

import { Explain, type Explanation } from "./explain";
import { ThesisScorecard, toExplanation } from "./thesis-scorecard";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

const PROVENANCE: Provenance = {
  agent_run_id: "r1",
  agent_name: "process_critic",
  agent_version: "1.0.0",
  model: "claude-opus-5",
  provider: "anthropic",
  prompt_name: "process_critic",
  prompt_version: "1.0.0",
  prompt_content_hash: "abc123def456",
  as_of: "2026-05-25T12:00:00Z",
  recorded_at: "2026-05-25T12:04:11Z",
  status: "succeeded",
  evaluation_passed: true,
  advisories: [],
};

function explanation(overrides: Partial<Explanation> = {}): Explanation {
  return {
    conclusion: "Accumulated evidence",
    value: "9.1 / 10",
    confidence: 0.84,
    supporting: [{ label: "Government investment", value: "4" }],
    contradicting: [],
    rationale: "Four independent Events over eight weeks.",
    provenance: PROVENANCE,
    ...overrides,
  };
}

describe("explain primitive", () => {
  it("carries §23's model version, timestamp and confidence", async () => {
    const user = userEvent.setup();
    render(<Explain explanation={explanation()} />);

    await user.click(screen.getByRole("button", { name: /explain/i }));

    expect(screen.getByText("claude-opus-5")).toBeInTheDocument();
    expect(screen.getByText(/2026-05-25 12:04:11/)).toBeInTheDocument();
    expect(screen.getByText("0.84")).toBeInTheDocument();
  });

  it("says a confidence is model belief, not a calibrated probability", () => {
    render(<Explain explanation={explanation()} defaultOpen />);

    expect(screen.getByText(/not a calibrated probability/i)).toBeInTheDocument();
  });

  it("states that nothing contradicts rather than dropping the section", () => {
    // Silently omitting it makes an unchallenged thesis look identical to one
    // that was challenged and survived.
    render(<Explain explanation={explanation()} defaultOpen />);

    expect(screen.getByText("Contradicting")).toBeInTheDocument();
    expect(screen.getByText(/no contradicting evidence recorded/i)).toBeInTheDocument();
  });

  it("says so when nothing can be attributed", () => {
    render(<Explain explanation={explanation({ provenance: null })} defaultOpen />);

    expect(screen.getByText(/cannot be attributed to a model/i)).toBeInTheDocument();
  });

  it("surfaces advisory notes on the run that produced the number", () => {
    render(
      <Explain
        explanation={explanation({
          provenance: { ...PROVENANCE, advisories: ["citation_coverage"] },
        })}
        defaultOpen
      />,
    );

    expect(screen.getByText(/1 advisory note/)).toBeInTheDocument();
  });

  it("shows a rejected evaluation, because the number should not be trusted", () => {
    render(
      <Explain
        explanation={explanation({
          provenance: { ...PROVENANCE, evaluation_passed: false },
        })}
        defaultOpen
      />,
    );

    expect(screen.getByText(/rejected by evaluation/i)).toBeInTheDocument();
  });
});

describe("thesis scorecard", () => {
  const scorecard = {
    id: "sc1",
    subject: { id: "p1", type: "process", label: "Minerals", slug: null },
    family: "thesis_quality",
    observed_at: "2026-05-25T12:00:00Z",
    composite: null,
    composite_method: null,
    provenance: PROVENANCE,
    dimensions: [
      {
        dimension: "contradiction",
        value: 6.8,
        confidence: 0.8,
        method: "llm_judgement",
        inputs: { critique_count: 2, max_severity: 7.4 },
        rationale: "Two open critiques, the more severe on permitting.",
      },
    ],
  } as Scorecard;

  it("never averages the dimensions into a composite of its own", () => {
    // PRD §10: dimensions are always preserved. A client-side average would be
    // an unexplained number with weights nobody chose.
    render(<ThesisScorecard scorecard={scorecard} />);

    expect(screen.getByText(/dimensions are not averaged here/i)).toBeInTheDocument();
  });

  it("lists axes no agent writes yet, naming what would write them", () => {
    // A scorecard showing one axis looks like a thesis measured on one axis.
    // It is a thesis mostly unmeasured, and that is a different statement.
    render(<ThesisScorecard scorecard={scorecard} />);

    expect(screen.getByText(/awaiting Counterfactual agent \(#66\)/)).toBeInTheDocument();
    expect(screen.getByText(/awaiting Historical engine \(Phase 2\)/)).toBeInTheDocument();
  });

  it("opens a scored dimension into its inputs", async () => {
    const user = userEvent.setup();
    render(<ThesisScorecard scorecard={scorecard} />);

    await user.click(screen.getByRole("button", { name: /explain/i }));

    expect(screen.getByText("Critique count")).toBeInTheDocument();
    expect(screen.getByText(/Two open critiques/)).toBeInTheDocument();
  });

  it("renders when no scorecard exists at all", () => {
    render(<ThesisScorecard scorecard={undefined} />);

    expect(screen.getByText("Thesis quality")).toBeInTheDocument();
    expect(screen.getAllByText(/awaiting/).length).toBeGreaterThan(5);
  });
});

describe("dimension mapping", () => {
  it("splits inputs by sign so a reader sees direction, not a flat list", () => {
    const result = toExplanation({
      dimension: "accumulated_evidence",
      value: 9.1,
      confidence: 0.8,
      method: "computed",
      inputs: { supporting_events: 4, retracted: -1 },
      rationale: null,
    });

    expect(result.supporting.map((f) => f.label)).toEqual(["Supporting events"]);
    expect(result.contradicting.map((f) => f.label)).toEqual(["Retracted"]);
  });
});
