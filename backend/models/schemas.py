from pydantic import BaseModel
from typing import Literal


class ScanRequest(BaseModel):
    address: str
    # When true, return map/score/template bullets immediately; call POST /scan/bullets for Gemini text.
    defer_gemini: bool = False


class Coordinate(BaseModel):
    lat: float
    lng: float


class LogisticsCard(BaseModel):
    type: str
    name: str
    category: str
    emoji: str
    distance_value: float
    distance_unit: Literal["feet", "miles"]
    color: str
    coordinates: Coordinate


class RestaurantBarCard(BaseModel):
    name: str
    category: str
    rating: float | None = None
    review_count: int | None = None
    price_level: str | None = None
    distance_value: float
    distance_unit: Literal["feet", "miles"]
    coordinates: Coordinate
    source: Literal["yelp", "google_places"]
    url: str | None = None
    ranking_score: float | None = None


class ThreatCard(BaseModel):
    id: str
    emoji: str
    title: str
    subtitle: str
    border_color: str
    text_color: str
    bullets: list[str]
    # quiet / watch / elevated = lower than / about / higher than typical NYC apartment locations.
    # unavailable = source did not answer; not_checked = no data source wired; tip = general advice.
    severity_level: Literal["quiet", "watch", "elevated", "unavailable", "not_checked", "tip"] = "unavailable"
    # Share of sampled NYC apartment locations with a lower count (0–100), when measured.
    nyc_percentile: int | None = None


class BulletsRequest(BaseModel):
    bullets_token: str


class BulletsResponse(BaseModel):
    threat_cards: list[ThreatCard]
    gemini_configured: bool = False
    gemini_status: str | None = None
    gemini_latency_ms: int | None = None
    gemini_timeout_seconds: float | None = None
    gemini_error_kind: str | None = None
    gemini_error_detail: str | None = None


class Zone(BaseModel):
    lat: float
    lng: float
    radius_meters: int
    color: str
    label: str
    # Record source + date, e.g. "311 request · Sep 30, 2026"
    detail: str | None = None


class SwarmPin(BaseModel):
    lat: float
    lng: float
    type: Literal["police", "rat", "permit", "truck", "bus", "noise", "fire", "water", "trash", "graffiti", "construction", "report"]
    label: str
    detail: str | None = None


class DataSource(BaseModel):
    key: str
    label: str
    status: Literal["ok", "unavailable"]
    count: int | None = None
    # ISO dates (YYYY-MM-DD). window_* = records counted; as_of = newest record the source has published.
    window_start: str | None = None
    window_end: str | None = None
    as_of: str | None = None
    provider: str
    note: str | None = None
    url: str | None = None


class FlightPath(BaseModel):
    start: Coordinate
    end: Coordinate
    label: str
    # Optional polyline for "real" tracks (ADS-B), ordered points.
    path: list[Coordinate] | None = None
    # Optional per-track stats (best-effort).
    closest_miles: float | None = None
    median_altitude_ft: int | None = None
    sample_count: int | None = None
    callsign: str | None = None
    airline: str | None = None
    flight_number: str | None = None
    last_seen_utc: str | None = None


class FlightExposure(BaseModel):
    # Distinct aircraft passes per covered hour inside the scan radius (a pass ends after 10 min unseen).
    night_overflights_per_hour: float
    day_overflights_per_hour: float
    # Typical altitude of nearby overflights (median), if available.
    typical_altitude_ft: int | None = None
    # "stable" vs "variable" based on recent history.
    trend: Literal["stable", "variable"] | None = None
    # "good" when we have consistent sampling; "sparse" when gaps are common.
    data_quality: Literal["good", "sparse", "unavailable"]
    # True only when exposure is materially above NYC baselines (show map + card).
    show_flight_feature: bool = False
    elevation_level: Literal["typical", "elevated", "high", "unavailable"] = "unavailable"
    night_percentile: float | None = None
    day_percentile: float | None = None
    combined_percentile: float | None = None
    headline: str | None = None
    detail: str | None = None
    observation_days: int | None = None
    radius_miles: float | None = None
    sample_count: int = 0


class MapData(BaseModel):
    target: Coordinate
    zones: list[Zone]
    swarm: list[SwarmPin]
    # Unique real geocodes among loaded records (may exceed len(swarm) when map caps pins for readability).
    swarm_location_total: int | None = None
    # True when only the newest records were loaded for the map, so more locations exist.
    swarm_total_is_lower_bound: bool = False
    # Municipal + flight overlay radius (miles) used for this scan.
    scan_radius_miles: float | None = None
    # Multiple nearby corridors (nearest first). `flight_path` is kept for backwards compatibility.
    flight_paths: list[FlightPath] = []
    flight_path: FlightPath | None = None


class PdfDossierRequest(BaseModel):
    dossier_token: str
    danger_score: int
    risk_level: Literal["LOW", "MODERATE", "HIGH", "EXTREME"] = "MODERATE"
    risk_label: str
    risk_description: str
    banner_driver: str | None = None
    threat_cards: list[ThreatCard]


class ScanResponse(BaseModel):
    address: str
    formatted_address: str
    coordinates: Coordinate
    danger_score: int
    risk_level: Literal["LOW", "MODERATE", "HIGH", "EXTREME"]
    risk_label: str
    risk_description: str
    # Primary factor behind banner copy: area_safety | 311 | permits | evictions | noise
    banner_driver: str | None = None
    # False when too few sources answered to compute a Wellness Score (danger_score is then 0 and unused).
    score_available: bool = True
    # Sources that answered vs. were unavailable, with the date range each count covers.
    data_sources: list[DataSource] = []
    # Day (YYYY-MM-DD) the NYC comparison counts were measured (backend/data/nyc_baselines.json).
    nyc_comparison_as_of: str | None = None
    logistics: list[LogisticsCard]
    dining: list[RestaurantBarCard] = []
    threat_cards: list[ThreatCard]
    map_data: MapData
    flight_exposure: FlightExposure | None = None
    # True when backend loaded a non-placeholder GEMINI_API_KEY for this scan (see /scan JSON in DevTools).
    gemini_configured: bool = False
    # Gemini call outcome — always present so callers can diagnose fallback reasons without reading logs.
    # gemini_status: "no_key" | "placeholder" | "timeout" | "error" | "ok"
    gemini_status: str | None = None
    gemini_latency_ms: int | None = None
    gemini_timeout_seconds: float | None = None
    # gemini_error_kind: "empty" | "json_parse" | "auth" | "quota" | "unknown" (set only on status="error")
    gemini_error_kind: str | None = None
    # Short, sanitized summary of the underlying exception (set only on status="error")
    gemini_error_detail: str | None = None
    # Present when defer_gemini=true and Gemini bullets were not awaited on /scan.
    bullets_token: str | None = None
    # Token for PDF dossier raw-data lookup (30 min TTL, in-memory).
    dossier_token: str | None = None
