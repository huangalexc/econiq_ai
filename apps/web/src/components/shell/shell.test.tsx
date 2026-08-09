import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { keyFor } from "@/lib/query";
import { confidenceBand } from "@/lib/utils";

import { ALL_NAV_ITEMS, NAVIGATION } from "./navigation";
import { Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({
  usePathname: () => "/processes",
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

describe("navigation", () => {
  it("leads with Discover and puts Assets last in the chain", () => {
    // ui_concept §2.1: the product is Process-first and Asset-second. Asserted
    // as an ordering rather than an exact list, so adding a layer to the chain
    // does not fail a test about which end it belongs at.
    const research = NAVIGATION[0].items.map((item) => item.label);

    expect(research[0]).toBe("Discover");
    expect(research.indexOf("Processes")).toBeLessThan(research.indexOf("Assets"));
    expect(research.indexOf("Bottlenecks")).toBeLessThan(
      research.indexOf("Capabilities"),
    );
    expect(research.indexOf("Capabilities")).toBeLessThan(research.indexOf("Assets"));
  });

  it("shows routes whose screens are not built yet, labelled", () => {
    const planned = ALL_NAV_ITEMS.filter((item) => item.planned);
    expect(planned.length).toBeGreaterThan(0);
    for (const item of planned) {
      expect(item.planned).toMatch(/#\d+|Phase \d/);
    }
  });

  it("marks exactly the current route, not every prefix of it", () => {
    render(<Sidebar />);

    const current = screen.getAllByRole("link", { current: "page" });
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAccessibleName(/Processes/);
  });
});

describe("query keys", () => {
  it("separate a historical read from the present", () => {
    // Two reads of one Process at different cut-offs are different data. A
    // cache that treated them as one would serve a July belief as today's.
    const now = keyFor(["process", "abc"]);
    const then = keyFor(["process", "abc"], { asOf: "2026-07-14T12:00:00Z" });

    expect(now).not.toEqual(then);
  });

  it("separate reads that differ only by filter", () => {
    expect(keyFor(["processes"], { query: { status: ["active"] } })).not.toEqual(
      keyFor(["processes"], { query: { status: ["dormant"] } }),
    );
  });
});

describe("confidence", () => {
  it("bands rather than grades, because these are not calibrated probabilities", () => {
    // Ontology §35. Rendering 0.71 as a precise point on a gradient would claim
    // a precision the calibration framework has not yet earned.
    expect(confidenceBand(0.9)).toBe("high");
    expect(confidenceBand(0.6)).toBe("medium");
    expect(confidenceBand(0.2)).toBe("low");
  });
});
