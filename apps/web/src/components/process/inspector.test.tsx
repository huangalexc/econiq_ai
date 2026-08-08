import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProvenanceInspector } from "./provenance-inspector";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/as-of", () => ({
  useAsOf: () => ({ asOf: null, setAsOf: vi.fn(), isHistorical: false }),
}));

function mountWith(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ProvenanceInspector nodeId="n1" title="Pentagon takes a stake" onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

const CLAIM = {
  id: "c1",
  document_id: "d1",
  text: "Separation capacity outside China is under 10 percent of supply.",
  claim_type: "reported_claim",
  assertion_source: "observed_fact",
  attributed_to: null,
  extraction_confidence: 0.93,
  source_location: {
    quote: "under 10 percent of global supply",
    char_start: 120,
    char_end: 153,
    section: "STRATEGIC MINERALS",
  },
  stated_at: null,
  provenance: null,
};

const DOCUMENT = {
  id: "d1",
  source: "corpus-wire-a",
  publisher: "Meridian Wire",
  title: "Defense department takes equity stake",
  url: null,
  document_type: "news_article",
  publication_time: "2026-05-04T12:00:00Z",
  storage_uri: null,
};

describe("provenance inspector", () => {
  it("shows the quoted span with its offsets, not a summary", async () => {
    // ui_concept §29: evidence must never be an undifferentiated AI summary.
    // Offsets are what make the citation checkable rather than merely present.
    mountWith({
      subject: { id: "n1", type: "event", label: "…", slug: null },
      is_evidenced: true,
      supporting_events: [],
      contradicting_events: [],
      claims: [CLAIM],
      documents: [DOCUMENT],
      independent_source_count: 1,
    });

    expect(
      await screen.findByText(/under 10 percent of global supply/),
    ).toBeInTheDocument();
    expect(screen.getByText(/chars 120–153/)).toBeInTheDocument();
    expect(screen.getByText(/Meridian Wire/)).toBeInTheDocument();
  });

  it("says how many documents added no independent source", async () => {
    // The most misleading thing about an evidence list is not saying that four
    // of its six documents are the same wire story.
    mountWith({
      subject: { id: "n1", type: "event", label: "…", slug: null },
      is_evidenced: true,
      supporting_events: [],
      contradicting_events: [],
      claims: [CLAIM],
      documents: [DOCUMENT, { ...DOCUMENT, id: "d2", publisher: "Halbrook" }],
      independent_source_count: 1,
    });

    expect(
      await screen.findByText(/1 document added no independent source/),
    ).toBeInTheDocument();
    expect(screen.getByText(/syndicated copy/)).toBeInTheDocument();
  });

  it("calls a missing Claim a gap in the chain, not an absence of opinion", async () => {
    mountWith({
      subject: { id: "n1", type: "process", label: "…", slug: null },
      is_evidenced: false,
      supporting_events: [],
      contradicting_events: [],
      claims: [],
      documents: [],
      independent_source_count: 0,
    });

    expect(await screen.findByText(/gap in the chain/)).toBeInTheDocument();
  });
});
