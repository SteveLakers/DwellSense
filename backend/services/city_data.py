"""
NYC municipal signals for one scan address.

Counts come straight from NYC Open Data (Socrata) aggregate queries inside a true
circle, so they are exact and never truncated. A capped set of rows is fetched
separately for map pins and the PDF dossier. Legacy DOB BIS permits are the one
exception: a citywide list is kept in memory and filtered by distance per scan.

If NYC Open Data does not answer, the Supabase copy written by
jobs/daily_refresh.py is used — but only when it is fresh. Otherwise the feed is
reported as unavailable (never as zero).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import math
import os
import re
import threading
import time
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Callable, Literal

from supabase import create_client, Client

from models.schemas import Coordinate, Zone, SwarmPin
from services import socrata
from services.socrata import SocrataError, nyc_today, soql_day_end, soql_ts

logger = logging.getLogger(__name__)


def get_scan_radius_miles() -> float:
    """Haversine search radius for crime / 311 / permits / evictions (address at center)."""
    try:
        return max(0.25, min(10.0, float(os.getenv("SCAN_RADIUS_MILES", "2"))))
    except ValueError:
        return 2.0


def get_scan_radius_meters() -> float:
    return get_scan_radius_miles() * 1609.344


# ── Datasets + windows ────────────────────────────────────────────────────────

CRIME_DATASET = "5uac-w243"          # NYPD Complaint Data Current (Year To Date) — quarterly
POLICE_CALLS_DATASET = "n2zq-pubd"   # NYPD Calls for Service (Year to Date) — quarterly
REPORTS_311_DATASET = "erm2-nwe9"    # 311 Service Requests — daily
PERMITS_BIS_DATASET = "ipu4-2q9a"    # DOB Permit Issuance (legacy BIS) — daily
PERMITS_NOW_DATASET = "rbx6-tga4"    # DOB NOW: Build – Approved Permits — daily
EVICTIONS_DATASET = "6z8x-wfk4"      # Evictions executed by NYC Marshals — daily

# NYPD windows end at the newest published record (the city releases them quarterly).
CRIME_DAYS_BACK = 30
POLICE_CALLS_DAYS_BACK = 30
REPORTS_311_DAYS_BACK = 30
PERMIT_DAYS_BACK = 90
EVICTION_DAYS_BACK = 180

# Rows loaded for map pins / PDF tables. Counts never depend on these.
CRIME_ROW_LIMIT = 2000
REPORTS_ROW_LIMIT = 3000
PERMITS_NOW_ROW_LIMIT = 1500
PERMITS_BIS_ROW_LIMIT = 300
EVICTIONS_ROW_LIMIT = 1000

MAJOR_FELONY_VIOLENT = frozenset({
    "MURDER & NON-NEGL. MANSLAUGHTER",
    "RAPE",
    "ROBBERY",
    "FELONY ASSAULT",
})
MAJOR_FELONY_PROPERTY = frozenset({
    "BURGLARY",
    "GRAND LARCENY",
    "GRAND LARCENY OF MOTOR VEHICLE",
})

POLICE_CALL_TIERS = ("Critical", "Serious", "Non Critical")

# Work that changes what neighbors see and hear (excludes plumbing, sprinklers, signs, solar …).
DISRUPTIVE_NOW_WORK_TYPES = (
    "General Construction",
    "Structural",
    "Foundation",
    "Earth Work",
    "Support of Excavation",
    "Full Demolition",
    "Sidewalk Shed",
    "Supported Scaffold",
    "Suspended Scaffold",
    "Construction Fence",
    "Protection and Mechanical Methods",
)
_BIS_PERMIT_LABELS = {
    "NB": "New Building",
    "DM": "Full Demolition",
    "FO": "Foundation",
}
_BIS_EQUIPMENT_LABELS = {
    "FN": "Construction Fence",
    "SH": "Sidewalk Shed",
    "SF": "Supported Scaffold",
}
DEMOLITION_WORK_TYPES = frozenset({"Full Demolition"})
SCAFFOLD_WORK_TYPES = frozenset({"Sidewalk Shed", "Supported Scaffold", "Suspended Scaffold"})


# ── Query filters (shared by counts and PDF source links) ─────────────────────

def _radius(radius_miles: float | None) -> float:
    return radius_miles if radius_miles is not None else get_scan_radius_miles()


def crime_where(coord: Coordinate, start: date, end: date, *, radius_miles: float | None = None) -> str:
    return (
        f"{socrata.within_circle('lat_lon', coord, _radius(radius_miles))} "
        f"AND cmplnt_fr_dt between '{soql_ts(start)}' and '{soql_day_end(end)}'"
    )


def police_calls_where(coord: Coordinate, start: date, end: date, *, radius_miles: float | None = None) -> str:
    tiers = ", ".join(f"'{t}'" for t in POLICE_CALL_TIERS)
    return (
        f"{socrata.numeric_circle('latitude', 'longitude', coord, _radius(radius_miles))} "
        f"AND incident_date between '{soql_ts(start)}' and '{soql_day_end(end)}' "
        f"AND cip_jobs in ({tiers})"
    )


def reports_311_where(
    coord: Coordinate, start: date, *, radius_miles: float | None = None, exclude_parking: bool = False
) -> str:
    where = (
        f"{socrata.within_circle('location', coord, _radius(radius_miles))} "
        f"AND created_date >= '{soql_ts(start)}'"
    )
    return f"{where} AND {soql_311_parking_exclusion()}" if exclude_parking else where


def permits_now_where(coord: Coordinate, start: date, today: date, *, radius_miles: float | None = None) -> str:
    work_types = ", ".join(f"'{t}'" for t in DISRUPTIVE_NOW_WORK_TYPES)
    return (
        f"{socrata.numeric_circle('latitude', 'longitude', coord, _radius(radius_miles))} "
        f"AND issued_date >= '{soql_ts(start)}' AND permit_status = 'Permit Issued' "
        f"AND expired_date >= '{soql_ts(today)}' AND work_type in ({work_types})"
    )


def bis_type_filter() -> str:
    """Disruptive BIS permit kinds (same set _bis_label accepts)."""
    basic = ", ".join(f"'{k}'" for k in _BIS_PERMIT_LABELS)
    equipment = ", ".join(f"'{k}'" for k in _BIS_EQUIPMENT_LABELS)
    return (
        f"(permit_type in ({basic}) OR (permit_type = 'AL' AND job_type = 'A1') "
        f"OR (permit_type = 'EQ' AND permit_subtype in ({equipment})))"
    )


def bis_citywide_where(start: date, today: date) -> str:
    """Active disruptive BIS permits citywide (with coordinates).

    BIS stores dates and coordinates as text, so these casts scan all ~4M rows (60-100 s
    when NYC Open Data's cache is cold). Run it off the request path, never per scan.
    """
    return (
        f"issuance_date::floating_timestamp >= '{soql_ts(start)}' "
        f"AND permit_status in ('ISSUED', 'RE-ISSUED') "
        f"AND expiration_date::floating_timestamp >= '{soql_ts(today)}' "
        f"AND {bis_type_filter()} AND gis_latitude IS NOT NULL"
    )


def evictions_where(coord: Coordinate, start: date, *, radius_miles: float | None = None) -> str:
    return (
        f"{socrata.numeric_circle('latitude::number', 'longitude::number', coord, _radius(radius_miles))} "
        f"AND executed_date >= '{soql_ts(start)}' AND residential_commercial_ind = 'Residential'"
    )


# ── Feed result ───────────────────────────────────────────────────────────────

FeedSource = Literal["nyc_open_data", "zermap_copy"]


@dataclass
class FeedResult:
    key: str
    label: str
    status: Literal["ok", "unavailable"]
    total: int | None = None
    rows: list[dict] = field(default_factory=list)
    breakdown: dict[str, int] = field(default_factory=dict)
    top_types: list[tuple[str, int]] = field(default_factory=list)
    window_start: date | None = None
    window_end: date | None = None
    as_of: date | None = None
    source: FeedSource = "nyc_open_data"
    rows_sampled: bool = False
    dataset_ids: tuple[str, ...] = ()
    note: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.status == "ok" and self.total is not None

    def count(self) -> int:
        return int(self.total or 0) if self.available else 0

    def part(self, name: str) -> int:
        return int(self.breakdown.get(name, 0)) if self.available else 0


def _unavailable(key: str, label: str, datasets: tuple[str, ...], note: str) -> FeedResult:
    return FeedResult(key=key, label=label, status="unavailable", dataset_ids=datasets, note=note)


# Feed key -> (label, NYC Open Data datasets).
FEEDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "crime": ("NYPD complaints", (CRIME_DATASET,)),
    "police_calls": ("NYPD crime-in-progress calls", (POLICE_CALLS_DATASET,)),
    "311": ("311 service requests", (REPORTS_311_DATASET,)),
    "permits": ("DOB construction permits", (PERMITS_NOW_DATASET, PERMITS_BIS_DATASET)),
    "evictions": ("Residential evictions", (EVICTIONS_DATASET,)),
}
_NO_RESPONSE_NOTE = "NYC Open Data did not respond."
# A feed whose requests stopped at the limit returns its own result within this margin.
_TIME_LIMIT_GRACE_SECONDS = 2.0


async def with_time_limit(key: str, feed: Coroutine[Any, Any, FeedResult], seconds: float) -> FeedResult:
    """
    Run a feed for at most `seconds`: its NYC Open Data requests give up at the limit
    (socrata.time_limit), and a feed still running just after it is reported unavailable.
    """
    with socrata.time_limit(seconds):
        task = asyncio.create_task(feed)
    try:
        return await asyncio.wait_for(task, seconds + _TIME_LIMIT_GRACE_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("%s: no answer within %.0f s — unavailable.", key, seconds)
        label, datasets = FEEDS[key]
        return _unavailable(key, label, datasets, _NO_RESPONSE_NOTE)


def _window(days: int, end: date) -> tuple[date, date]:
    return end - timedelta(days=days - 1), end


def format_window(start: date | None, end: date | None) -> str:
    """'Jun 1–30, 2026' · 'Sep 3 – Oct 2, 2026' · 'Dec 5, 2025 – Jan 3, 2026'."""
    if not start or not end:
        return ""
    if start.year != end.year:
        return f"{start:%b} {start.day}, {start.year} – {end:%b} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"
    return f"{start:%b} {start.day}–{end.day}, {end.year}"


def _top(counter: dict[str, int], n: int = 5) -> list[tuple[str, int]]:
    return sorted(((k, v) for k, v in counter.items() if k and v > 0), key=lambda kv: (-kv[1], kv[0]))[:n]


def _int(raw: object) -> int:
    try:
        return int(float(str(raw)))
    except (TypeError, ValueError):
        return 0


def _float(raw: object) -> float | None:
    try:
        v = float(str(raw))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v != 0 else None


# ── 311 classification (shared by counts, map pins, PDF) ──────────────────────

_PARKING_CTYPE_KEYS = (
    "parking",
    "vehicle",
    "traffic",
    "highway",
    "gridlock",
    "taxi",
    "tlc",
    "for-hire",
    "for hire",
    "commuter van",
    "tow",
    "license plate",
    "abandoned vehicle",
    "blocked driveway",
    "hydrant",
)
_PARKING_DESC_KEYS = (
    "illegal parking",
    "no parking",
    "double parked",
    "double-parked",
    "hydrant",
    "blocked hydrant",
    "blocked driveway",
    "commercial vehicle",
    "gridlock",
    "traffic",
    "tlc",
    "taxi",
    "tow",
    "abandoned vehicle",
)
_PARKING_ANY_KEYS = ("parking", "parked")


def _is_parking_vehicle_noise_complaint(row: dict) -> bool:
    """
    NYC 311 includes a huge volume of parking / vehicle / traffic complaints.
    These are not renter safety signals for lease decisions, so we exclude them
    from scoring, map pins, and AI briefs.
    """
    ctype = (row.get("complaint_type") or "").lower()
    desc = (row.get("descriptor") or "").lower()
    return any(k in ctype for k in _PARKING_CTYPE_KEYS + _PARKING_ANY_KEYS) or any(
        k in desc for k in _PARKING_DESC_KEYS + _PARKING_ANY_KEYS
    )


def soql_311_parking_exclusion() -> str:
    """SoQL equivalent of _is_parking_vehicle_noise_complaint (for source links)."""
    ctype = " OR ".join(f"upper(complaint_type) like '%{k.upper()}%'" for k in _PARKING_CTYPE_KEYS + _PARKING_ANY_KEYS)
    desc = " OR ".join(f"upper(descriptor) like '%{k.upper()}%'" for k in _PARKING_DESC_KEYS + _PARKING_ANY_KEYS)
    return f"(complaint_type IS NULL OR NOT ({ctype})) AND (descriptor IS NULL OR NOT ({desc}))"


def _filter_311_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if not _is_parking_vehicle_noise_complaint(r)]


def _311_blob(row: dict) -> str:
    return f"{row.get('complaint_type') or ''} {row.get('descriptor') or ''}".lower()


_311_NOISE_KEYS = ("noise", "loud", "music", "party")
# Words NYC itself puts on construction complaints (complaint type or descriptor). "building" is
# deliberately not one of them: it matches the descriptor "ENTIRE BUILDING" on HEAT/HOT WATER
# complaints (70% of the matches in Nov 2026) and "Hitting Building" on tree complaints, and the
# "Building/Use" type is about illegal conversions and zoning, not construction work.
_311_CONSTRUCTION_KEYS = ("construction", "scaffold", "demolition", "crane")


def is_311_noise(row: dict) -> bool:
    return any(k in _311_blob(row) for k in _311_NOISE_KEYS)


def is_311_construction(row: dict) -> bool:
    return any(k in _311_blob(row) for k in _311_CONSTRUCTION_KEYS)


def _soql_311_keywords(keys: tuple[str, ...]) -> str:
    return "(" + " OR ".join(
        f"upper({col}) like '%{k.upper()}%'" for k in keys for col in ("complaint_type", "descriptor")
    ) + ")"


def soql_311_noise() -> str:
    return _soql_311_keywords(_311_NOISE_KEYS)


def soql_311_construction() -> str:
    return _soql_311_keywords(_311_CONSTRUCTION_KEYS)


# ── Supabase copy (fallback only) ─────────────────────────────────────────────

_supabase_reachable: bool | None = None  # None = untested, True/False = known


def _get_client() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("Supabase credentials are not set in environment variables.")
    global _supabase_reachable
    if _supabase_reachable is False:
        raise RuntimeError("Supabase DNS unavailable (cached failure).")
    return create_client(url, key)


_thread_local = threading.local()


def thread_client() -> Client:
    """One Supabase client per worker thread for parallel paged reads."""
    client = getattr(_thread_local, "client", None)
    if client is None:
        client = _get_client()
        _thread_local.client = client
    return client


def _bbox(coord: Coordinate, radius_miles: float) -> dict:
    lat_delta = radius_miles / 69.0
    lng_delta = radius_miles / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    return {
        "lat_min": coord.lat - lat_delta,
        "lat_max": coord.lat + lat_delta,
        "lng_min": coord.lng - lng_delta,
        "lng_max": coord.lng + lng_delta,
    }


def _grid_bboxes(coord: Coordinate, radius_miles: float, *, n: int = 4) -> list[dict]:
    """Split the scan bbox into an N×N grid so each cell pages independently."""
    bb = _bbox(coord, radius_miles)
    lat_step = (bb["lat_max"] - bb["lat_min"]) / n
    lng_step = (bb["lng_max"] - bb["lng_min"]) / n
    return [
        {
            "lat_min": bb["lat_min"] + i * lat_step,
            "lat_max": bb["lat_min"] + (i + 1) * lat_step,
            "lng_min": bb["lng_min"] + j * lng_step,
            "lng_max": bb["lng_min"] + (j + 1) * lng_step,
        }
        for i in range(n)
        for j in range(n)
    ]


def copy_fallback_enabled() -> bool:
    """The copy is only trustworthy once jobs/daily_refresh.py has completed full-window runs.

    Freshness alone can't prove completeness (older imports stored partial windows), so the
    fallback stays off until COPY_FALLBACK_ENABLED=true is set deliberately.
    """
    return os.getenv("COPY_FALLBACK_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


_COPY_PAGE = 1000  # Supabase PostgREST max rows per request
_COPY_MAX_ROWS_PER_CELL = 20_000
_copy_latest_cache: dict[tuple[str, str], tuple[float, date | None]] = {}
_copy_latest_lock = threading.Lock()


def _copy_latest(client: Client, table: str, date_col: str) -> date | None:
    key = (table, date_col)
    now = time.monotonic()
    with _copy_latest_lock:
        hit = _copy_latest_cache.get(key)
    if hit and now - hit[0] < 600:
        return hit[1]
    res = client.table(table).select(date_col).order(date_col, desc=True).limit(1).execute()
    latest = socrata.parse_date((res.data or [{}])[0].get(date_col)) if res.data else None
    with _copy_latest_lock:
        _copy_latest_cache[key] = (now, latest)
    return latest


def _copy_rows(
    table: str,
    select: str,
    coord: Coordinate,
    *,
    date_col: str,
    start: date,
    end: date | None = None,
) -> tuple[list[dict], bool]:
    """Every copy row in the scan bbox + window (paged per grid cell), then a true circle."""
    radius = get_scan_radius_miles()

    def fetch_cell(bb: dict) -> tuple[list[dict], bool]:
        local = thread_client()
        out: list[dict] = []
        offset = 0
        while offset < _COPY_MAX_ROWS_PER_CELL:
            q = (
                local.table(table)
                .select(select)
                .gte("lat", bb["lat_min"])
                .lt("lat", bb["lat_max"])
                .gte("lng", bb["lng_min"])
                .lt("lng", bb["lng_max"])
                .gte(date_col, start.isoformat())
            )
            if end is not None:
                q = q.lte(date_col, f"{end.isoformat()}T23:59:59")
            page = q.order("id").range(offset, offset + _COPY_PAGE - 1).execute().data or []
            out.extend(page)
            if len(page) < _COPY_PAGE:
                return out, False
            offset += _COPY_PAGE
        return out, True

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(fetch_cell, _grid_bboxes(coord, radius)))
    rows: list[dict] = []
    seen: set[str] = set()
    truncated = False
    for cell_rows, cell_truncated in results:
        truncated = truncated or cell_truncated
        for row in cell_rows:
            sid = str(row.get("source_id") or "")
            if sid and sid in seen:
                continue
            if sid:
                seen.add(sid)
            rows.append(row)
    return filter_rows_within_radius(coord, rows), truncated


def _from_copy(
    *,
    key: str,
    table: str,
    select: str,
    date_col: str,
    coord: Coordinate,
    days: int,
    expected_latest: date,
    max_staleness_days: int,
    window_end: date | None,
    build: Callable[[list[dict]], tuple[list[dict], int, dict[str, int], list[tuple[str, int]]]],
    reason: str,
) -> FeedResult:
    """
    Supabase copy fallback. Used only when the copy's newest record is within
    max_staleness_days of expected_latest; window_end=None ends the window there.
    """
    global _supabase_reachable
    label, datasets = FEEDS[key]
    unavailable_note = _NO_RESPONSE_NOTE
    if not copy_fallback_enabled():
        logger.warning("%s: NYC Open Data failed (%s); copy fallback disabled — unavailable.", key, reason)
        return _unavailable(key, label, datasets, unavailable_note)
    logger.warning("%s: NYC Open Data failed (%s) — checking the ZerMap copy.", key, reason)
    try:
        client = _get_client()
        latest = _copy_latest(client, table, date_col)
        _supabase_reachable = True
    except Exception as e:
        if "nodename nor servname" in str(e) or "DNS" in str(e).upper():
            _supabase_reachable = False
        logger.warning("%s: ZerMap copy unavailable (%s)", key, e)
        return _unavailable(key, label, datasets, unavailable_note)

    if latest is None or (expected_latest - latest).days > max_staleness_days:
        logger.warning("%s: ZerMap copy is stale (newest %s, expected ~%s)", key, latest, expected_latest)
        return _unavailable(key, label, datasets, unavailable_note)

    start, end = _window(days, window_end or latest)
    try:
        raw, truncated = _copy_rows(table, select, coord, date_col=date_col, start=start, end=end)
    except Exception as e:
        logger.warning("%s: ZerMap copy query failed (%s)", key, e)
        return _unavailable(key, label, datasets, unavailable_note)
    if truncated:
        return _unavailable(key, label, datasets, "Too many records to count from the ZerMap copy.")

    rows, total, breakdown, top = build(raw)
    logger.info("%s: %s records from the ZerMap copy (newest %s).", key, total, latest)
    return FeedResult(
        key=key,
        label=label,
        status="ok",
        total=total,
        rows=rows,
        breakdown=breakdown,
        top_types=top,
        window_start=start,
        window_end=end,
        as_of=latest,
        source="zermap_copy",
        dataset_ids=datasets,
        note=f"From ZerMap's nightly copy of NYC Open Data (newest record {latest:%b %-d, %Y}).",
    )


# ── Crime (NYPD complaints) ───────────────────────────────────────────────────

def _crime_breakdown(groups: list[tuple[str, str, int]]) -> tuple[int, dict[str, int], list[tuple[str, int]]]:
    total = 0
    breakdown = {"violent": 0, "property": 0, "felony": 0, "misdemeanor": 0, "violation": 0}
    by_offense: dict[str, int] = {}
    for offense, law_cat, n in groups:
        total += n
        offense = (offense or "").strip().upper()
        if offense in MAJOR_FELONY_VIOLENT:
            breakdown["violent"] += n
        elif offense in MAJOR_FELONY_PROPERTY:
            breakdown["property"] += n
        cat = (law_cat or "").strip().upper()
        if cat == "FELONY":
            breakdown["felony"] += n
        elif cat == "MISDEMEANOR":
            breakdown["misdemeanor"] += n
        elif cat == "VIOLATION":
            breakdown["violation"] += n
        if offense:
            by_offense[offense] = by_offense.get(offense, 0) + n
    breakdown["major_felonies"] = breakdown["violent"] + breakdown["property"]
    return total, breakdown, _top(by_offense)


def _normalize_crime_row(r: dict) -> dict | None:
    lat = _float(r.get("latitude"))
    lng = _float(r.get("longitude"))
    if lat is None or lng is None:
        return None
    return {
        "lat": lat,
        "lng": lng,
        "crime_type": r.get("ofns_desc") or "UNKNOWN",
        "description": r.get("pd_desc") or "",
        "law_category": r.get("law_cat_cd") or "",
        "occurred_at": r.get("cmplnt_fr_dt") or "",
        "source_id": str(r.get("cmplnt_num") or ""),
    }


async def _no_rows() -> tuple[list[dict], bool]:
    return [], False


def _display_latest(dataset_id: str, column: str) -> date | None:
    """
    Newest record date for feeds whose window ends today, so it is display-only.
    A failed lookup leaves the date blank instead of making the whole feed unavailable.
    """
    try:
        return socrata.latest_date(dataset_id, column, ttl_seconds=3600)
    except SocrataError as e:
        logger.warning("%s: newest record date unavailable (%s)", dataset_id, e)
        return None


async def get_crime_feed(coord: Coordinate, *, include_rows: bool = True) -> FeedResult:
    """NYPD complaints within the scan radius over the newest 30 days NYPD has published."""
    key = "crime"
    label, datasets = FEEDS[key]
    try:
        as_of = await asyncio.to_thread(socrata.latest_date, CRIME_DATASET, "cmplnt_fr_dt", ttl_seconds=6 * 3600)
        start, end = _window(CRIME_DAYS_BACK, as_of)
        where = crime_where(coord, start, end)
        groups_raw, (rows_raw, _) = await asyncio.gather(
            asyncio.to_thread(
                socrata.query,
                CRIME_DATASET,
                {"$select": "ofns_desc, law_cat_cd, count(*) as n", "$where": where,
                 "$group": "ofns_desc, law_cat_cd", "$limit": 5000},
            ),
            asyncio.to_thread(
                socrata.query_all,
                CRIME_DATASET,
                where=where,
                select="cmplnt_num, cmplnt_fr_dt, ofns_desc, pd_desc, law_cat_cd, latitude, longitude",
                order="cmplnt_fr_dt DESC, cmplnt_num",
                page_size=CRIME_ROW_LIMIT,
                max_rows=CRIME_ROW_LIMIT,
            ) if include_rows else _no_rows(),
        )
    except SocrataError as e:
        return await asyncio.to_thread(_crime_from_copy, coord, str(e))

    total, breakdown, top = _crime_breakdown(
        [(g.get("ofns_desc", ""), g.get("law_cat_cd", ""), _int(g.get("n"))) for g in groups_raw]
    )
    rows = [r for r in (_normalize_crime_row(x) for x in rows_raw) if r]
    logger.info("Crime: %s complaints (%s–%s), %s rows loaded.", total, start, end, len(rows))
    return FeedResult(
        key=key, label=label, status="ok", total=total, rows=rows, breakdown=breakdown, top_types=top,
        window_start=start, window_end=end, as_of=as_of, rows_sampled=len(rows) < total, dataset_ids=datasets,
    )


def _crime_from_copy(coord: Coordinate, reason: str) -> FeedResult:
    # NYPD publishes quarterly; without a known release date accept a copy up to
    # one release cycle old and end the window at its newest complaint.
    release = socrata.cached_latest_date(CRIME_DATASET, "cmplnt_fr_dt")

    def build(raw: list[dict]):
        rows = [{**r, "law_category": ""} for r in raw]
        by_offense: dict[str, int] = {}
        for r in rows:
            offense = str(r.get("crime_type") or "").upper()
            by_offense[offense] = by_offense.get(offense, 0) + 1
        total, breakdown, top = _crime_breakdown([(k, "", v) for k, v in by_offense.items()])
        for k in ("felony", "misdemeanor", "violation"):
            breakdown.pop(k, None)
        rows.sort(key=lambda r: str(r.get("occurred_at") or ""), reverse=True)
        return rows, total, breakdown, top

    return _from_copy(
        key="crime", table="crime_reports",
        select="lat, lng, crime_type, description, occurred_at, source_id", date_col="occurred_at",
        coord=coord, days=CRIME_DAYS_BACK,
        expected_latest=release or nyc_today(), max_staleness_days=3 if release else 120,
        window_end=release, build=build, reason=reason,
    )


# ── Police calls (NYPD crime-in-progress calls for service) ───────────────────

async def get_police_calls_feed(coord: Coordinate) -> FeedResult:
    """Crime-in-progress calls to NYPD (critical / serious / non-critical) in the newest 30 days published."""
    key = "police_calls"
    label, datasets = FEEDS[key]
    try:
        as_of = await asyncio.to_thread(
            socrata.latest_date, POLICE_CALLS_DATASET, "incident_date", ttl_seconds=6 * 3600
        )
        start, end = _window(POLICE_CALLS_DAYS_BACK, as_of)
        where = police_calls_where(coord, start, end)
        groups = await asyncio.to_thread(
            socrata.query,
            POLICE_CALLS_DATASET,
            {"$select": "cip_jobs, typ_desc, count(*) as n", "$where": where,
             "$group": "cip_jobs, typ_desc", "$limit": 5000},
            timeout=60.0,
        )
    except SocrataError as e:
        logger.warning("Police calls: NYC Open Data failed (%s).", e)
        return _unavailable(key, label, datasets, _NO_RESPONSE_NOTE)

    breakdown = {"critical": 0, "serious": 0, "non_critical": 0}
    tier_keys = {"Critical": "critical", "Serious": "serious", "Non Critical": "non_critical"}
    by_type: dict[str, int] = {}
    for g in groups:
        n = _int(g.get("n"))
        tier = tier_keys.get(str(g.get("cip_jobs") or ""))
        if tier:
            breakdown[tier] += n
        name = str(g.get("typ_desc") or "")
        if name:
            by_type[name] = by_type.get(name, 0) + n
    total = sum(breakdown.values())
    top = _top(by_type)
    logger.info("Police calls: %s crime-in-progress calls (%s–%s).", total, start, end)
    return FeedResult(
        key=key, label=label, status="ok", total=total, breakdown=breakdown, top_types=top,
        window_start=start, window_end=end, as_of=as_of, dataset_ids=datasets,
    )


# ── 311 service requests ──────────────────────────────────────────────────────

def _summarize_311_groups(
    groups: list[tuple[str, str, int]],
) -> tuple[int, dict[str, int], list[tuple[str, int]], list[tuple[str, int]]]:
    """(total, breakdown, top complaint types, top noise types) after the parking filter."""
    total = 0
    breakdown = {"noise": 0, "construction": 0, "excluded_parking_vehicle": 0}
    by_type: dict[str, int] = {}
    noise_by_type: dict[str, int] = {}
    for ctype, desc, n in groups:
        row = {"complaint_type": ctype, "descriptor": desc}
        if _is_parking_vehicle_noise_complaint(row):
            breakdown["excluded_parking_vehicle"] += n
            continue
        total += n
        name = " ".join(str(ctype or "").split())
        if is_311_noise(row):
            breakdown["noise"] += n
            if name:
                noise_by_type[name] = noise_by_type.get(name, 0) + n
        if is_311_construction(row):
            breakdown["construction"] += n
        if name:
            by_type[name] = by_type.get(name, 0) + n
    return total, breakdown, _top(by_type), _top(noise_by_type, 3)


def _normalize_311_row(r: dict) -> dict | None:
    lat = _float(r.get("latitude"))
    lng = _float(r.get("longitude"))
    if lat is None or lng is None:
        return None
    return {
        "lat": lat,
        "lng": lng,
        "complaint_type": r.get("complaint_type") or "UNKNOWN",
        "descriptor": r.get("descriptor") or "",
        "created_at": r.get("created_date") or "",
        "source_id": str(r.get("unique_key") or ""),
    }


async def get_311_feed(coord: Coordinate, *, include_rows: bool = True) -> FeedResult:
    """311 requests in the last 30 days (parking / vehicle complaints excluded)."""
    key = "311"
    label, datasets = FEEDS[key]
    try:
        as_of = await asyncio.to_thread(_display_latest, REPORTS_311_DATASET, "created_date")
        start, end = _window(REPORTS_311_DAYS_BACK, nyc_today())
        where = reports_311_where(coord, start)
        groups_raw, (rows_raw, _) = await asyncio.gather(
            asyncio.to_thread(
                socrata.query,
                REPORTS_311_DATASET,
                {"$select": "complaint_type, descriptor, count(*) as n", "$where": where,
                 "$group": "complaint_type, descriptor", "$limit": 50000},
                timeout=60.0,
            ),
            asyncio.to_thread(
                socrata.query_all,
                REPORTS_311_DATASET,
                where=where,
                select="unique_key, created_date, complaint_type, descriptor, latitude, longitude",
                order="created_date DESC, unique_key",
                page_size=REPORTS_ROW_LIMIT,
                max_rows=REPORTS_ROW_LIMIT,
            ) if include_rows else _no_rows(),
        )
    except SocrataError as e:
        return await asyncio.to_thread(_311_from_copy, coord, str(e))

    total, breakdown, top, noise_top = _summarize_311_groups(
        [(g.get("complaint_type", ""), g.get("descriptor", ""), _int(g.get("n"))) for g in groups_raw]
    )
    rows = _filter_311_rows([r for r in (_normalize_311_row(x) for x in rows_raw) if r])
    logger.info("311: %s requests after the parking/vehicle filter, %s rows loaded.", total, len(rows))
    return FeedResult(
        key=key, label=label, status="ok", total=total, rows=rows, breakdown=breakdown, top_types=top,
        window_start=start, window_end=end, as_of=as_of, rows_sampled=len(rows) < total, dataset_ids=datasets,
        extra={"noise_top": noise_top},
    )


def _311_from_copy(coord: Coordinate, reason: str) -> FeedResult:
    def build(raw: list[dict]):
        counts: dict[tuple[str, str], int] = {}
        for r in raw:
            k = (str(r.get("complaint_type") or ""), str(r.get("descriptor") or ""))
            counts[k] = counts.get(k, 0) + 1
        total, breakdown, top, _ = _summarize_311_groups([(c, d, n) for (c, d), n in counts.items()])
        rows = _filter_311_rows(raw)
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return rows, total, breakdown, top

    return _from_copy(
        key="311", table="reports_311",
        select="lat, lng, complaint_type, descriptor, created_at, source_id", date_col="created_at",
        coord=coord, days=REPORTS_311_DAYS_BACK, expected_latest=nyc_today(), max_staleness_days=2,
        window_end=nyc_today(), build=build, reason=reason,
    )


# ── DOB construction permits (DOB NOW + legacy BIS) ───────────────────────────

def _bis_label(permit_type: str, subtype: str, job_type: str) -> str | None:
    p = (permit_type or "").strip().upper()
    if p in _BIS_PERMIT_LABELS:
        return _BIS_PERMIT_LABELS[p]
    if p == "AL" and (job_type or "").strip().upper() == "A1":
        return "Major Alteration"
    if p == "EQ":
        return _BIS_EQUIPMENT_LABELS.get((subtype or "").strip().upper())
    return None


def _permit_breakdown(by_type: dict[str, int]) -> dict[str, int]:
    return {
        "demolition": sum(n for t, n in by_type.items() if t in DEMOLITION_WORK_TYPES),
        "scaffold_shed": sum(n for t, n in by_type.items() if t in SCAFFOLD_WORK_TYPES),
        "new_building": by_type.get("New Building", 0),
    }


# Active BIS permits are a few hundred citywide, so main.py loads them all every few hours
# and each scan keeps the ones inside its circle (see bis_citywide_where for why).
BIS_SNAPSHOT_REFRESH_HOURS = 3
BIS_SNAPSHOT_MAX_AGE_SECONDS = 6 * 3600
BIS_SNAPSHOT_WAIT_SECONDS = 40.0
_BIS_SNAPSHOT_MAX_ROWS = 50_000
_BIS_SELECT = (
    "permit_si_no, job__, permit_type, permit_subtype, job_type, issuance_date, "
    "expiration_date, house__, street_name, gis_latitude, gis_longitude"
)


@dataclass
class _BisSnapshot:
    loaded_at: float  # time.monotonic()
    rows: list[dict]


_bis_snapshot: _BisSnapshot | None = None
_bis_loading: threading.Event | None = None
_bis_lock = threading.Lock()


def _parse_bis_row(r: dict) -> dict | None:
    label = _bis_label(r.get("permit_type", ""), r.get("permit_subtype", ""), r.get("job_type", ""))
    lat, lng = _float(r.get("gis_latitude")), _float(r.get("gis_longitude"))
    issued = socrata.parse_date(r.get("issuance_date"))
    expires = socrata.parse_date(r.get("expiration_date"))
    if not label or lat is None or lng is None or issued is None or expires is None or not r.get("permit_si_no"):
        return None
    return {**r, "_label": label, "_lat": lat, "_lng": lng, "_issued": issued, "_expires": expires}


def _load_bis_snapshot(done: threading.Event) -> None:
    global _bis_snapshot, _bis_loading
    started = time.monotonic()
    try:
        today = nyc_today()
        start, _ = _window(PERMIT_DAYS_BACK, today)
        raw, truncated = socrata.query_all(
            PERMITS_BIS_DATASET, where=bis_citywide_where(start, today), select=_BIS_SELECT,
            order="permit_si_no", page_size=_BIS_SNAPSHOT_MAX_ROWS, max_rows=_BIS_SNAPSHOT_MAX_ROWS,
            timeout=150.0,
        )
        if truncated:
            raise SocrataError(f"{PERMITS_BIS_DATASET}: more than {_BIS_SNAPSHOT_MAX_ROWS} active permits")
        rows = [p for p in (_parse_bis_row(r) for r in raw) if p]
        if len(rows) < len(raw):
            logger.warning("DOB BIS list: skipped %s rows without a usable type, date or location.", len(raw) - len(rows))
        with _bis_lock:
            _bis_snapshot = _BisSnapshot(loaded_at=time.monotonic(), rows=rows)
        logger.info("DOB BIS list: %s active permits citywide (%.0f s).", len(rows), time.monotonic() - started)
    except SocrataError as e:
        logger.warning("DOB BIS list refresh failed after %.0f s: %s", time.monotonic() - started, e)
    finally:
        with _bis_lock:
            _bis_loading = None
        done.set()


def _begin_bis_load() -> tuple[threading.Event, bool]:
    """(event set when the running load ends, whether the caller must run it)."""
    global _bis_loading
    with _bis_lock:
        if _bis_loading is not None:
            return _bis_loading, False
        _bis_loading = threading.Event()
        return _bis_loading, True


def refresh_bis_snapshot() -> None:
    """Reload the citywide BIS list; returns at once if a load is already running."""
    done, owner = _begin_bis_load()
    if owner:
        _load_bis_snapshot(done)


def _fresh_bis_rows() -> list[dict] | None:
    with _bis_lock:
        snap = _bis_snapshot
    if snap and time.monotonic() - snap.loaded_at < BIS_SNAPSHOT_MAX_AGE_SECONDS:
        return snap.rows
    return None


def bis_permits_near(coord: Coordinate, start: date, today: date, *, radius_miles: float | None = None) -> list[dict]:
    """
    Active BIS permits inside the scan circle, newest first. Without a fresh citywide list
    (cold start), starts a load and waits up to BIS_SNAPSHOT_WAIT_SECONDS (less if the scan's
    time limit ends first), then raises SocrataError so the permits feed is unavailable rather
    than missing BIS permits.
    """
    rows = _fresh_bis_rows()
    if rows is None:
        done, owner = _begin_bis_load()
        if owner:
            # Empty context: the scan's time limit must not cut the citywide load short.
            threading.Thread(
                target=contextvars.Context().run, args=(_load_bis_snapshot, done), name="bis-list", daemon=True
            ).start()
        left = socrata.time_left()
        done.wait(BIS_SNAPSHOT_WAIT_SECONDS if left is None else max(0.0, min(BIS_SNAPSHOT_WAIT_SECONDS, left)))
        rows = _fresh_bis_rows()
        if rows is None:
            raise SocrataError(f"{PERMITS_BIS_DATASET}: citywide permit list is not loaded")
    limit_m = _radius(radius_miles) * 1609.344
    near = [
        r for r in rows
        if r["_issued"] >= start and r["_expires"] >= today
        and _haversine_meters(coord.lat, coord.lng, r["_lat"], r["_lng"]) <= limit_m
    ]
    near.sort(key=lambda r: (r["_issued"], str(r["permit_si_no"])), reverse=True)
    return near


async def get_permits_feed(coord: Coordinate, *, include_rows: bool = True) -> FeedResult:
    """
    Active DOB permits for disruptive work issued in the last 90 days
    (still open: not signed off, not expired). DOB NOW holds most current permits;
    legacy BIS permits (from the citywide list) are added so older job filings are not missed.
    """
    key = "permits"
    label, datasets = FEEDS[key]
    today = nyc_today()
    start, end = _window(PERMIT_DAYS_BACK, today)
    now_where = permits_now_where(coord, start, today)
    try:
        as_of_now, as_of_bis, now_total_raw, now_groups, bis_near, (now_rows_raw, _) = (
            await asyncio.gather(
                asyncio.to_thread(_display_latest, PERMITS_NOW_DATASET, "issued_date"),
                asyncio.to_thread(_display_latest, PERMITS_BIS_DATASET, "dobrundate"),
                asyncio.to_thread(
                    socrata.query, PERMITS_NOW_DATASET,
                    {"$select": "count(distinct work_permit) as n", "$where": now_where},
                ),
                asyncio.to_thread(
                    socrata.query, PERMITS_NOW_DATASET,
                    {"$select": "work_type, count(distinct work_permit) as n", "$where": now_where,
                     "$group": "work_type"},
                ),
                asyncio.to_thread(bis_permits_near, coord, start, today),
                asyncio.to_thread(
                    socrata.query_all, PERMITS_NOW_DATASET, where=now_where,
                    select=("work_permit, work_type, job_description, issued_date, expired_date, "
                            "house_no, street_name, latitude, longitude"),
                    order="issued_date DESC, work_permit",
                    page_size=PERMITS_NOW_ROW_LIMIT, max_rows=PERMITS_NOW_ROW_LIMIT,
                ) if include_rows else _no_rows(),
            )
        )
    except SocrataError as e:
        return await asyncio.to_thread(_permits_from_copy, coord, str(e))

    by_type: dict[str, int] = {}
    for g in now_groups:
        wt = str(g.get("work_type") or "")
        by_type[wt] = by_type.get(wt, 0) + _int(g.get("n"))
    for r in bis_near:
        by_type[r["_label"]] = by_type.get(r["_label"], 0) + 1
    now_total = _int((now_total_raw or [{}])[0].get("n"))
    bis_total = len(bis_near)
    total = now_total + bis_total

    rows: list[dict] = []
    seen: set[str] = set()
    for r in now_rows_raw:
        permit = str(r.get("work_permit") or "")
        lat, lng = _float(r.get("latitude")), _float(r.get("longitude"))
        if not permit or permit in seen or lat is None or lng is None:
            continue
        seen.add(permit)
        rows.append({
            "lat": lat, "lng": lng, "active": True, "system": "DOB NOW",
            "permit_type": r.get("work_type") or "Construction",
            "permit_status": "Permit Issued",
            "job_description": r.get("job_description") or "",
            "filing_date": r.get("issued_date") or "",
            "expiration_date": r.get("expired_date") or "",
            "address": " ".join(x for x in (r.get("house_no"), r.get("street_name")) if x),
            "source_id": f"NOW:{permit}",
        })
    for r in (bis_near[:PERMITS_BIS_ROW_LIMIT] if include_rows else []):
        rows.append({
            "lat": r["_lat"], "lng": r["_lng"], "active": True, "system": "DOB BIS",
            "permit_type": r["_label"],
            "permit_status": "ISSUED",
            "job_description": f"Job {r.get('job__')}" if r.get("job__") else "",
            "filing_date": r["_issued"].isoformat(),
            "expiration_date": r["_expires"].isoformat(),
            "address": " ".join(x for x in (r.get("house__"), r.get("street_name")) if x),
            "job_number": str(r.get("job__") or ""),
            "source_id": f"BIS:{r['permit_si_no']}",
        })
    rows.sort(key=lambda r: str(r.get("filing_date") or ""), reverse=True)
    as_of = max((d for d in (as_of_now, as_of_bis) if d), default=None)
    logger.info("Permits: %s active (%s DOB NOW, %s BIS), %s rows loaded.", total, now_total, bis_total, len(rows))
    return FeedResult(
        key=key, label=label, status="ok", total=total, rows=rows, breakdown=_permit_breakdown(by_type),
        top_types=_top(by_type), window_start=start, window_end=end, as_of=as_of,
        rows_sampled=len(rows) < total, dataset_ids=datasets, extra={"bis_total": bis_total},
    )


def _permits_from_copy(coord: Coordinate, reason: str) -> FeedResult:
    today = nyc_today()

    def build(raw: list[dict]):
        rows = []
        by_type: dict[str, int] = {}
        for r in raw:
            expires = socrata.parse_date(r.get("expiration_date"))
            if expires is not None and expires < today:
                continue
            t = str(r.get("permit_type") or "Construction")
            rows.append({**r, "active": True})
            by_type[t] = by_type.get(t, 0) + 1
        rows.sort(key=lambda r: str(r.get("filing_date") or ""), reverse=True)
        return rows, len(rows), _permit_breakdown(by_type), _top(by_type)

    return _from_copy(
        key="permits", table="building_permits",
        select="lat, lng, permit_type, permit_status, job_description, filing_date, expiration_date, source_id",
        date_col="filing_date", coord=coord, days=PERMIT_DAYS_BACK, expected_latest=today, max_staleness_days=4,
        window_end=today, build=build, reason=reason,
    )


# ── Evictions (executed by NYC Marshals) ──────────────────────────────────────

def eviction_source_id(row: dict) -> str:
    """court:docket:date — a case can be executed again on a later date (a separate row)."""
    executed = str(row.get("executed_date") or "")[:10]
    return f"{row.get('court_index_number') or ''}:{row.get('docket_number') or ''}:{executed}"


async def get_evictions_feed(coord: Coordinate, *, include_rows: bool = True) -> FeedResult:
    """Residential evictions carried out by NYC Marshals in the last 180 days."""
    key = "evictions"
    label, datasets = FEEDS[key]
    start, end = _window(EVICTION_DAYS_BACK, nyc_today())
    where = evictions_where(coord, start)
    try:
        as_of, (rows_raw, truncated) = await asyncio.gather(
            asyncio.to_thread(_display_latest, EVICTIONS_DATASET, "executed_date"),
            asyncio.to_thread(
                socrata.query_all, EVICTIONS_DATASET, where=where,
                select="court_index_number, docket_number, eviction_address, executed_date, latitude, longitude",
                order="executed_date DESC, court_index_number",
                page_size=EVICTIONS_ROW_LIMIT, max_rows=EVICTIONS_ROW_LIMIT,
            ) if include_rows else _no_rows(),
        )
        if truncated or not include_rows:
            total_raw = await asyncio.to_thread(
                socrata.query, EVICTIONS_DATASET, {"$select": "count(*) as n", "$where": where}
            )
            total = _int((total_raw or [{}])[0].get("n"))
        else:
            total = len(rows_raw)
    except SocrataError as e:
        return await asyncio.to_thread(_evictions_from_copy, coord, str(e))

    rows = []
    for r in rows_raw:
        lat, lng = _float(r.get("latitude")), _float(r.get("longitude"))
        if lat is None or lng is None:
            continue
        rows.append({
            "lat": lat, "lng": lng,
            "case_type": "Residential",
            "address": r.get("eviction_address") or "",
            "filing_date": r.get("executed_date") or "",
            "source_id": eviction_source_id(r),
        })
    logger.info("Evictions: %s residential (%s–%s).", total, start, end)
    return FeedResult(
        key=key, label=label, status="ok", total=total, rows=rows, window_start=start, window_end=end,
        as_of=as_of, rows_sampled=len(rows) < total, dataset_ids=datasets,
    )


def _evictions_from_copy(coord: Coordinate, reason: str) -> FeedResult:
    def build(raw: list[dict]):
        rows = [r for r in raw if str(r.get("case_type") or "").lower() == "residential"]
        rows.sort(key=lambda r: str(r.get("filing_date") or ""), reverse=True)
        return rows, len(rows), {}, []

    return _from_copy(
        key="evictions", table="eviction_records",
        select="lat, lng, case_type, filing_date, source_id", date_col="filing_date", coord=coord,
        days=EVICTION_DAYS_BACK, expected_latest=nyc_today(), max_staleness_days=7, window_end=nyc_today(),
        build=build, reason=reason,
    )


# ── Geometry ──────────────────────────────────────────────────────────────────

def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def filter_rows_within_radius(
    coord: Coordinate,
    rows: list[dict],
    *,
    radius_meters: float | None = None,
) -> list[dict]:
    """Keep rows with valid lat/lng within radius_meters of coord."""
    limit_m = radius_meters if radius_meters is not None else get_scan_radius_meters()
    out: list[dict] = []
    for row in rows:
        try:
            lat = float(row.get("lat"))
            lng = float(row.get("lng"))
        except (TypeError, ValueError):
            continue
        if not lat or not lng:
            continue
        if _haversine_meters(coord.lat, coord.lng, lat, lng) <= limit_m:
            out.append(row)
    return out


# ── Map Builders ──────────────────────────────────────────────────────────────

def _fmt_day(raw: object) -> str:
    d = socrata.parse_date(raw)
    return f"{d:%b} {d.day}, {d.year}" if d else ""


def _detail(kind: str, raw_date: object) -> str:
    day = _fmt_day(raw_date)
    return f"{kind} · {day}" if day else kind


def build_zones(crime: list[dict], reports_311: list[dict], permits: list[dict]) -> list[Zone]:
    """Converts raw data rows into map zone circles."""
    zones: list[Zone] = []

    for row in crime[:6]:
        if row.get("lat") and row.get("lng"):
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=250, color="#ef4444",
                label=row.get("crime_type", "Crime Report"),
                detail=_detail("NYPD complaint", row.get("occurred_at")),
            ))

    for row in reports_311[:4]:
        if row.get("lat") and row.get("lng"):
            ctype = row.get("complaint_type", "").lower()
            color = "#a855f7" if "rodent" in ctype else "#3b82f6"
            zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=200, color=color,
                label=_format_311_label(row),
                detail=_detail("311 request", row.get("created_at")),
            ))

    for row in permits[:3]:
        if not row.get("lat") or not row.get("lng"):
            continue
        if not is_active_permit(row):
            continue
        zones.append(Zone(
                lat=row["lat"], lng=row["lng"],
                radius_meters=180, color="#f97316",
                label=f"Permit: {row.get('permit_type', 'Construction')}",
                detail=_detail("DOB permit issued", row.get("filing_date")),
            ))

    return zones


def _clean_311_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _format_water_311_label(complaint_type: str, descriptor: str) -> str:
    c = complaint_type.lower()
    d = descriptor.lower()
    blob = f"{c} {d}"

    if "sewer" in blob:
        if any(k in blob for k in ["odor", "smell", "stench"]):
            issue = "Sewer Odor"
        elif any(k in blob for k in ["backup", "back up", "back-up", "overflow"]):
            issue = "Sewer Backup"
        elif any(k in blob for k in ["clog", "block", "catch basin", "drain"]):
            issue = "Drain Blockage"
        else:
            issue = "Sewer Issue"
    elif any(k in blob for k in ["contamin", "dirty", "brown", "discolor", "quality"]):
        issue = "Water Quality Issue"
    elif any(k in blob for k in ["leak", "flood"]):
        issue = "Water Leak"
    elif any(k in blob for k in ["no water", "pressure", "hydrant"]):
        issue = "Water Pressure"
    else:
        issue = "Water Issue"

    return issue


def _format_311_label(row: dict) -> str:
    complaint_type = _clean_311_text(row.get("complaint_type")) or "311 Report"
    descriptor = _clean_311_text(row.get("descriptor"))
    c = complaint_type.lower()

    if any(k in c for k in ["water", "leak", "flood", "sewer", "drain"]):
        return _format_water_311_label(complaint_type, descriptor)

    return f"311: {complaint_type}"


# Whole words only: as a substring "rat" also matches "Special Operations" and "Literature Request".
_RODENT_TYPE_RE = re.compile(r"\b(rodents?|rats?|mice|mouse|pests?)\b")


def _classify_311(row: dict) -> tuple[str, str]:
    """Returns (pin_type, label) for a 311 complaint type. 311 is never shown as an NYPD crime pin."""
    complaint_type = _clean_311_text(row.get("complaint_type"))
    c = complaint_type.lower()
    if _RODENT_TYPE_RE.search(c):
        return "rat", f"311: {complaint_type}"
    if any(k in c for k in ["noise", "loud", "music", "party"]):
        return "noise", f"311: {complaint_type}"
    if any(k in c for k in ["heat", "hot water", "heating", "boiler"]):
        return "fire", f"311: {complaint_type}"
    if any(k in c for k in ["water", "leak", "flood", "sewer", "drain"]):
        return "water", _format_311_label(row)
    if any(k in c for k in ["garbage", "sanitation", "litter", "trash", "waste", "dirty"]):
        return "trash", f"311: {complaint_type}"
    # Not "paint": HPD's PAINT/PLASTER complaints are about apartment upkeep, not graffiti.
    if any(k in c for k in ["graffiti", "vandal"]):
        return "graffiti", f"311: {complaint_type}"
    if any(k in c for k in _311_CONSTRUCTION_KEYS):
        return "construction", f"311: {complaint_type}"
    if any(k in c for k in ["parking", "vehicle", "traffic", "truck"]):
        return "truck", f"311: {complaint_type}"
    return "report", f"311: {complaint_type}"


# Lower = higher priority when multiple record types share one geocode.
_PIN_TYPE_RANK: dict[str, int] = {
    "police": 0,
    "fire": 1,
    "construction": 2,
    "permit": 3,
    "water": 4,
    "rat": 5,
    "noise": 6,
    "trash": 7,
    "graffiti": 8,
    "truck": 9,
    "bus": 10,
    "report": 11,
}


def is_active_permit(row: dict) -> bool:
    """True for DOB permit rows we treat as currently active."""
    if row.get("active") is True:
        return True
    return (row.get("permit_status", "") or "").lower() in ("issued", "active", "renewed", "permit issued")


def get_map_swarm_max_pins() -> int:
    """Max map pins to render (all are real; scoring still uses full in-radius counts)."""
    try:
        return max(20, min(200, int(os.getenv("MAP_SWARM_MAX_PINS", "100"))))
    except ValueError:
        return 100


def _swarm_pin_shuffle_key(pin: SwarmPin, center: Coordinate) -> str:
    """Stable per-property ordering (rescans show the same subset)."""
    payload = (
        f"{center.lat:.5f}|{center.lng:.5f}|"
        f"{pin.lat:.5f}|{pin.lng:.5f}|{pin.type}|{pin.label[:48]}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _sample_swarm_pins(
    pins: list[SwarmPin],
    center: Coordinate,
    limit: int,
) -> list[SwarmPin]:
    """
    Pick a subset of real pins for map readability.

    Uses a deterministic shuffle (not a spatial grid) so displayed pins keep
    natural NYC clustering — coordinates are never modified.
    """
    if len(pins) <= limit:
        return pins
    shuffled = sorted(pins, key=lambda p: _swarm_pin_shuffle_key(p, center))
    return shuffled[:limit]


def build_swarm(
    crime: list[dict],
    reports_311: list[dict],
    permits: list[dict],
    center: Coordinate,
) -> tuple[list[SwarmPin], int]:
    """
    Build map pins from real municipal rows (already Haversine-filtered).
    Returns (pins to render, total unique locations among the loaded rows).
    """
    grouped: dict[tuple[float, float], list[tuple[str, str, float, float, str]]] = {}

    def _add(lat: float, lng: float, pin_type: str, label: str, detail: str) -> None:
        key = (round(lat, 5), round(lng, 5))
        grouped.setdefault(key, []).append((pin_type, label, lat, lng, detail))

    for row in crime:
        if not row.get("lat") or not row.get("lng"):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        _add(lat, lng, "police", f"NYPD: {row.get('crime_type', 'Police Activity')}",
             _detail("NYPD complaint", row.get("occurred_at")))

    for row in reports_311:
        if not row.get("lat") or not row.get("lng"):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        pin_type, label = _classify_311(row)
        _add(lat, lng, pin_type, label, _detail("311 request", row.get("created_at")))

    for row in permits:
        if not row.get("lat") or not row.get("lng"):
            continue
        if not is_active_permit(row):
            continue
        try:
            lat, lng = float(row["lat"]), float(row["lng"])
        except (TypeError, ValueError):
            continue
        _add(lat, lng, "permit", f"Permit: {row.get('permit_type', 'Construction')}",
             _detail("DOB permit issued", row.get("filing_date")))

    swarm: list[SwarmPin] = []
    for entries in grouped.values():
        pin_type, label, lat, lng, detail = min(
            entries,
            key=lambda e: (_PIN_TYPE_RANK.get(e[0], 99), e[1]),
        )
        count = len(entries)
        if count > 1:
            label = f"{label} ({count} records at this location)"
        swarm.append(SwarmPin(lat=lat, lng=lng, type=pin_type, label=label, detail=detail))

    total = len(swarm)
    max_pins = get_map_swarm_max_pins()
    if total > max_pins:
        swarm = _sample_swarm_pins(swarm, center, max_pins)
    return swarm, total
