"""
Nightly copy of NYC Open Data into Supabase — the /scan fallback when NYC Open Data is down.

Each run rewrites every dataset's full scan window (the same windows city_data reads),
oldest records first and one page at a time, then deletes records that left the window
in one-day chunks. The scan only uses the copy when COPY_FALLBACK_ENABLED=true, which
should be set after a run has logged "complete" for every dataset.

Run manually (from backend/):
  python -m jobs.daily_refresh                    # all datasets
  python -m jobs.daily_refresh --dry-run          # fetch and count only; no Supabase writes
  python -m jobs.daily_refresh --only 311 evictions
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from services import city_data, socrata  # noqa: E402  (needs .env loaded first)
from services.socrata import SocrataError, nyc_today, soql_day_end, soql_ts  # noqa: E402

logger = logging.getLogger("daily_refresh")

SOCRATA_PAGE = 5000
UPSERT_BATCH = 1000
_RETRY_STATUS = frozenset({408, 429, 500, 502, 503, 504})


# ── Supabase REST ─────────────────────────────────────────────────────────────

def _supabase() -> tuple[str, dict[str, str]]:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
    return url, {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _request(method: str, path: str, *, params=None, json=None, prefer: str = "", timeout: float = 60.0):
    url, headers = _supabase()
    if prefer:
        headers = {**headers, "Prefer": prefer}
    for attempt in range(4):
        try:
            resp = requests.request(method, f"{url}/rest/v1/{path}", params=params, json=json,
                                    headers=headers, timeout=timeout)
        except requests.RequestException as e:
            if attempt == 3:
                raise
            logger.warning("Supabase %s %s failed (%s); retrying", method, path, e)
        else:
            if resp.ok:
                return resp
            if resp.status_code not in _RETRY_STATUS or attempt == 3:
                raise RuntimeError(f"Supabase {method} {path}: HTTP {resp.status_code} {resp.text[:300]}")
            logger.warning("Supabase %s %s: HTTP %s; retrying", method, path, resp.status_code)
        time.sleep(2 ** attempt)
    raise RuntimeError("unreachable")


def _upsert(table: str, records: list[dict]) -> None:
    for i in range(0, len(records), UPSERT_BATCH):
        _request("POST", table, params={"on_conflict": "source_id"}, json=records[i:i + UPSERT_BATCH],
                 prefer="resolution=merge-duplicates,return=minimal")


def _oldest(table: str, column: str) -> date | None:
    resp = _request("GET", table, params={"select": column, "order": f"{column}.asc.nullslast", "limit": "1"})
    rows = resp.json()
    return socrata.parse_date(rows[0].get(column)) if rows else None


def _count(table: str, filters: list[tuple[str, str]]) -> int:
    resp = _request("HEAD", table, params=[("select", "id"), *filters], prefer="count=exact")
    total = (resp.headers.get("content-range") or "*/0").rsplit("/", 1)[-1]
    return int(total) if total.isdigit() else 0


def _delete_before(table: str, column: str, cutoff: date, *, dry_run: bool) -> int:
    """Delete rows with column < cutoff, one day per request (no index on the date columns)."""
    oldest = _oldest(table, column)
    if oldest is None or oldest >= cutoff:
        return 0
    if dry_run:
        return _count(table, [(column, f"lt.{cutoff.isoformat()}")])
    removed, day = 0, oldest
    while day < cutoff:
        nxt = day + timedelta(days=1)
        params = [(column, f"gte.{day.isoformat()}"), (column, f"lt.{nxt.isoformat()}")]
        _request("DELETE", table, params=params, prefer="return=minimal", timeout=120.0)
        removed += 1
        day = nxt
    return removed


# ── Socrata ───────────────────────────────────────────────────────────────────

def _pages(dataset_id: str, *, where: str, select: str, order: str) -> Iterator[list[dict]]:
    """Stable, ascending pages (a stopped run leaves the copy complete up to its last page)."""
    offset = 0
    while True:
        page = socrata.query(
            dataset_id,
            {"$select": select, "$where": where, "$order": order, "$limit": SOCRATA_PAGE, "$offset": offset},
            timeout=90.0, attempts=4,
        )
        if page:
            yield page
        if len(page) < SOCRATA_PAGE:
            return
        offset += SOCRATA_PAGE


def _coords(lat: object, lng: object) -> tuple[float, float] | None:
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    return (la, ln) if la and ln else None


def _iso_day(raw: object) -> str | None:
    d = socrata.parse_date(raw)
    return d.isoformat() if d else None


# ── Datasets ──────────────────────────────────────────────────────────────────

@dataclass
class Source:
    dataset_id: str
    where: str
    select: str
    order: str
    to_record: Callable[[dict], dict | None]


@dataclass
class Job:
    key: str
    table: str
    date_col: str
    window: tuple[date, date]
    sources: list[Source]
    # Set when one record can span several source rows (a DOB NOW permit has a row per work
    # type): records are collected across all pages and the higher-priority row wins.
    priority: Callable[[dict], int] | None = None
    delete_expired: bool = False


def _crime_record(r: dict) -> dict | None:
    xy = _coords(r.get("latitude"), r.get("longitude"))
    if not xy or not r.get("cmplnt_num"):
        return None
    return {
        "lat": xy[0], "lng": xy[1], "crime_type": r.get("ofns_desc") or "Unknown",
        "description": r.get("pd_desc") or "", "occurred_at": r.get("cmplnt_fr_dt"),
        "borough": r.get("boro_nm") or "", "source_id": str(r["cmplnt_num"]),
    }


def _311_record(r: dict) -> dict | None:
    xy = _coords(r.get("latitude"), r.get("longitude"))
    if not xy or not r.get("unique_key"):
        return None
    return {
        "lat": xy[0], "lng": xy[1], "complaint_type": r.get("complaint_type") or "Unknown",
        "descriptor": r.get("descriptor") or "", "created_at": r.get("created_date"),
        "borough": r.get("borough") or "", "source_id": str(r["unique_key"]),
    }


def _now_record(r: dict) -> dict | None:
    xy = _coords(r.get("latitude"), r.get("longitude"))
    if not xy or not r.get("work_permit"):
        return None
    return {
        "lat": xy[0], "lng": xy[1], "permit_type": r.get("work_type") or "Construction",
        "permit_status": "Permit Issued", "job_description": r.get("job_description") or "",
        "filing_date": r.get("issued_date"), "expiration_date": r.get("expired_date"),
        "source_id": f"NOW:{r['work_permit']}",
    }


def _bis_record(r: dict) -> dict | None:
    xy = _coords(r.get("gis_latitude"), r.get("gis_longitude"))
    label = city_data._bis_label(r.get("permit_type", ""), r.get("permit_subtype", ""), r.get("job_type", ""))
    if not xy or not label or not r.get("permit_si_no"):
        return None
    return {
        "lat": xy[0], "lng": xy[1], "permit_type": label, "permit_status": r.get("permit_status") or "",
        "job_description": "", "filing_date": _iso_day(r.get("issuance_date")),
        "expiration_date": _iso_day(r.get("expiration_date")), "source_id": f"BIS:{r['permit_si_no']}",
    }


def _eviction_record(r: dict) -> dict | None:
    xy = _coords(r.get("latitude"), r.get("longitude"))
    if not xy or not (r.get("court_index_number") or r.get("docket_number")):
        return None
    return {
        "lat": xy[0], "lng": xy[1], "case_type": r.get("residential_commercial_ind") or "",
        "filing_date": r.get("executed_date"), "source_id": city_data.eviction_source_id(r),
    }


def _permit_priority(rec: dict) -> int:
    t = rec.get("permit_type")
    if t in city_data.DEMOLITION_WORK_TYPES:
        return 2
    return 1 if t in city_data.SCAFFOLD_WORK_TYPES else 0


def build_jobs(today: date) -> dict[str, Job]:
    crime_end = socrata.latest_date(city_data.CRIME_DATASET, "cmplnt_fr_dt", ttl_seconds=0)
    crime_start = crime_end - timedelta(days=city_data.CRIME_DAYS_BACK - 1)
    r311_start = today - timedelta(days=city_data.REPORTS_311_DAYS_BACK - 1)
    permit_start = today - timedelta(days=city_data.PERMIT_DAYS_BACK - 1)
    eviction_start = today - timedelta(days=city_data.EVICTION_DAYS_BACK - 1)
    work_types = ", ".join(f"'{t}'" for t in city_data.DISRUPTIVE_NOW_WORK_TYPES)
    return {
        "crime": Job("crime", "crime_reports", "occurred_at", (crime_start, crime_end), [Source(
            city_data.CRIME_DATASET,
            f"cmplnt_fr_dt between '{soql_ts(crime_start)}' and '{soql_day_end(crime_end)}' AND latitude IS NOT NULL",
            "cmplnt_num, cmplnt_fr_dt, ofns_desc, pd_desc, boro_nm, latitude, longitude",
            "cmplnt_fr_dt, cmplnt_num", _crime_record,
        )]),
        "311": Job("311", "reports_311", "created_at", (r311_start, today), [Source(
            city_data.REPORTS_311_DATASET,
            f"created_date >= '{soql_ts(r311_start)}' AND latitude IS NOT NULL",
            "unique_key, created_date, complaint_type, descriptor, borough, latitude, longitude",
            "created_date, unique_key", _311_record,
        )]),
        "permits": Job("permits", "building_permits", "filing_date", (permit_start, today), [
            Source(
                city_data.PERMITS_NOW_DATASET,
                f"issued_date >= '{soql_ts(permit_start)}' AND permit_status = 'Permit Issued' "
                f"AND expired_date >= '{soql_ts(today)}' AND work_type in ({work_types}) AND latitude IS NOT NULL",
                "work_permit, work_type, job_description, issued_date, expired_date, latitude, longitude",
                "issued_date, work_permit", _now_record,
            ),
            Source(
                city_data.PERMITS_BIS_DATASET,
                city_data.bis_citywide_where(permit_start, today),
                "permit_si_no, permit_type, permit_subtype, job_type, permit_status, issuance_date, "
                "expiration_date, gis_latitude, gis_longitude",
                "dobrundate, permit_si_no", _bis_record,
            ),
        ], priority=_permit_priority, delete_expired=True),
        "evictions": Job("evictions", "eviction_records", "filing_date", (eviction_start, today), [Source(
            city_data.EVICTIONS_DATASET,
            f"executed_date >= '{soql_ts(eviction_start)}' AND latitude IS NOT NULL",
            "court_index_number, docket_number, executed_date, residential_commercial_ind, latitude, longitude",
            "executed_date, court_index_number, docket_number", _eviction_record,
        )]),
    }


def run_job(job: Job, *, dry_run: bool) -> dict:
    start, end = job.window
    source_rows = skipped = written = 0
    pending: dict[str, dict] = {}

    def flush() -> None:
        nonlocal written
        if pending and not dry_run:
            _upsert(job.table, list(pending.values()))
        written += len(pending)
        pending.clear()

    for source in job.sources:
        for page in _pages(source.dataset_id, where=source.where, select=source.select, order=source.order):
            source_rows += len(page)
            for raw in page:
                rec = source.to_record(raw)
                if rec is None:
                    skipped += 1
                    continue
                prev = pending.get(rec["source_id"])
                if prev is None or (job.priority and job.priority(rec) > job.priority(prev)):
                    pending[rec["source_id"]] = rec
            if job.priority is None:
                flush()
    flush()

    removed = _delete_before(job.table, job.date_col, start, dry_run=dry_run)
    if not dry_run:
        _request("DELETE", job.table, params=[(job.date_col, "is.null")], prefer="return=minimal", timeout=120.0)
        if job.delete_expired:
            _request("DELETE", job.table, params=[("expiration_date", f"lt.{nyc_today().isoformat()}")],
                     prefer="return=minimal", timeout=120.0)
    return {
        "window": f"{start} to {end}", "source_rows": source_rows, "records": written,
        "skipped_no_location": skipped, ("rows_before_window" if dry_run else "days_deleted"): removed,
    }


def run_all(*, dry_run: bool = False, only: list[str] | None = None) -> dict[str, dict]:
    """Refresh every dataset; a failing dataset is logged and does not stop the others."""
    today = nyc_today()
    try:
        jobs = build_jobs(today)
    except SocrataError as e:
        logger.error("Daily refresh aborted: could not read the NYPD release date (%s)", e)
        return {}
    results: dict[str, dict] = {}
    for key, job in jobs.items():
        if only and key not in only:
            continue
        t0 = time.monotonic()
        try:
            results[key] = run_job(job, dry_run=dry_run)
            logger.info("Daily refresh %s %s: %s (%.0fs)", key, "dry run" if dry_run else "complete",
                        results[key], time.monotonic() - t0)
        except Exception as e:
            results[key] = {"error": str(e)[:300]}
            logger.exception("Daily refresh %s FAILED after %.0fs", key, time.monotonic() - t0)
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="fetch and count only; no Supabase writes")
    parser.add_argument("--only", nargs="+", choices=["crime", "311", "permits", "evictions"])
    args = parser.parse_args()
    run_all(dry_run=args.dry_run, only=args.only)
