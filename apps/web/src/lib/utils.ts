import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Confidence bands (ontology §35).
 *
 * Three bands rather than a continuous scale, because these numbers are model
 * belief and not calibrated probabilities. A UI that renders 0.71 as a precise
 * position on a gradient is making a claim the calibration framework has not
 * yet earned the right to make.
 */
export type ConfidenceBand = "high" | "medium" | "low";

export function confidenceBand(value: number): ConfidenceBand {
  if (value >= 0.75) return "high";
  if (value >= 0.5) return "medium";
  return "low";
}

const BAND_CLASS: Record<ConfidenceBand, string> = {
  high: "text-confidence-high",
  medium: "text-confidence-medium",
  low: "text-confidence-low",
};

export function confidenceClass(value: number): string {
  return BAND_CLASS[confidenceBand(value)];
}

/** Titles a snake_case ontology value for display without losing the original. */
export function humanise(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}
