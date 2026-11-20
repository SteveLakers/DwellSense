export interface Coordinate {
  lat: number;
  lng: number;
}

export interface LogisticsCard {
  type: string;
  name: string;
  category: string;
  emoji: string;
  distance_value: number;
  distance_unit: "feet" | "miles";
  color: string;
  coordinates: Coordinate;
  /** Present on dining cards merged into the proximity bar */
  rating?: number | null;
  review_count?: number | null;
  url?: string | null;
  /** Provider behind rating / review_count on dining cards */
  source?: RestaurantBarCard["source"];
}

export interface RestaurantBarCard {
  name: string;
  category: string;
  rating?: number | null;
  review_count?: number | null;
  price_level?: string | null;
  distance_value: number;
  distance_unit: "feet" | "miles";
  coordinates: Coordinate;
  source: "yelp" | "google_places";
  url?: string | null;
  ranking_score?: number | null;
}

export type ThreatSeverityLevel =
  | "quiet"
  | "watch"
  | "elevated"
  /** Source didn't answer during the scan. */
  | "unavailable"
  /** ZerMap doesn't load this data yet (e.g. HPD violations). */
  | "not_checked"
  /** General guidance, not measured for this address. */
  | "tip";

export interface ThreatCard {
  id: string;
  emoji: string;
  title: string;
  subtitle: string;
  border_color: string;
  text_color: string;
  bullets: string[];
  severity_level?: ThreatSeverityLevel;
  /** Share (0–100) of sampled NYC apartment locations with a lower count. */
  nyc_percentile?: number | null;
}

export interface Zone {
  lat: number;
  lng: number;
  radius_meters: number;
  color: string;
  label: string;
  /** Source and date, e.g. "NYPD complaint · Jun 12, 2026". */
  detail?: string | null;
}

export interface SwarmPin {
  lat: number;
  lng: number;
  type:
    | "police"
    | "rat"
    | "permit"
    | "truck"
    | "bus"
    | "noise"
    | "fire"
    | "water"
    | "trash"
    | "graffiti"
    | "construction"
    | "report";
  label: string;
  /** Source and date, e.g. "311 request · Sep 30, 2026". */
  detail?: string | null;
}

export interface FlightPath {
  start: Coordinate;
  end: Coordinate;
  label: string;
  /** Optional polyline points (ADS‑B tracks). */
  path?: Coordinate[] | null;
  closest_miles?: number | null;
  median_altitude_ft?: number | null;
  sample_count?: number | null;
  callsign?: string | null;
  airline?: string | null;
  flight_number?: string | null;
  last_seen_utc?: string | null;
}

export interface FlightExposure {
  night_overflights_per_hour: number;
  day_overflights_per_hour: number;
  typical_altitude_ft?: number | null;
  trend?: "stable" | "variable" | null;
  data_quality: "good" | "sparse" | "unavailable";
  /** True when exposure is materially above NYC baselines — show map lines + threat card. */
  show_flight_feature?: boolean;
  elevation_level?: "typical" | "elevated" | "high" | "unavailable";
  night_percentile?: number | null;
  day_percentile?: number | null;
  combined_percentile?: number | null;
  headline?: string | null;
  detail?: string | null;
  observation_days?: number | null;
  radius_miles?: number | null;
  sample_count?: number;
}

export interface MapData {
  target: Coordinate;
  zones: Zone[];
  swarm: SwarmPin[];
  /** Total unique real geocodes in the scan radius (may exceed swarm.length). */
  swarm_location_total?: number | null;
  /** True when only the newest records were loaded, so swarm_location_total is a lower bound. */
  swarm_total_is_lower_bound?: boolean;
  /** Scan radius in miles (municipal data + flight path filter). */
  scan_radius_miles?: number | null;
  flight_paths?: FlightPath[];
  /** Back-compat: some responses include a single path */
  flight_path?: FlightPath | null;
}

export interface DataSource {
  key: string;
  label: string;
  status: "ok" | "unavailable";
  count?: number | null;
  /** ISO dates (YYYY-MM-DD) of the records counted. */
  window_start?: string | null;
  window_end?: string | null;
  /** Newest record the source had published at scan time. */
  as_of?: string | null;
  provider?: string | null;
  note?: string | null;
  url?: string | null;
}

export interface ScanResult {
  address: string;
  formatted_address: string;
  coordinates: Coordinate;
  danger_score: number;
  risk_level: "LOW" | "MODERATE" | "HIGH" | "EXTREME";
  risk_label: string;
  risk_description: string;
  /** Primary wellness banner factor — maps to a threat card breakdown link. */
  banner_driver?: string | null;
  /** False when too few sources answered to compute a Wellness Score. */
  score_available?: boolean;
  data_sources?: DataSource[];
  /** Day (YYYY-MM-DD) the NYC comparison counts were measured. */
  nyc_comparison_as_of?: string | null;
  logistics: LogisticsCard[];
  dining?: RestaurantBarCard[];
  threat_cards: ThreatCard[];
  map_data: MapData;
  flight_exposure?: FlightExposure | null;
  /** From backend: whether a real GEMINI_API_KEY was loaded (check Network → /api/scan response). */
  gemini_configured?: boolean;
  gemini_status?: string | null;
  gemini_latency_ms?: number | null;
  bullets_token?: string | null;
  /** Token for full raw-data PDF dossier (30 min TTL). */
  dossier_token?: string | null;
}
