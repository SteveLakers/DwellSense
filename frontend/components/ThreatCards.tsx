"use client";

import type { LucideIcon } from "lucide-react";
import {
  CircleHelp,
  ClipboardList,
  Construction,
  DoorOpen,
  LoaderCircle,
  MessageSquareWarning,
  Plane,
  ShieldAlert,
  Siren,
  Sun,
  Volume2,
} from "lucide-react";
import { ThreatCard } from "@/lib/types";
import { sentenceCase } from "@/lib/format";
import { threatComparison, threatSeverityLabel, threatSeverityTone } from "@/lib/threatCardSeverity";
import SectionHeading from "./SectionHeading";

/** Card ids from backend threat_card_layout.CARD_SPECS. */
const CARD_ICON: Record<string, LucideIcon> = {
  high_churn: DoorOpen,
  police_calls: Siren,
  area_safety: ShieldAlert,
  tenant_warnings: MessageSquareWarning,
  demolitions: Construction,
  noise_schedule: Volume2,
  flight_path: Plane,
  reports_311: ClipboardList,
  oven_effect: Sun,
};

const HIGHLIGHT = "bg-brand-soft";

export function scrollToThreatCard(cardId: string) {
  const el = document.getElementById(`threat-card-${cardId}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add(HIGHLIGHT);
  window.setTimeout(() => el.classList.remove(HIGHLIGHT), 1800);
}

/** Where this address sits among sampled NYC apartment locations (0 = fewest records). */
function PercentileScale({ percentile, accent, label }: { percentile: number; accent: string; label: string }) {
  const p = Math.max(0, Math.min(100, percentile));
  return (
    <div className="mt-5 max-w-sm">
      <p className="text-[15px] font-medium text-fg">{label}</p>
      <div className="relative mt-3 h-2 rounded-sm bg-surface-3" aria-hidden>
        <span className="absolute left-1/2 top-1/2 h-4 w-px -translate-y-1/2 bg-fg-3" />
        <span
          className="absolute top-1/2 h-5 w-2 -translate-x-1/2 -translate-y-1/2 rounded-[2px] border-2 border-fg"
          style={{ left: `${p}%`, backgroundColor: accent }}
        />
      </div>
      <div className="mt-2 grid grid-cols-3 text-[13px] text-fg-3" aria-hidden>
        <span>Lower</span>
        <span className="text-center">Median</span>
        <span className="text-right">Higher</span>
      </div>
    </div>
  );
}

function ThreatRow({ card }: { card: ThreatCard }) {
  const tone = threatSeverityTone(card);
  const comparison = threatComparison(card);
  const Icon = CARD_ICON[card.id] ?? CircleHelp;
  const bullets = card.bullets.filter((b) => b.trim());

  return (
    <li
      id={`threat-card-${card.id}`}
      className="grid scroll-mt-24 gap-5 border-b border-line px-1 py-8 transition-colors duration-500 lg:grid-cols-12 lg:gap-10"
    >
      <div className="lg:col-span-5">
        <div className="flex flex-wrap items-center gap-3">
          <Icon className="h-5 w-5 text-fg-2" aria-hidden />
          <span className={`inline-flex rounded border px-2 py-0.5 text-sm font-semibold ${tone.tag}`}>
            {threatSeverityLabel(card)}
          </span>
        </div>
        <h3 className="heading mt-4 text-[1.875rem]">{sentenceCase(card.title)}</h3>
        <p className="mt-2 text-[15px] leading-relaxed text-fg-2">{card.subtitle}</p>
        {card.nyc_percentile != null && comparison ? (
          <PercentileScale percentile={card.nyc_percentile} accent={tone.accent} label={comparison} />
        ) : null}
      </div>

      {bullets.length ? (
        <ul className="space-y-3 text-base leading-relaxed text-fg lg:col-span-7 lg:pt-1">
          {bullets.map((b, j) => (
            <li key={j} className="flex gap-3">
              <span aria-hidden className="mt-[9px] h-1.5 w-1.5 shrink-0 bg-fg" />
              <span className="min-w-0">{b}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

interface Props {
  cards: ThreatCard[];
  bulletsRefreshing?: boolean;
}

export default function ThreatCards({ cards, bulletsRefreshing = false }: Props) {
  return (
    <section aria-labelledby="threat-analysis" className="wrap mt-20 lg:mt-28">
      <SectionHeading
        id="threat-analysis"
        title="What the records show"
        description={`${cards.length} checks. Measured ones compare this address with apartment locations sampled across NYC.`}
        action={
          bulletsRefreshing ? (
            <span className="tag" role="status">
              <LoaderCircle className="h-3.5 w-3.5 animate-spin" aria-hidden />
              Refining AI summaries…
            </span>
          ) : null
        }
      />
      <ol className="mt-8 border-t-[3px] border-fg">
        {cards.map((card) => (
          <ThreatRow key={card.id} card={card} />
        ))}
      </ol>
    </section>
  );
}
