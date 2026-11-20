import { formatCount, plural } from "./format";
import { LogisticsCard, RestaurantBarCard } from "./types";

const DINING_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"] as const;
const DINING_COLOR = "#B45309";
const REVIEW_PROVIDER: Record<RestaurantBarCard["source"], string> = {
  google_places: "Google",
  yelp: "Yelp",
};

/**
 * Pin, route and list colour by LogisticsCard.type. The backend's colours were picked for a dark map;
 * these read on the light map and pass 4.5:1 on white. Unknown types keep the backend colour.
 */
const PLACE_COLOR: Record<string, string> = {
  subway: "#047857",
  train: "#6D28D9",
  bus: "#4D7C0F",
  grocery: "#1D4ED8",
  targetstore: "#B91C1C",
  traderjoes: "#C2410C",
  airport: "#334155",
  mall: "#0E7490",
};

export function isDiningCard(type: string): boolean {
  return type.startsWith("dining-");
}

/** e.g. "2,310 Google reviews" — names the provider so the rating is attributable. */
export function reviewCountLabel(card: LogisticsCard): string | null {
  if (card.review_count == null) return null;
  const provider = card.source ? REVIEW_PROVIDER[card.source] : undefined;
  return [formatCount(card.review_count), provider, plural(card.review_count, "review")]
    .filter(Boolean)
    .join(" ");
}

/** Merge transit/grocery logistics with top 4 dining cards for one proximity bar + map routes. */
export function buildProximityCards(
  logistics: LogisticsCard[],
  dining?: RestaurantBarCard[] | null,
): LogisticsCard[] {
  const places = logistics.map((card) => ({ ...card, color: PLACE_COLOR[card.type] ?? card.color }));
  const diningCards = (dining ?? []).slice(0, 4).map((card, index) => ({
    type: `dining-${index}`,
    name: card.name,
    category: card.category || "Restaurant / Bar",
    emoji: DINING_EMOJIS[index] ?? "🍽️",
    distance_value: card.distance_value,
    distance_unit: card.distance_unit,
    color: DINING_COLOR,
    coordinates: card.coordinates,
    rating: card.rating ?? null,
    review_count: card.review_count ?? null,
    url: card.url ?? null,
    source: card.source,
  }));
  return [...places, ...diningCards];
}
