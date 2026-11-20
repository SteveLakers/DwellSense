from __future__ import annotations

import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from models.schemas import Coordinate, FlightExposure
from services import nyc_baselines
from services.city_data import _get_client, get_scan_radius_miles, thread_client

logger = logging.getLogger(__name__)

_NYC_TZ = ZoneInfo("America/New_York")
# Renter-facing "night" window for aircraft noise (local NYC time).
_NIGHT_HOUR_START = 22  # 10 PM
_NIGHT_HOUR_END = 7  # before 7 AM

# A new pass starts when the same aircraft is unseen in the circle for this long
# (ingest polls every ~10 s, so a helicopter circling for 20 minutes is one pass).
PASS_GAP_SECONDS = 600

_NIGHT_WEIGHT = 0.58
_DAY_WEIGHT = 0.42
_SHOW_COMBINED_MIN = 0.54
_SHOW_NIGHT_MIN = 0.60
_SHOW_DAY_MIN = 0.68
_HIGH_COMBINED_MIN = 0.72
_HIGH_NIGHT_MIN = 0.78
_MIN_PASSES_TO_SHOW = 20
_MIN_COVERAGE_SHARE = 0.8

_SLICE_HOURS = 6
_PAGE_ROWS = 1000  # Supabase PostgREST max rows per request
_MAX_SLICE_ROWS = 60_000
_WINDOW_CACHE_SECONDS = 300
_SELECT = "id,observed_at,icao24,lat,lng,baro_alt_m,geo_alt_m,on_ground"

# Flight noise is paused. adsb.lol, the collector's source, began allowing 500 requests a day
# around Nov 16, 2026. At one poll every 10 s that covers about 83 minutes, so passes can no longer
# be counted and the NYC flight baselines (measured at full coverage) no longer apply. While this
# is True a scan reads no aircraft positions and the report has no flight section. Before setting
# it to False: restore full-rate collection, re-run scripts/calibrate_nyc_baselines.py with flight
# points, and set FLIGHT_NOISE_PAUSED in frontend/lib/site.ts to false in the same change.
FLIGHT_NOISE_PAUSED = True

# One scan's whole read of stored positions. A slower read is given up (flights are then
# shown as unavailable) so a slow database cannot hold up the rest of the report.
_WINDOW_BUDGET_SECONDS = 20.0
# After a failed or slow read, skip further reads for this long instead of repeating them
# (a scan asks for the same window three times).
_PAUSE_AFTER_FAILURE_SECONDS = 60.0

_paused_until = 0.0  # time.monotonic() until which reads are skipped


def pause_reads(seconds: float = _PAUSE_AFTER_FAILURE_SECONDS) -> None:
    global _paused_until
    _paused_until = time.monotonic() + seconds


def reads_paused() -> bool:
    return time.monotonic() < _paused_until


def _is_night(local_hour: int) -> bool:
    return local_hour >= _NIGHT_HOUR_START or local_hour < _NIGHT_HOUR_END


def _comparison_label(percentile: float) -> str:
    if percentile >= 0.85:
        return "among the highest we see in NYC"
    if percentile >= 0.70:
        return "higher than most NYC blocks"
    return "above typical NYC levels"


def _elevation_level(combined: float, night_p: float) -> str:
    if combined >= _HIGH_COMBINED_MIN or night_p >= _HIGH_NIGHT_MIN:
        return "high"
    if combined >= _SHOW_COMBINED_MIN or night_p >= _SHOW_NIGHT_MIN:
        return "elevated"
    return "typical"


def _should_show_flight_feature(
    *,
    data_quality: str,
    pass_count: int,
    combined_percentile: float,
    night_percentile: float,
    day_percentile: float,
) -> bool:
    if data_quality == "unavailable" or pass_count < _MIN_PASSES_TO_SHOW:
        return False
    return (
        combined_percentile >= _SHOW_COMBINED_MIN
        or night_percentile >= _SHOW_NIGHT_MIN
        or day_percentile >= _SHOW_DAY_MIN
    )


def _rate_word(rate: float) -> str:
    if rate < 0.2:
        return "rare"
    if rate < 0.7:
        return "occasional"
    if rate < 2:
        return "fairly common"
    return "frequent"


def _build_headline(
    *,
    night_per_hr: float,
    day_per_hr: float,
    night_percentile: float,
    day_percentile: float,
    observation_days: int,
) -> tuple[str, str]:
    if night_percentile >= _HIGH_NIGHT_MIN:
        headline = "Planes fly over often at night — more than at most NYC apartment locations."
    elif night_percentile >= _SHOW_NIGHT_MIN:
        headline = "More overnight flights than at most NYC apartment locations."
    elif day_percentile >= _SHOW_DAY_MIN:
        headline = "Busier daytime air traffic than at most NYC apartment locations."
    else:
        headline = "More flight activity here than typical for NYC."

    detail = (
        f"Overnight: {_rate_word(night_per_hr)}; daytime: {_rate_word(day_per_hr)} "
        f"(last {observation_days} days)."
    )
    return headline, detail


def _haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 3958.7613
    p = math.pi / 180
    dlat = (lat2 - lat1) * p
    dlng = (lng2 - lng1) * p
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin(dlng / 2) ** 2
    )
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def parse_ts(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def exposure_params(days: int | None = None, radius_miles: float | None = None) -> tuple[int, float]:
    try:
        days_val = max(1, min(30, int(os.getenv("EXPOSURE_DAYS", str(days or 7)))))
    except ValueError:
        days_val = 7
    default_radius = radius_miles if radius_miles is not None else get_scan_radius_miles()
    try:
        radius_val = max(0.25, min(10.0, float(os.getenv("EXPOSURE_RADIUS_MILES", str(default_radius)))))
    except ValueError:
        radius_val = get_scan_radius_miles()
    return days_val, radius_val


# ── Ingest coverage (which hours the NYC-wide ADS-B poller actually recorded) ──

_coverage: dict[datetime, bool] = {}
_coverage_lock = threading.Lock()


def _hour_has_samples(hour_start: datetime) -> bool:
    res = (
        thread_client()
        .table("adsb_samples")
        .select("id")
        .gte("observed_at", hour_start.isoformat())
        .lt("observed_at", (hour_start + timedelta(hours=1)).isoformat())
        .limit(1)
        .execute()
    )
    return bool(res.data)


def covered_hours(since: datetime, until: datetime) -> set[datetime]:
    """UTC hour starts in [since, until) with any NYC sample. Past hours are cached."""
    hours = []
    h = since
    while h < until:
        hours.append(h)
        h += timedelta(hours=1)
    recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    with _coverage_lock:
        todo = [h for h in hours if h not in _coverage or h >= recent_cutoff]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(_hour_has_samples, todo))
        with _coverage_lock:
            for h, ok in zip(todo, results):
                _coverage[h] = ok
            for stale in [k for k in _coverage if k < since - timedelta(days=31)]:
                _coverage.pop(stale, None)
    with _coverage_lock:
        return {h for h in hours if _coverage.get(h)}


# ── Window rows (every in-radius sample, paged) ───────────────────────────────

@dataclass
class AdsbWindow:
    rows: list[dict]
    since: datetime
    until: datetime
    days: int
    radius_miles: float
    covered: set[datetime] = field(default_factory=set)
    truncated: bool = False


_window_cache: dict[tuple, tuple[float, AdsbWindow]] = {}
_window_lock = threading.Lock()


def _fetch_slice(
    args: tuple[datetime, datetime, tuple[float, float, float, float], float, threading.Event],
) -> tuple[list[dict], bool]:
    """
    Keyset pages on the observed_at index. One poll writes many rows with the same
    timestamp, so each page restarts at the last timestamp and skips ids already read.
    Returns (rows, truncated). Raises TimeoutError once the read's time budget is spent
    or another slice has already failed.
    """
    start, end, (lat_min, lat_max, lng_min, lng_max), deadline, stop = args
    out: list[dict] = []
    seen: set[int] = set()
    cursor = start.isoformat()
    while True:
        if stop.is_set() or time.monotonic() > deadline:
            raise TimeoutError("ADS-B window read stopped: time budget spent or another slice failed")
        if len(out) >= _MAX_SLICE_ROWS:
            return out, True
        page = (
            thread_client()
            .table("adsb_samples")
            .select(_SELECT)
            .gte("observed_at", cursor)
            .lt("observed_at", end.isoformat())
            .gte("lat", lat_min)
            .lte("lat", lat_max)
            .gte("lng", lng_min)
            .lte("lng", lng_max)
            .order("observed_at")
            .limit(_PAGE_ROWS)
            .execute()
            .data
            or []
        )
        fresh = [r for r in page if int(r["id"]) not in seen]
        out.extend(fresh)
        seen.update(int(r["id"]) for r in fresh)
        if len(page) < _PAGE_ROWS:
            return out, False
        if not fresh:
            # More than one page of rows share a single timestamp; cannot advance.
            return out, True
        cursor = str(page[-1]["observed_at"])


def load_adsb_window(
    coord: Coordinate,
    *,
    days: int | None = None,
    radius_miles: float | None = None,
    max_alt_ft: int = 10000,
    limited: bool = True,
) -> AdsbWindow | None:
    """
    Every stored ADS-B sample within radius over the last `days` complete hours
    (airborne, at or below max_alt_ft). None when the store cannot be read, the read
    runs past its time budget, or reads are paused after a recent failure.

    limited=False is for the calibration script: no time budget and no pause, so a slow
    read of a busy location is waited for instead of dropped (dropping the busiest
    locations would skew the flight baselines low).
    """
    days_val, radius_val = exposure_params(days, radius_miles)
    until = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    since = until - timedelta(days=days_val)
    key = (round(coord.lat, 4), round(coord.lng, 4), days_val, round(radius_val, 3), max_alt_ft, until)
    now = time.monotonic()
    with _window_lock:
        hit = _window_cache.get(key)
        if hit and now - hit[0] < _WINDOW_CACHE_SECONDS:
            return hit[1]

    if limited and reads_paused():
        return None
    try:
        _get_client()
    except Exception:
        return None

    dlat = radius_val / 69.0
    dlng = radius_val / (69.0 * max(0.2, math.cos(math.radians(coord.lat))))
    bbox = (coord.lat - dlat, coord.lat + dlat, coord.lng - dlng, coord.lng + dlng)
    deadline = now + _WINDOW_BUDGET_SECONDS if limited else math.inf
    stop = threading.Event()
    slices = []
    s = since
    while s < until:
        e = min(until, s + timedelta(hours=_SLICE_HOURS))
        slices.append((s, e, bbox, deadline, stop))
        s = e
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            try:
                parts = list(pool.map(_fetch_slice, slices))
            except BaseException:
                stop.set()  # slices still queued return at once instead of running for nothing
                raise
        covered = covered_hours(since, until)
    except Exception:
        logger.exception("flight_exposure: ADS-B window query failed")
        if limited:
            pause_reads()
        return None

    rows: list[dict] = []
    for part, _ in parts:
        for r in part:
            if r.get("on_ground") is True:
                continue
            try:
                lat = float(r["lat"])
                lng = float(r["lng"])
            except (KeyError, TypeError, ValueError):
                continue
            if _haversine_miles(coord.lat, coord.lng, lat, lng) > radius_val:
                continue
            alt_m = r.get("geo_alt_m") if isinstance(r.get("geo_alt_m"), (int, float)) else r.get("baro_alt_m")
            alt_ft = int(round(float(alt_m) * 3.28084)) if isinstance(alt_m, (int, float)) else None
            if alt_ft is not None and alt_ft > max_alt_ft:
                continue
            r["_alt_ft"] = alt_ft
            rows.append(r)
    rows.sort(key=lambda r: str(r.get("observed_at") or ""))
    window = AdsbWindow(
        rows=rows,
        since=since,
        until=until,
        days=days_val,
        radius_miles=radius_val,
        covered=covered,
        truncated=any(truncated for _, truncated in parts),
    )
    with _window_lock:
        _window_cache[key] = (now, window)
        for k in [k for k, (t, _) in _window_cache.items() if now - t >= _WINDOW_CACHE_SECONDS]:
            _window_cache.pop(k, None)
    return window


def count_passes(rows: list[dict]) -> list[datetime]:
    """Start time of each distinct pass (per aircraft, split by gaps > PASS_GAP_SECONDS)."""
    by_icao: dict[str, list[datetime]] = {}
    for r in rows:
        icao = str(r.get("icao24") or "").strip().lower()
        t = parse_ts(r.get("observed_at"))
        if icao and t is not None:
            by_icao.setdefault(icao, []).append(t)
    starts: list[datetime] = []
    for times in by_icao.values():
        times.sort()
        starts.append(times[0])
        for prev, cur in zip(times, times[1:]):
            if (cur - prev).total_seconds() > PASS_GAP_SECONDS:
                starts.append(cur)
    return starts


@dataclass(frozen=True)
class PassRates:
    night_per_hr: float
    day_per_hr: float
    night_passes: int
    day_passes: int
    night_hours: int
    day_hours: int


def pass_rates(rows: list[dict], covered: set[datetime]) -> PassRates:
    night_hours = sum(1 for h in covered if _is_night(h.astimezone(_NYC_TZ).hour))
    day_hours = len(covered) - night_hours
    night = day = 0
    for start in count_passes(rows):
        if _is_night(start.astimezone(_NYC_TZ).hour):
            night += 1
        else:
            day += 1
    return PassRates(
        night_per_hr=night / night_hours if night_hours else 0.0,
        day_per_hr=day / day_hours if day_hours else 0.0,
        night_passes=night,
        day_passes=day,
        night_hours=night_hours,
        day_hours=day_hours,
    )


def fetch_raw_adsb_samples(
    coord: Coordinate,
    *,
    days: int | None = None,
    radius_miles: float | None = None,
    max_alt_ft: int = 10000,
) -> list[dict]:
    """In-radius ADS-B rows for the dossier PDF (fail-open: []). Nothing is read while flight noise is paused."""
    if FLIGHT_NOISE_PAUSED:
        return []
    window = load_adsb_window(coord, days=days, radius_miles=radius_miles, max_alt_ft=max_alt_ft)
    if window is None:
        return []
    return [
        {
            "observed_at": r.get("observed_at"),
            "icao24": r.get("icao24"),
            "lat": r.get("lat"),
            "lng": r.get("lng"),
            "baro_alt_m": r.get("baro_alt_m"),
            "geo_alt_m": r.get("geo_alt_m"),
            "on_ground": r.get("on_ground"),
        }
        for r in window.rows
    ]


def unavailable_exposure(days: int | None = None, radius_miles: float | None = None) -> FlightExposure:
    """The result when stored positions cannot be read: nothing measured, nothing shown."""
    days_val, radius_val = exposure_params(days, radius_miles)
    return FlightExposure(
        night_overflights_per_hour=0.0,
        day_overflights_per_hour=0.0,
        data_quality="unavailable",
        show_flight_feature=False,
        elevation_level="unavailable",
        observation_days=days_val,
        radius_miles=radius_val,
        sample_count=0,
    )


def compute_exposure(
    coord: Coordinate,
    *,
    days: int = 7,
    radius_miles: float | None = None,
    max_alt_ft: int = 10000,
) -> FlightExposure:
    """
    Address-relative aircraft exposure from stored ADS-B samples: distinct passes per
    covered night / day hour, compared with the same measurement at sampled NYC
    apartment locations. ``show_flight_feature`` is true only when clearly above typical.
    """
    days, radius_miles = exposure_params(days, radius_miles)
    unavailable = unavailable_exposure(days, radius_miles)
    if FLIGHT_NOISE_PAUSED:
        return unavailable

    window = load_adsb_window(coord, days=days, radius_miles=radius_miles, max_alt_ft=max_alt_ft)
    if window is None or not window.covered or window.truncated:
        return unavailable

    rates = pass_rates(window.rows, window.covered)
    expected_hours = days * 24
    quality = (
        "good"
        if len(window.covered) >= _MIN_COVERAGE_SHARE * expected_hours and rates.night_hours and rates.day_hours
        else "sparse"
    )
    alts = sorted(r["_alt_ft"] for r in window.rows if r.get("_alt_ft") is not None)
    typical_alt = alts[len(alts) // 2] if alts else None

    night_p = nyc_baselines.percentile("flight_night_passes_per_hr", rates.night_per_hr)
    day_p = nyc_baselines.percentile("flight_day_passes_per_hr", rates.day_per_hr)
    observed_days = max(1, round(len(window.covered) / 24))
    base = dict(
        night_overflights_per_hour=round(rates.night_per_hr, 2),
        day_overflights_per_hour=round(rates.day_per_hr, 2),
        typical_altitude_ft=typical_alt,
        data_quality=quality,
        observation_days=observed_days,
        radius_miles=radius_miles,
        sample_count=len(window.rows),
    )
    if night_p is None or day_p is None:
        logger.warning("flight_exposure: NYC flight baselines missing — comparison unavailable")
        return FlightExposure(**base, show_flight_feature=False, elevation_level="unavailable")

    combined_p = _NIGHT_WEIGHT * night_p + _DAY_WEIGHT * day_p
    show = _should_show_flight_feature(
        data_quality=quality,
        pass_count=rates.night_passes + rates.day_passes,
        combined_percentile=combined_p,
        night_percentile=night_p,
        day_percentile=day_p,
    )
    headline = detail = None
    if show:
        headline, detail = _build_headline(
            night_per_hr=rates.night_per_hr,
            day_per_hr=rates.day_per_hr,
            night_percentile=night_p,
            day_percentile=day_p,
            observation_days=observed_days,
        )
        if typical_alt is not None and typical_alt <= 3200:
            detail = (
                f"{detail} Many planes pass around {typical_alt:,} ft — "
                "low enough to hear from the street."
            )
    return FlightExposure(
        **base,
        show_flight_feature=show,
        elevation_level=_elevation_level(combined_p, night_p) if show else "typical",
        night_percentile=round(night_p, 3),
        day_percentile=round(day_p, 3),
        combined_percentile=round(combined_p, 3),
        headline=headline,
        detail=detail,
    )
