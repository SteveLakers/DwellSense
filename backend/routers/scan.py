"""
POST /scan — the main endpoint.
Takes an address, runs all data lookups in parallel, and returns the full ScanResponse.
"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from models.schemas import (
    BulletsRequest,
    BulletsResponse,
    DataSource,
    FlightExposure,
    MapData,
    ScanRequest,
    ScanResponse,
    ThreatCard,
)
from services import (
    ai_analysis,
    city_data,
    dossier_context,
    flight_exposure,
    flight_preview,
    flights,
    geocoding,
    nyc_baselines,
    places,
    socrata,
)
from services.threat_card_layout import cards_from_specs_and_bullets, ordered_card_ids

router = APIRouter()
logger = logging.getLogger(__name__)

NYC_BOUNDS = {
    "lat_min": 40.4774,  # SW corner (approx)
    "lat_max": 40.9176,  # NE corner (approx)
    "lng_min": -74.2591,
    "lng_max": -73.7004,
}

_SEVERITIES = frozenset({"quiet", "watch", "elevated", "unavailable", "not_checked", "tip"})

# A city source that hasn't answered by then is shown as unavailable instead of holding up the report.
CITY_SOURCE_TIME_LIMIT_SECONDS = 30.0

# Same idea for the stored aircraft positions (Supabase): a slow or failing read must not hold up
# the report. flight_exposure gives up on its own after 20 s; this is the backstop for a hung request.
FLIGHT_READ_TIME_LIMIT_SECONDS = 25.0


async def _flight_read(work, default, what: str, *, pause_on_timeout: bool = True):
    """Await a flight lookup, but only for so long; on a timeout the report shows flights as unavailable."""
    try:
        return await asyncio.wait_for(work, FLIGHT_READ_TIME_LIMIT_SECONDS)
    except asyncio.TimeoutError:
        if pause_on_timeout:
            flight_exposure.pause_reads()  # don't start the same slow read again for the next minute
        logger.warning("%s: no answer within %.0f s; flights unavailable for this scan.",
                       what, FLIGHT_READ_TIME_LIMIT_SECONDS)
        return default


def _is_within_nyc(coord) -> bool:
    return (
        NYC_BOUNDS["lat_min"] <= coord.lat <= NYC_BOUNDS["lat_max"]
        and NYC_BOUNDS["lng_min"] <= coord.lng <= NYC_BOUNDS["lng_max"]
    )


def _threat_cards_from_ai(ai_result: dict) -> list[ThreatCard]:
    threat_cards: list[ThreatCard] = []
    for card in ai_result.get("threat_cards") or []:
        if not isinstance(card, dict):
            continue
        try:
            bullets = card.get("bullets")
            if not isinstance(bullets, list):
                bullets = []
            sev = str(card.get("severity_level", "unavailable"))
            if sev not in _SEVERITIES:
                sev = "unavailable"
            pct = card.get("nyc_percentile")
            threat_cards.append(
                ThreatCard(
                    id=str(card.get("id", "")),
                    emoji=str(card.get("emoji", "")),
                    title=str(card.get("title", "")),
                    subtitle=str(card.get("subtitle", "")),
                    border_color=str(card.get("border_color", "")),
                    text_color=str(card.get("text_color", "")),
                    bullets=[str(b) for b in bullets],
                    severity_level=sev,
                    nyc_percentile=int(pct) if isinstance(pct, (int, float)) else None,
                )
            )
        except Exception:
            logger.warning("Skipping malformed threat card", exc_info=True)
    if not threat_cards:
        fb_map = {cid: ["Details unavailable.", "", ""] for cid in ordered_card_ids()}
        threat_cards = [ThreatCard(**c) for c in cards_from_specs_and_bullets(fb_map)]
    return threat_cards


def _iso(d) -> str | None:
    return d.isoformat() if d else None


def _feed_source(feed: city_data.FeedResult) -> DataSource:
    return DataSource(
        key=feed.key,
        label=feed.label,
        status="ok" if feed.available else "unavailable",
        count=feed.total if feed.available else None,
        window_start=_iso(feed.window_start) if feed.available else None,
        window_end=_iso(feed.window_end) if feed.available else None,
        as_of=_iso(feed.as_of),
        provider="ZerMap copy of NYC Open Data" if feed.source == "zermap_copy" else "NYC Open Data",
        note=feed.note,
        url=f"https://data.cityofnewyork.us/d/{feed.dataset_ids[0]}" if feed.dataset_ids else None,
    )


def _flight_source(window: flight_exposure.AdsbWindow | None, exposure: FlightExposure | None) -> DataSource:
    if window is None or exposure is None or exposure.data_quality == "unavailable":
        return DataSource(
            key="flights", label="Aircraft positions (ADS-B)", status="unavailable",
            provider="adsb.lol via ZerMap's collector",
            note="Stored aircraft positions could not be read.",
        )
    if exposure.elevation_level == "unavailable":
        # Positions were read, but there are no NYC flight baselines to compare them with, so the
        # report has no flight section. Listing the source as used would suggest otherwise.
        return DataSource(
            key="flights", label="Aircraft positions (ADS-B)", status="unavailable",
            provider="adsb.lol via ZerMap's collector",
            note="Flight noise is paused: no NYC comparison is available for aircraft passes.",
        )
    newest = max((str(r.get("observed_at") or "") for r in window.rows), default="")
    newest_dt = flight_exposure.parse_ts(newest)
    return DataSource(
        key="flights",
        label="Aircraft positions (ADS-B)",
        status="ok",
        count=len(window.rows),
        window_start=window.since.astimezone(socrata.NYC_TZ).date().isoformat(),
        window_end=window.until.astimezone(socrata.NYC_TZ).date().isoformat(),
        as_of=newest_dt.astimezone(socrata.NYC_TZ).date().isoformat() if newest_dt else None,
        provider="adsb.lol via ZerMap's collector",
        note=f"{len(window.covered)} of {window.days * 24} hours recorded; counted as distinct passes.",
    )


@router.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest):
    address = request.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="Address cannot be empty.")

    # ── 1. Geocode the address ────────────────────────────────────────────────
    try:
        coord, formatted_address = await geocoding.geocode(address)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # NYC-only guardrail (product scope).
    if not _is_within_nyc(coord):
        raise HTTPException(
            status_code=400,
            detail="Out of reach — NYC addresses only.",
        )

    # ── 2. Fire all data lookups in parallel ──────────────────────────────────
    def limited(key: str, feed):
        return city_data.with_time_limit(key, feed, CITY_SOURCE_TIME_LIMIT_SECONDS)

    (
        crime,
        police_calls,
        reports_311,
        permits,
        evictions,
        logistics,
        dining_all,
        adsb_samples,
    ) = await asyncio.gather(
        limited("crime", city_data.get_crime_feed(coord)),
        limited("police_calls", city_data.get_police_calls_feed(coord)),
        limited("311", city_data.get_311_feed(coord)),
        limited("permits", city_data.get_permits_feed(coord)),
        limited("evictions", city_data.get_evictions_feed(coord)),
        places.get_logistics(coord),
        places.get_top_restaurants_bars(coord, limit=20),
        _flight_read(asyncio.to_thread(flight_exposure.fetch_raw_adsb_samples, coord), [], "ADS-B rows"),
    )
    dining = dining_all[:4]

    crime_rows = city_data.filter_rows_within_radius(coord, crime.rows)
    reports_rows = city_data.filter_rows_within_radius(coord, reports_311.rows)
    permit_rows = city_data.filter_rows_within_radius(coord, permits.rows)
    eviction_rows = city_data.filter_rows_within_radius(coord, evictions.rows)

    # ── 3. Flight exposure, then paths only when the flight section will be shown ─────
    # (compute_exposure reads nothing and returns "unavailable" while flight noise is paused.)
    exposure = await _flight_read(
        asyncio.to_thread(flight_exposure.compute_exposure, coord),
        flight_exposure.unavailable_exposure(),
        "Flight exposure",
    )

    # FLIGHT_UI_PREVIEW is a local-only layout aid that draws sample flights. Never while flight noise
    # is paused: a paused report must not show any flight content.
    preview = flight_preview.preview_enabled() and not flight_exposure.FLIGHT_NOISE_PAUSED
    if preview and exposure.data_quality == "unavailable":
        exposure = flight_preview.preview_exposure(
            coord, radius_miles=city_data.get_scan_radius_miles(), days=7
        )

    show_flight = bool(exposure and exposure.show_flight_feature)
    # The paths are a separate, heavier read: a slow one should not pause the exposure reads.
    flight_paths = (
        await _flight_read(flights.get_flight_paths(coord, limit=3), [], "Flight paths", pause_on_timeout=False)
        if show_flight else []
    )
    if show_flight and not flight_paths and preview:
        flight_paths = flight_preview.preview_flight_paths(coord)
    flight_path = flight_paths[0] if flight_paths else None

    # ── 4. Build map data ────────────────────────────────────────────────────
    zones = city_data.build_zones(crime_rows, reports_rows, permit_rows)
    swarm, swarm_total = city_data.build_swarm(crime_rows, reports_rows, permit_rows, coord)
    scan_radius_miles = city_data.get_scan_radius_miles()
    map_data = MapData(
        target=coord,
        zones=zones,
        swarm=swarm,
        swarm_location_total=swarm_total,
        swarm_total_is_lower_bound=crime.rows_sampled or reports_311.rows_sampled or permits.rows_sampled,
        scan_radius_miles=scan_radius_miles,
        flight_paths=flight_paths,
        flight_path=flight_path,
    )

    # ── 5. Score + cards (Gemini only adds bottom lines) ─────────────────────
    facts = ai_analysis.ScanFacts.build(
        crime=crime,
        police_calls=police_calls,
        reports_311=reports_311,
        permits=permits,
        evictions=evictions,
    )
    ai_result = await ai_analysis.analyze(
        address=formatted_address,
        coord=coord,
        facts=facts,
        logistics=logistics,
        flight_path=flight_path,
        flight_exposure=exposure,
        defer_gemini=request.defer_gemini,
    )

    # ── 6. Parse AI result into typed models ──────────────────────────────────
    threat_cards = _threat_cards_from_ai(ai_result)
    score_available = bool(ai_result.get("score_available", False))
    try:
        danger_score = max(0, min(100, int(ai_result.get("danger_score") or 0)))
    except (TypeError, ValueError):
        danger_score, score_available = 0, False

    _valid_risk = frozenset({"LOW", "MODERATE", "HIGH", "EXTREME"})
    risk_level = ai_result.get("risk_level", "MODERATE")
    if risk_level not in _valid_risk:
        risk_level = "MODERATE"

    label_text = str(ai_result.get("risk_label") or "Not scored")
    if not score_available:
        risk_label = label_text
    else:
        risk_emoji_map = {"EXTREME": "🚨", "HIGH": "⚠️", "MODERATE": "🟡", "LOW": "✅"}
        emoji = {"Outstanding": "🌟", "Excellent": "✨"}.get(label_text) or risk_emoji_map.get(risk_level, "⚠️")
        risk_label = f"{emoji} {label_text}"

    # Only needed for the source row; skipped when there is no exposure to describe (paused or unreadable).
    adsb_window = (
        await _flight_read(asyncio.to_thread(flight_exposure.load_adsb_window, coord), None, "ADS-B window")
        if exposure.data_quality != "unavailable" else None
    )
    data_sources = [_feed_source(f) for f in (crime, police_calls, reports_311, permits, evictions)]
    if not flight_exposure.FLIGHT_NOISE_PAUSED:
        # While flight noise is paused the report leaves flights out entirely (see the About page).
        data_sources.append(_flight_source(adsb_window, exposure))

    dossier_token = dossier_context.store_dossier(
        dossier_context.DossierContext(
            formatted_address=formatted_address,
            coord_lat=coord.lat,
            coord_lng=coord.lng,
            scan_radius_miles=scan_radius_miles,
            scanned_at=datetime.now(timezone.utc).isoformat(),
            crime=crime_rows,
            reports_311=reports_rows,
            permits=permit_rows,
            evictions=eviction_rows,
            feeds={f.key: dossier_context.feed_summary(f) for f in (crime, police_calls, reports_311, permits, evictions)},
            data_sources=[s.model_dump() for s in data_sources],
            score_available=score_available,
            logistics=[c.model_dump() for c in logistics],
            dining_candidates=[c.model_dump() for c in dining_all],
            flight_paths=[p.model_dump() for p in flight_paths],
            adsb_samples=adsb_samples,
            flight_exposure=exposure.model_dump() if exposure else None,
            map_swarm_shown=len(swarm),
            map_swarm_total=swarm_total,
            map_zones_count=len(zones),
        )
    )

    return ScanResponse(
        address=address,
        formatted_address=formatted_address,
        coordinates=coord,
        danger_score=danger_score,
        risk_level=risk_level,
        risk_label=risk_label,
        risk_description=ai_result.get("risk_description", ""),
        banner_driver=ai_result.get("banner_driver"),
        score_available=score_available,
        data_sources=data_sources,
        nyc_comparison_as_of=nyc_baselines.measured_on(),
        logistics=logistics,
        dining=dining,
        threat_cards=threat_cards,
        map_data=map_data,
        flight_exposure=exposure,
        gemini_configured=bool(ai_result.get("gemini_configured", False)),
        gemini_status=ai_result.get("gemini_status"),
        gemini_latency_ms=ai_result.get("gemini_latency_ms"),
        gemini_timeout_seconds=ai_result.get("gemini_timeout_seconds"),
        gemini_error_kind=ai_result.get("gemini_error_kind"),
        gemini_error_detail=ai_result.get("gemini_error_detail"),
        bullets_token=ai_result.get("bullets_token"),
        dossier_token=dossier_token,
    )


@router.post("/scan/bullets", response_model=BulletsResponse)
async def scan_bullets(request: BulletsRequest):
    token = request.bullets_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="bullets_token is required.")

    ai_result = await ai_analysis.complete_deferred_bullets(token)
    if not ai_result:
        raise HTTPException(
            status_code=404,
            detail="Bullets token expired or invalid. Re-run the scan to refresh summaries.",
        )

    return BulletsResponse(
        threat_cards=_threat_cards_from_ai(ai_result),
        gemini_configured=bool(ai_result.get("gemini_configured", False)),
        gemini_status=ai_result.get("gemini_status"),
        gemini_latency_ms=ai_result.get("gemini_latency_ms"),
        gemini_timeout_seconds=ai_result.get("gemini_timeout_seconds"),
        gemini_error_kind=ai_result.get("gemini_error_kind"),
        gemini_error_detail=ai_result.get("gemini_error_detail"),
    )
