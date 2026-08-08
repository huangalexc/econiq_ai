"use client";

/**
 * Emergence Radar (issue #22, ui_concept §5.2).
 *
 *   X = Process maturity        — position on the archetype's State machine
 *   Y = evidence acceleration   — the ranking component, unweighted
 *   size = graph breadth        — Capabilities and Assets downstream
 *   opacity = source breadth    — publisher count, a media-coverage proxy
 *
 * §5.2's purpose is to find Processes "where evidence is accelerating before
 * attention has fully caught up" — the top-left region, young and moving and
 * not yet widely covered. It says plainly that this is "a discovery
 * visualization, not a predictive claim", so the chart carries that framing
 * rather than leaving it in a doc.
 *
 * **Two axes are honest and two are proxies**, and the legend says which. Size
 * is *graph breadth*, not "economic scope": counting downstream Capabilities
 * and Assets says how broadly the Process touches this graph, not how much of
 * the economy it touches, and the second would need output and revenue data
 * Phase 0 does not have. Opacity is media coverage, for the reason given
 * everywhere else — Phase 0 has no market data, and using media coverage while
 * calling it market attention would quietly invert the reading of the top-left
 * corner, which is the entire point of the chart.
 *
 * Rendered as SVG with `d3-scale` for the scales rather than through a charting
 * library. §28 asks for a small number of reusable primitives; a scatter is one
 * `<circle>` per point, and real DOM nodes can be focused, labelled and read by
 * a screen reader, which a canvas cannot.
 */

import { scaleLinear, scaleSqrt } from "d3-scale";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { ArchetypeMachine, EmergingProcess } from "@/lib/api/client";
import { humanise } from "@/lib/utils";

const WIDTH = 720;
const HEIGHT = 380;
const MARGIN = { top: 16, right: 24, bottom: 40, left: 56 };

export interface RadarPoint {
  process: EmergingProcess;
  maturity: number;
  acceleration: number;
  breadth: number;
  sourceBreadth: number;
}

/**
 * Maturity comes from the archetype's machine, not from age.
 *
 * A Process discovered yesterday can be in Saturation and one running for three
 * years can still be in Discovery; the machine position is the claim being
 * made, and elapsed time is not.
 */
export function toPoints(
  processes: EmergingProcess[],
  machines: ArchetypeMachine[],
): RadarPoint[] {
  const maturityByState = new Map<string, number>();
  for (const machine of machines) {
    for (const node of machine.states ?? []) {
      maturityByState.set(`${machine.archetype}:${node.state}`, node.maturity);
    }
  }

  return processes.flatMap((process) => {
    if (!process.archetype || !process.current_state) return [];
    const maturity = maturityByState.get(
      `${process.archetype}:${process.current_state}`,
    );
    // A State that is not on its archetype's machine is a data defect, not a
    // point at the origin. Dropping it is better than drawing it somewhere
    // arbitrary and having someone read meaning into the position.
    if (maturity === undefined) return [];

    const acceleration =
      (process.components ?? []).find((c) => c.name === "evidence_acceleration")
        ?.normalised ?? 0;

    return [
      {
        process,
        maturity,
        acceleration,
        breadth: process.capability_count + process.asset_count,
        sourceBreadth: process.source_breadth,
      },
    ];
  });
}

export function EmergenceRadar({ points }: { points: RadarPoint[] }) {
  const router = useRouter();
  const [hovered, setHovered] = useState<RadarPoint | null>(null);

  const { x, y, r, opacity } = useMemo(() => {
    const maxBreadth = Math.max(...points.map((p) => p.breadth), 1);
    const maxSources = Math.max(...points.map((p) => p.sourceBreadth), 1);
    return {
      x: scaleLinear().domain([0, 1]).range([MARGIN.left, WIDTH - MARGIN.right]),
      y: scaleLinear().domain([0, 1]).range([HEIGHT - MARGIN.bottom, MARGIN.top]),
      // Area, not radius: a radius scale makes a Process with twice the breadth
      // look four times as large.
      r: scaleSqrt().domain([0, maxBreadth]).range([4, 22]),
      opacity: scaleLinear().domain([0, maxSources]).range([0.25, 0.9]),
    };
  }, [points]);

  if (points.length === 0) {
    return (
      <p className="rounded-panel border border-border bg-surface p-8 text-center text-sm text-ink-muted">
        No Process has both an archetype and a State on it yet, so there is
        nothing to place on the machine.
      </p>
    );
  }

  return (
    <figure className="rounded-panel border border-border bg-surface p-4">
      <figcaption className="mb-2 text-xs text-ink-muted">
        Evidence acceleration against position on the archetype&rsquo;s State
        machine. Processes in the upper left are moving early and quietly.{" "}
        <strong className="font-medium text-ink">
          A discovery view, not a forecast.
        </strong>
      </figcaption>

      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="w-full min-w-[40rem]"
          role="img"
          aria-label={`Emergence radar of ${points.length} Processes`}
        >
          {[0, 0.25, 0.5, 0.75, 1].map((tick) => (
            <g key={`grid-${tick}`}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--color-border)"
                strokeDasharray={tick === 0 ? undefined : "2 4"}
              />
              <text
                x={MARGIN.left - 8}
                y={y(tick)}
                textAnchor="end"
                dominantBaseline="middle"
                className="fill-[var(--color-ink-subtle)] text-[10px]"
              >
                {tick.toFixed(2)}
              </text>
            </g>
          ))}

          {[0, 0.5, 1].map((tick) => (
            <text
              key={`x-${tick}`}
              x={x(tick)}
              y={HEIGHT - MARGIN.bottom + 16}
              textAnchor="middle"
              className="fill-[var(--color-ink-subtle)] text-[10px]"
            >
              {tick === 0 ? "early" : tick === 1 ? "late" : "mid"}
            </text>
          ))}

          <text
            x={WIDTH / 2}
            y={HEIGHT - 6}
            textAnchor="middle"
            className="fill-[var(--color-ink-muted)] text-[11px]"
          >
            Maturity — position on the archetype&rsquo;s State machine
          </text>
          <text
            transform={`translate(14 ${HEIGHT / 2}) rotate(-90)`}
            textAnchor="middle"
            className="fill-[var(--color-ink-muted)] text-[11px]"
          >
            Evidence acceleration
          </text>

          {points.map((point) => (
            <circle
              key={point.process.id}
              cx={x(point.maturity)}
              cy={y(point.acceleration)}
              r={r(point.breadth)}
              fill="var(--color-accent)"
              fillOpacity={opacity(point.sourceBreadth)}
              stroke="var(--color-accent)"
              strokeWidth={hovered?.process.id === point.process.id ? 2 : 0.5}
              className="cursor-pointer"
              tabIndex={0}
              role="button"
              aria-label={`${point.process.name}, ${
                point.process.current_state
                  ? humanise(point.process.current_state)
                  : "no State"
              }`}
              onMouseEnter={() => setHovered(point)}
              onMouseLeave={() => setHovered(null)}
              onFocus={() => setHovered(point)}
              onBlur={() => setHovered(null)}
              onClick={() => router.push(`/processes/${point.process.id}`)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  router.push(`/processes/${point.process.id}`);
                }
              }}
            />
          ))}
        </svg>
      </div>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-4 text-xs">
        <p className="text-ink-subtle">
          Bubble size: downstream Capabilities and Assets —{" "}
          <span title="Not economic scope: that would need output and revenue data Phase 0 does not have">
            graph breadth
          </span>
          . Opacity: distinct publishers — media coverage, not market attention.
        </p>
        {hovered ? (
          <p className="text-ink" aria-live="polite">
            <span className="font-medium">{hovered.process.name}</span> ·{" "}
            {hovered.process.current_state
              ? humanise(hovered.process.current_state)
              : "no State"}{" "}
            · evidence {hovered.process.evidence_recent} vs{" "}
            {hovered.process.evidence_prior} · {hovered.breadth} downstream ·{" "}
            {hovered.sourceBreadth} publisher
            {hovered.sourceBreadth === 1 ? "" : "s"}
          </p>
        ) : null}
      </div>
    </figure>
  );
}
