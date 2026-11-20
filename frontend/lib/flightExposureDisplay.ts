import type { FlightExposure, FlightPath } from "./types";

/** Plain-language frequency bucket for planes per hour. */
export function flightFrequencyLabel(ratePerHour: number): string {
  if (ratePerHour < 0.2) return "Rare";
  if (ratePerHour < 0.7) return "Occasional";
  if (ratePerHour < 2) return "Fairly common";
  return "Frequent";
}

/** One-sentence takeaway for renters. */
export function flightNoiseSummary(exposure: FlightExposure): string {
  const nightP = exposure.night_percentile ?? 0;
  const dayP = exposure.day_percentile ?? 0;

  if (nightP >= 0.78 || (nightP >= 0.6 && exposure.night_overflights_per_hour >= 0.8)) {
    return "Planes fly over often at night, more than at most NYC apartment locations.";
  }
  if (nightP >= 0.6) {
    return "More overnight flights than at most NYC apartment locations.";
  }
  if (dayP >= 0.68) {
    return "Busier daytime air traffic than at most NYC apartment locations.";
  }
  if (exposure.elevation_level === "high") {
    return "This block sees noticeably more planes than typical NYC apartment locations.";
  }
  return "More aircraft pass here than at typical NYC apartment locations.";
}

export type FlightComparisonTier = "below" | "average" | "above";

/**
 * NYC-relative tier from the highest of the night / day / combined percentiles — the same basis
 * the backend uses for the flight card's severity, so the badge never contradicts the card.
 */
export function flightComparisonTier(exposure: FlightExposure): FlightComparisonTier {
  const p = Math.max(
    exposure.night_percentile ?? 0,
    exposure.day_percentile ?? 0,
    exposure.combined_percentile ?? 0,
  );
  if (p >= 0.54) return "above";
  if (p >= 0.42) return "average";
  return "below";
}

export function flightElevationBadge(exposure: FlightExposure): string {
  const tier = flightComparisonTier(exposure);
  if (tier === "above") {
    return exposure.elevation_level === "high"
      ? "Well above typical for NYC"
      : "Above typical for NYC";
  }
  if (tier === "average") return "About typical for NYC";
  return "Below typical for NYC";
}

export function flightElevationBadgeClasses(exposure: FlightExposure): string {
  const tier = flightComparisonTier(exposure);
  if (tier === "above") {
    return exposure.elevation_level === "high" ? "border-bad bg-bad text-white" : "border-bad/30 bg-bad-soft text-bad";
  }
  if (tier === "average") {
    return "border-typical/25 bg-typical-soft text-typical";
  }
  return "border-good/30 bg-good-soft text-good";
}

/** Short note about altitude when flights are low enough to hear. */
export function flightAltitudeNote(exposure: FlightExposure): string | null {
  const alt = exposure.typical_altitude_ft;
  if (alt == null || alt > 3200) return null;
  return `Many planes pass around ${alt.toLocaleString()} ft, low enough to hear from the street.`;
}

/** Human-readable recent track line (no ADS-B jargon). */
export function formatFlightPathPlain(path: FlightPath): string {
  const parts: string[] = [];
  if (path.closest_miles != null) {
    parts.push(`about ${path.closest_miles.toFixed(1)} mi from this address`);
  }
  const alt = path.median_altitude_ft;
  if (alt != null) {
    parts.push(`around ${alt.toLocaleString()} ft`);
  }
  if (!parts.length) return "A recent plane route is drawn on the map in cyan.";
  return `Recent plane route ${parts.join(", ")}.`;
}

export function formatObservationWindow(exposure: FlightExposure): string {
  const days = exposure.observation_days ?? 7;
  const mi = exposure.radius_miles ?? 2;
  const miLabel = Number.isInteger(mi) ? `${mi}` : mi.toFixed(1);
  return (
    `Based on ${days} ${days === 1 ? "day" : "days"} of flight tracking within ~${miLabel} mi. ` +
    "Each aircraft counts once per pass, even if it circles, until it’s gone for 10 minutes."
  );
}

/** Large figure for the night/day tiles: the rate, or "Rare" when it is below 0.2/hr. */
export function flightRateDisplay(ratePerHour: number): { value: string; unit: string } {
  if (ratePerHour < 0.2) return { value: "Rare", unit: "usually quiet" };
  return { value: ratePerHour.toFixed(1), unit: "passes / hour" };
}
