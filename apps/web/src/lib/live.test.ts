import { describe, expect, it } from "vitest";

/**
 * The stream's contract, asserted from the client's side.
 *
 * The behaviour that matters is in `useLiveUpdates`, which needs a real
 * EventSource to exercise. What can be pinned without one is the shape of the
 * agreement: the server sends cache keys, never rows.
 */
describe("live update contract", () => {
  it("carries invalidation targets rather than data", () => {
    const frame = {
      name: "process.updated",
      subject_id: "p1",
      invalidates: ["discover", "process", "journal", "alerts"],
      at: "2026-08-07T12:00:00Z",
    };

    // Two paths to a value diverge the first time one is read at a different
    // as_of, so the frame must not contain one.
    expect(Object.keys(frame)).not.toContain("payload");
    expect(Object.keys(frame)).not.toContain("process");
    expect(frame.invalidates.every((key) => typeof key === "string")).toBe(true);
  });
});
