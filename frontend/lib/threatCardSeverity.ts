import type { ThreatCard, ThreatSeverityLevel } from "./types";

export type ThreatSeverity = ThreatSeverityLevel;

const SEVERITY_LABEL: Record<ThreatSeverity, string> = {
  quiet: "Lower than most of NYC",
  watch: "About typical for NYC",
  elevated: "Higher than most of NYC",
  unavailable: "Unavailable",
  not_checked: "Not checked",
  tip: "Tip",
};

const SEVERITY_SHORT: Record<ThreatSeverity, string> = {
  quiet: "Lower",
  watch: "Typical",
  elevated: "Higher",
  unavailable: "Unavailable",
  not_checked: "Not checked",
  tip: "Tip",
};

export interface SeverityTone {
  /** Tag: soft fill + readable text; unmeasured levels get a dashed outline instead of a fill. */
  tag: string;
  /** Small square in lists and legends. */
  swatch: string;
  text: string;
  /** Hex for inline styles (percentile marker). */
  accent: string;
}

/** Diverging scale with a neutral middle: green lower, grey typical, red higher. */
const MISSING: SeverityTone = {
  tag: "border-dashed border-fg-3 bg-transparent text-fg-2",
  swatch: "hatch border border-fg-3",
  text: "text-fg-2",
  accent: "#63625B",
};

const SEVERITY_TONE: Record<ThreatSeverity, SeverityTone> = {
  quiet: {
    tag: "border-good/30 bg-good-soft text-good",
    swatch: "bg-good-fill",
    text: "text-good",
    accent: "#1E8C5A",
  },
  watch: {
    tag: "border-typical/25 bg-typical-soft text-typical",
    swatch: "bg-typical-fill",
    text: "text-typical",
    accent: "#77766E",
  },
  elevated: {
    tag: "border-bad/30 bg-bad-soft text-bad",
    swatch: "bg-bad-fill",
    text: "text-bad",
    accent: "#DD4527",
  },
  unavailable: MISSING,
  not_checked: MISSING,
  tip: {
    tag: "border-tip/25 bg-tip-soft text-tip",
    swatch: "bg-tip-fill",
    text: "text-tip",
    accent: "#2F6FE0",
  },
};

/** Summary order: what needs attention first. */
const SEVERITY_RANK: Record<ThreatSeverity, number> = {
  elevated: 0,
  watch: 1,
  quiet: 2,
  unavailable: 3,
  not_checked: 4,
  tip: 5,
};

/** Missing or unknown levels are "unavailable" — never shown as a good result. */
export function threatSeverity(card: ThreatCard): ThreatSeverity {
  const level = card.severity_level;
  return level && level in SEVERITY_LABEL ? level : "unavailable";
}

export function threatSeverityLabel(card: ThreatCard): string {
  return SEVERITY_LABEL[threatSeverity(card)];
}

export function threatSeverityShort(card: ThreatCard): string {
  return SEVERITY_SHORT[threatSeverity(card)];
}

export function threatSeverityTone(card: ThreatCard): SeverityTone {
  return SEVERITY_TONE[threatSeverity(card)];
}

export function threatSeverityRank(card: ThreatCard): number {
  return SEVERITY_RANK[threatSeverity(card)];
}

/** "Higher than at 82% of NYC apartment locations" for cards measured against NYC baselines. */
export function threatComparison(card: ThreatCard): string | null {
  const p = card.nyc_percentile;
  const level = threatSeverity(card);
  if (p == null || !(level === "quiet" || level === "watch" || level === "elevated")) return null;
  return p >= 50
    ? `Higher than at ${p}% of NYC apartment locations`
    : `Lower than at ${100 - p}% of NYC apartment locations`;
}
