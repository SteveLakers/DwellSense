"""
NYC Open Data (Socrata SODA) client shared by /scan and the nightly import.

Errors are raised as SocrataError instead of returning [] so callers can tell
"zero records" apart from "the source did not answer" and label it unavailable.
"""

from __future__ import annotations

import contextvars
import logging
import math
import os
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

from models.schemas import Coordinate

logger = logging.getLogger(__name__)

SOCRATA_BASE = "https://data.cityofnewyork.us/resource"
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_METERS_PER_DEGREE = 111_194.9  # mean Earth radius 6371 km
NYC_TZ = ZoneInfo("America/New_York")

# SocrataError messages get logged, and request URLs and query echoes carry the scan's
# coordinates (written with 6 decimals by within_circle / numeric_circle).
_COORDINATE = re.compile(r"-?\d+\.\d{4,}")


def _redact(text: str) -> str:
    return _COORDINATE.sub("[redacted]", text)


class SocrataError(RuntimeError):
    """NYC Open Data returned an error or no usable payload after retries."""


def nyc_now() -> datetime:
    return datetime.now(NYC_TZ)


def nyc_today() -> date:
    return nyc_now().date()


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    token = (os.getenv("SOCRATA_APP_TOKEN") or "").strip()
    if token:
        headers["X-App-Token"] = token
    return headers


_deadline: contextvars.ContextVar[float | None] = contextvars.ContextVar("socrata_deadline", default=None)


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    """
    Requests made inside give up once `seconds` have passed (SocrataError). Tasks and
    asyncio.to_thread started inside inherit the limit; threads from threading.Thread do not.
    """
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def time_left() -> float | None:
    """Seconds left in the current time_limit(), or None outside one."""
    deadline = _deadline.get()
    return None if deadline is None else deadline - time.monotonic()


def _pause(seconds: float) -> None:
    left = time_left()
    time.sleep(seconds if left is None else max(0.0, min(seconds, left)))


def query(
    dataset_id: str,
    params: dict,
    *,
    timeout: float = 45.0,
    attempts: int = 3,
) -> list[dict]:
    """One SODA request with retries on throttling / transient server errors."""
    url = f"{SOCRATA_BASE}/{dataset_id}.json"
    last_error = "no response"
    for attempt in range(attempts):
        left = time_left()
        if left is not None and left <= 0:
            raise SocrataError(f"{dataset_id}: no answer within the time limit ({last_error})")
        try:
            resp = requests.get(
                url, params=params, headers=_headers(), timeout=timeout if left is None else min(timeout, left)
            )
        except requests.RequestException as e:
            last_error = _redact(f"{type(e).__name__}: {e}")
        else:
            if resp.ok:
                try:
                    data = resp.json()
                except ValueError:
                    last_error = "invalid JSON"
                else:
                    if isinstance(data, list):
                        return data
                    last_error = f"unexpected payload: {_redact(str(data))[:200]}"
            elif resp.status_code in _RETRY_STATUS:
                last_error = f"HTTP {resp.status_code}"
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit() and attempt < attempts - 1:
                    _pause(min(10.0, float(retry_after)))
                    continue
            else:
                raise SocrataError(f"{dataset_id}: HTTP {resp.status_code} {_redact(resp.text)[:200]}")
        if attempt < attempts - 1:
            _pause(1.5 * (attempt + 1))
    raise SocrataError(f"{dataset_id}: {last_error}")


def query_all(
    dataset_id: str,
    *,
    where: str,
    select: str | None = None,
    order: str = ":id",
    page_size: int = 5000,
    max_rows: int = 50_000,
    timeout: float = 60.0,
) -> tuple[list[dict], bool]:
    """
    Page through a filtered query. Returns (rows, truncated) where truncated means
    max_rows was reached and more rows may exist.
    """
    out: list[dict] = []
    offset = 0
    while len(out) < max_rows:
        limit = min(page_size, max_rows - len(out))
        params: dict = {"$where": where, "$order": order, "$limit": limit, "$offset": offset}
        if select:
            params["$select"] = select
        batch = query(dataset_id, params, timeout=timeout)
        out.extend(batch)
        if len(batch) < limit:
            return out, False
        offset += limit
    return out, True


def soql_ts(value: date | datetime) -> str:
    """Floating timestamp literal (NYC Open Data date columns carry no timezone)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{value.isoformat()}T00:00:00"


def soql_day_end(value: date) -> str:
    return f"{value.isoformat()}T23:59:59"


def parse_date(raw: object) -> date | None:
    """Parse SODA date strings ('2026-06-30T00:00:00.000' or 'MM/DD/YYYY')."""
    if not raw:
        return None
    s = str(raw).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")[:19]).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%m/%d/%Y").date()
    except ValueError:
        return None


def within_circle(location_col: str, coord: Coordinate, radius_miles: float) -> str:
    meters = radius_miles * 1609.344
    return f"within_circle({location_col}, {coord.lat:.6f}, {coord.lng:.6f}, {meters:.1f})"


def numeric_circle(lat_expr: str, lng_expr: str, coord: Coordinate, radius_miles: float) -> str:
    """
    True-circle filter for datasets that only have numeric (or castable text)
    latitude/longitude columns. Bounding box first so the server can prune rows.
    """
    meters = radius_miles * 1609.344
    cos_lat = max(0.2, math.cos(math.radians(coord.lat)))
    dlat = meters / _METERS_PER_DEGREE
    dlng = meters / (_METERS_PER_DEGREE * cos_lat)
    k_lat = (_METERS_PER_DEGREE / meters) ** 2
    k_lng = (_METERS_PER_DEGREE * cos_lat / meters) ** 2
    return (
        f"{lat_expr} between {coord.lat - dlat:.6f} and {coord.lat + dlat:.6f} "
        f"and {lng_expr} between {coord.lng - dlng:.6f} and {coord.lng + dlng:.6f} "
        f"and (({lat_expr} - {coord.lat:.6f}) * ({lat_expr} - {coord.lat:.6f}) * {k_lat:.6f} "
        f"+ ({lng_expr} - ({coord.lng:.6f})) * ({lng_expr} - ({coord.lng:.6f})) * {k_lng:.6f}) <= 1"
    )


_latest_cache: dict[tuple[str, str, str], tuple[float, date | None]] = {}
_latest_lock = threading.Lock()


def cached_latest_date(dataset_id: str, column: str, *, where: str = "") -> date | None:
    """Last successful latest_date() result, without a network call."""
    with _latest_lock:
        hit = _latest_cache.get((dataset_id, column, where))
    return hit[1] if hit else None


def latest_date(
    dataset_id: str,
    column: str,
    *,
    where: str = "",
    ttl_seconds: float = 3600.0,
) -> date:
    """
    Newest record date in a dataset (cached). Future-dated typos are excluded.
    Falls back to the last good cached value when the source is briefly down.
    """
    key = (dataset_id, column, where)
    now = time.monotonic()
    with _latest_lock:
        hit = _latest_cache.get(key)
    if hit and now - hit[0] < ttl_seconds and hit[1] is not None:
        return hit[1]

    clauses = [f"{column} <= '{soql_day_end(nyc_today())}'"]
    if where:
        clauses.append(f"({where})")
    try:
        rows = query(
            dataset_id,
            {"$select": f"max({column}) as latest", "$where": " AND ".join(clauses)},
            timeout=60.0,
        )
        latest = parse_date(rows[0].get("latest")) if rows else None
    except SocrataError:
        if hit and hit[1] is not None:
            logger.warning("Using cached latest date for %s.%s after a failed refresh.", dataset_id, column)
            return hit[1]
        raise
    if latest is None:
        raise SocrataError(f"{dataset_id}: no {column} values")
    with _latest_lock:
        _latest_cache[key] = (now, latest)
    return latest
