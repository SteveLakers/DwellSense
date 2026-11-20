"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { Bus, MapPin, Plane, ShoppingBag, ShoppingCart, Star, TrainFront, TrainTrack } from "lucide-react";
import { LogisticsCard } from "@/lib/types";
import { isDiningCard, reviewCountLabel } from "@/lib/proximityCards";
import { distanceParts } from "@/lib/format";

/** Keys must match the LogisticsCard.type values set in backend/services/places.py. */
const TYPE_ICON: Record<string, LucideIcon> = {
  subway: TrainFront,
  train: TrainTrack,
  bus: Bus,
  grocery: ShoppingCart,
  targetstore: ShoppingCart,
  traderjoes: ShoppingCart,
  airport: Plane,
  mall: ShoppingBag,
};

/** Same ring and colour as the place's map pin. */
function PlaceGlyph({ card }: { card: LogisticsCard }) {
  const style = { color: card.color, borderColor: card.color };
  if (isDiningCard(card.type)) {
    const rank = Number(card.type.slice("dining-".length)) + 1;
    return (
      <span className="figure flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 bg-surface text-base" style={style}>
        {Number.isFinite(rank) ? rank : "•"}
      </span>
    );
  }
  const Icon = TYPE_ICON[card.type] ?? MapPin;
  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 bg-surface" style={style}>
      <Icon className="h-[18px] w-[18px]" aria-hidden />
    </span>
  );
}

interface Props {
  cards: LogisticsCard[];
  activeType: string | null;
  pinnedType: string | null;
  onHover: (type: string | null) => void;
  onTogglePin: (type: string) => void;
}

export default function NearbyPlaces({ cards, activeType, pinnedType, onHover, onTogglePin }: Props) {
  const listRef = useRef<HTMLUListElement>(null);
  const [moreBelow, setMoreBelow] = useState(false);

  const updateMoreBelow = useCallback(() => {
    const el = listRef.current;
    setMoreBelow(!!el && el.scrollHeight - el.scrollTop - el.clientHeight > 4);
  }, []);

  useEffect(() => {
    const el = listRef.current;
    updateMoreBelow();
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(updateMoreBelow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateMoreBelow, cards.length]);

  return (
    <section
      aria-labelledby="nearby-heading"
      className="relative flex flex-col overflow-hidden rounded-lg border-2 border-fg bg-surface lg:h-0 lg:min-h-full"
    >
      <div className="border-b-2 border-fg px-5 py-4">
        <h2 id="nearby-heading" className="heading text-[1.75rem]">
          Getting around
        </h2>
        <p className="mt-1 text-[15px] leading-snug text-fg-2">
          Transit, groceries and top-rated dining. Hover or tap a place to draw a line to it on the map.
        </p>
      </div>

      {cards.length ? (
        <ul
          ref={listRef}
          onScroll={updateMoreBelow}
          className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto sm:grid-cols-2 lg:grid-cols-1"
        >
          {cards.map((card, i) => {
            const dining = isDiningCard(card.type);
            const dist = distanceParts(card.distance_value, card.distance_unit);
            const active = activeType === card.type;
            return (
              <li key={card.type + i} className="border-b border-line">
                <button
                  type="button"
                  aria-pressed={pinnedType === card.type}
                  onMouseEnter={() => onHover(card.type)}
                  onMouseLeave={() => onHover(null)}
                  onFocus={() => onHover(card.type)}
                  onBlur={() => onHover(null)}
                  onClick={() => onTogglePin(card.type)}
                  className={[
                    "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors",
                    active ? "bg-brand-soft" : "hover:bg-canvas",
                  ].join(" ")}
                >
                  <PlaceGlyph card={card} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-fg-3">{card.category}</span>
                    <span className="block truncate text-[15px] font-semibold text-fg" title={card.name}>
                      {card.name}
                    </span>
                    {dining && card.rating != null ? (
                      <span className="mt-0.5 flex items-center gap-1 text-[13px] text-fg-2">
                        <Star className="h-3 w-3 fill-current text-fg" aria-hidden />
                        <span className="font-semibold text-fg">{card.rating.toFixed(1)}</span>
                        {card.review_count != null ? (
                          <span className="min-w-0 truncate">({reviewCountLabel(card)})</span>
                        ) : null}
                      </span>
                    ) : null}
                  </span>
                  <span className="shrink-0 text-right">
                    <span className="figure block text-[1.375rem]">{dist.value}</span>
                    <span className="block text-[13px] text-fg-3">{dist.unit}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="px-5 py-6 text-[15px] text-fg-2">No nearby places were returned for this address.</p>
      )}
      {moreBelow ? (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-surface to-transparent"
        />
      ) : null}
    </section>
  );
}
