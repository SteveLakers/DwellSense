"use client";

import { ScanResult } from "@/lib/types";
import { resolveBannerBreakdown } from "@/lib/bannerDriver";
import { sentenceCase, stripLeadingEmoji } from "@/lib/format";
import {
  threatSeverity,
  threatSeverityRank,
  threatSeverityShort,
  threatSeverityTone,
} from "@/lib/threatCardSeverity";

const RISK_TEXT: Record<ScanResult["risk_level"], string> = {
  EXTREME: "text-bad",
  HIGH: "text-bad",
  MODERATE: "text-typical",
  LOW: "text-good",
};

// Neutral ticks only: top-tier caps can hold the label below its band, so band names would contradict it.
const TICKS = Array.from({ length: 21 }, (_, i) => i * 5);

function ScoreRuler({ score, scored }: { score: number; scored: boolean }) {
  const p = Math.max(0, Math.min(100, score));
  return (
    <div className="relative mt-9 max-w-2xl" aria-hidden>
      {/* The border is an overlay so the fill and the needle share one width. */}
      <div className={`relative h-5 overflow-hidden rounded-sm bg-surface ${scored ? "" : "hatch"}`}>
        {scored ? <div className="ruler-fill absolute inset-y-0 left-0 bg-brand" style={{ width: `${p}%` }} /> : null}
        <span className="absolute inset-0 rounded-sm border-2 border-fg" />
      </div>
      {scored ? (
        <div className="ruler-needle absolute inset-x-0 -top-2 h-9" style={{ transform: `translateX(${p - 100}%)` }}>
          <span className="absolute inset-y-0 right-0 w-1 translate-x-1/2 rounded-full bg-fg" />
        </div>
      ) : null}
      <div className="relative mt-1.5 h-8 text-sm tnum text-fg-3">
        {TICKS.map((t) => {
          const major = t % 25 === 0;
          return (
            <span
              key={t}
              className={`absolute top-0 flex flex-col ${t === 0 ? "items-start" : t === 100 ? "-translate-x-full items-end" : "-translate-x-1/2 items-center"}`}
              style={{ left: `${t}%` }}
            >
              <span className={major ? "h-2.5 w-px bg-fg-2" : "h-1.5 w-px bg-fg-3"} />
              {major ? <span className="mt-0.5">{t}</span> : null}
            </span>
          );
        })}
      </div>
    </div>
  );
}

interface Props {
  result: ScanResult;
  onScrollToCard?: (cardId: string) => void;
}

export default function DangerBanner({ result, onScrollToCard }: Props) {
  const scored = result.score_available !== false;
  const breakdown = scored ? resolveBannerBreakdown(result) : null;
  const label = stripLeadingEmoji(result.risk_label);

  const glance = result.threat_cards
    .map((card, i) => ({ card, i }))
    .sort((a, b) => threatSeverityRank(a.card) - threatSeverityRank(b.card) || a.i - b.i)
    .map(({ card }) => card);
  const higher = result.threat_cards.filter((c) => threatSeverity(c) === "elevated").length;

  return (
    <section aria-labelledby="score-heading" className="wrap mt-12 lg:mt-16">
      <div className="grid gap-12 lg:grid-cols-12 lg:gap-14">
        <div className="lg:col-span-7">
          <h2 id="score-heading" className="text-[15px] font-semibold text-fg-2">
            Wellness Score
          </h2>
          {scored ? (
            <div className="mt-3 flex flex-wrap items-end gap-x-7 gap-y-3">
              <p className="flex items-end gap-2">
                <span className="figure block overflow-hidden pt-[0.03em] text-[7.5rem] leading-[0.78] sm:text-[11rem]">
                  <span className="rise">{result.danger_score}</span>
                </span>
                <span className="pb-1 text-lg font-semibold text-fg-3">/ 100</span>
              </p>
              <p className={`heading text-[2.5rem] leading-none sm:text-[3.5rem] ${RISK_TEXT[result.risk_level] ?? "text-typical"}`}>
                {label}
              </p>
            </div>
          ) : (
            <p className="heading mt-3 text-[3rem] sm:text-[4rem]">{label}</p>
          )}

          <ScoreRuler score={result.danger_score} scored={scored} />

          <p className="mt-6 max-w-2xl text-[17px] leading-relaxed text-fg">{result.risk_description}</p>
          {breakdown && onScrollToCard ? (
            <button type="button" onClick={() => onScrollToCard(breakdown.cardId)} className="text-link mt-4 text-base">
              {breakdown.label}
            </button>
          ) : null}
          {process.env.NODE_ENV !== "production" && result.gemini_configured === false ? (
            <p className="mt-5 max-w-xl rounded border border-dashed border-fg-3 px-3 py-2 text-sm leading-snug text-fg-2">
              Dev note: the backend reports Gemini is off (<code className="font-mono text-fg">gemini_configured: false</code>),
              so cards show the fact bullets only. Set <code className="font-mono text-fg">GEMINI_API_KEY</code> in{" "}
              <code className="font-mono text-fg">backend/.env</code> and restart to add the takeaway line.
            </p>
          ) : null}
        </div>

        {glance.length ? (
          <div className="self-start rounded-lg border-2 border-fg bg-surface lg:col-span-5">
            <div className="on-ink grain-ink flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-t-md bg-ink px-5 py-4 text-white">
              <h3 className="heading text-[1.5rem]">At a glance</h3>
              <p className="text-sm text-ink-muted">
                <span className="font-semibold text-white">
                  {higher} of {result.threat_cards.length}
                </span>{" "}
                higher than most of NYC
              </p>
            </div>
            <ul className="divide-y divide-line">
              {glance.map((card) => {
                const tone = threatSeverityTone(card);
                return (
                  <li key={card.id}>
                    <button
                      type="button"
                      onClick={() => onScrollToCard?.(card.id)}
                      className="group flex min-h-[44px] w-full items-center justify-between gap-3 px-5 py-2.5 text-left transition-colors hover:bg-canvas"
                    >
                      <span className="flex min-w-0 items-center gap-3">
                        <span aria-hidden className={`h-3 w-3 shrink-0 rounded-[2px] ${tone.swatch}`} />
                        <span className="truncate text-[15px] font-medium text-fg underline-offset-[3px] group-hover:underline">
                          {sentenceCase(card.title)}
                        </span>
                      </span>
                      <span className={`shrink-0 text-sm font-semibold ${tone.text}`}>{threatSeverityShort(card)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
      </div>
    </section>
  );
}
