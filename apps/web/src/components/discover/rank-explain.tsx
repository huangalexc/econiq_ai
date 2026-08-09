"use client";

/**
 * The [Explain] primitive applied to the Discover rank (ui_concept §23, #25).
 *
 * §23 makes Explain universal: any derived number should be openable to show
 * what produced it. This is the first place that principle is exercised, and
 * the rank is a good test of it — it is a weighted sum of six things, none of
 * which is meaningful on its own.
 *
 * The bars are contributions, not raw values. A component with a high raw value
 * and a low weight looks important on a chart of raw values and is not.
 */

import { humanise } from "@/lib/utils";
import type { EmergingProcess } from "@/lib/api/client";

type Component = NonNullable<EmergingProcess["components"]>[number];

export function RankExplain({
  components,
  score,
}: {
  components: Component[];
  score: number;
}) {
  const max = Math.max(...components.map((c) => c.contribution), 0.0001);

  return (
    <div className="space-y-2">
      <p className="text-xs text-ink-subtle">
        Rank {score.toFixed(3)} is the sum of these contributions. Weights are
        provisional and are shown so they can be disagreed with.
      </p>
      <table className="w-full text-xs">
        <tbody>
          {[...components]
            .sort((a, b) => b.contribution - a.contribution)
            .map((component) => (
              <tr key={component.name}>
                <td className="py-1 pr-3 text-ink-muted">
                  {humanise(component.name)}
                </td>
                <td className="py-1 pr-3 text-right font-mono text-ink-subtle">
                  {formatRaw(component.name, component.raw)}
                </td>
                <td className="w-1/2 py-1">
                  <div
                    className="h-1.5 rounded-full bg-accent"
                    style={{
                      width: `${Math.max((component.contribution / max) * 100, 2)}%`,
                    }}
                  />
                </td>
                <td className="py-1 pl-3 text-right font-mono text-ink">
                  {component.contribution.toFixed(3)}
                </td>
                <td className="py-1 pl-2 text-right font-mono text-ink-subtle">
                  ×{component.weight.toFixed(2)}
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

function formatRaw(name: string, raw: number): string {
  // `state_recency` is days, and an unmeasured State is infinitely old rather
  // than zero days old — rendering `Infinity` would be worse than saying never.
  if (!Number.isFinite(raw)) return "never";
  if (name === "state_recency") return `${Math.round(raw)}d`;
  if (name === "evidence_acceleration") return raw > 0 ? `+${raw}` : `${raw}`;
  return Number.isInteger(raw) ? String(raw) : raw.toFixed(2);
}
