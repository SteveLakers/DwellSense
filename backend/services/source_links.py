"""Deep links to NYC Open Data and third-party sources used in PDF dossiers.

All links point at official external sources (never localhost) and open pages
pre-filtered to the scanned address, scan radius, or exact dossier record.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal
from urllib.parse import quote

from models.schemas import Coordinate
from services import city_data

_BASE = "https://data.cityofnewyork.us"

# "feed" is the scan feed whose date window the browse link reuses.
_DATASETS: dict[str, dict[str, str]] = {
    "crime": {
        "path": "Public-Safety/NYPD-Complaint-Data-Current-Year-To-Date-/5uac-w243",
        "feed": "crime",
        "id_field": "cmplnt_num",
        "order_field": "cmplnt_fr_dt",
        "label": "NYPD Complaint Data (NYC Open Data)",
        "select": "cmplnt_num,cmplnt_fr_dt,ofns_desc,pd_desc,law_cat_cd,boro_nm,latitude,longitude",
    },
    "police_calls": {
        "path": "Public-Safety/NYPD-Calls-for-Service-Year-to-Date-/n2zq-pubd",
        "feed": "police_calls",
        "id_field": "cad_evnt_id",
        "order_field": "incident_date",
        "label": "NYPD Calls for Service (NYC Open Data)",
        "select": "cad_evnt_id,incident_date,incident_time,typ_desc,cip_jobs,boro_nm,latitude,longitude",
    },
    "311": {
        "path": "Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9",
        "feed": "311",
        "id_field": "unique_key",
        "order_field": "created_date",
        "label": "311 Service Requests (NYC Open Data)",
        "select": "unique_key,created_date,complaint_type,descriptor,borough,incident_address,latitude,longitude",
    },
    "permits_now": {
        "path": "Housing-Development/DOB-NOW-Build-Approved-Permits/rbx6-tga4",
        "feed": "permits",
        "id_field": "work_permit",
        "id_prefix": "NOW:",
        "order_field": "issued_date",
        "label": "DOB NOW: Build Approved Permits (NYC Open Data)",
        "select": (
            "work_permit,issued_date,expired_date,work_type,permit_status,job_description,"
            "house_no,street_name,borough,latitude,longitude"
        ),
    },
    "permits": {
        "path": "Housing-Development/DOB-Permit-Issuance/ipu4-2q9a",
        "feed": "permits",
        "id_field": "permit_si_no",
        "id_prefix": "BIS:",
        "order_field": "dobrundate",
        "label": "DOB Permit Issuance (NYC Open Data)",
        "select": (
            "permit_si_no,job__,issuance_date,expiration_date,permit_type,permit_subtype,job_type,"
            "permit_status,house__,street_name,borough,gis_latitude,gis_longitude"
        ),
    },
    "evictions": {
        "path": "City-Government/Evictions/6z8x-wfk4",
        "feed": "evictions",
        "id_field": "docket_number",
        "order_field": "executed_date",
        "label": "Evictions (NYC Open Data)",
        "select": (
            "court_index_number,docket_number,eviction_address,executed_date,"
            "residential_commercial_ind,borough,latitude,longitude"
        ),
    },
}

_HPD_VIOLATIONS: dict[str, str] = {
    "path": "Housing-Development/Housing-Maintenance-Code-Violations/wvxf-dwi5",
    "select": (
        "violationid,housenumber,streetname,boro,class,novdescription,"
        "novissueddate,currentstatus,violationstatus,apartment"
    ),
    "order_field": "novissueddate",
}

# (dataset key, 311 subset) per card; subsets mirror city_data.is_311_noise / is_311_construction.
_CARD_DATASETS: dict[str, list[tuple[str, str | None]]] = {
    "high_churn": [("evictions", None)],
    "police_calls": [("police_calls", None)],
    "area_safety": [("crime", None)],
    "demolitions": [("permits_now", None), ("permits", None), ("311", "construction")],
    "noise_schedule": [("311", "noise")],
    "reports_311": [("311", None)],
}

CARD_DATASET_KEYS: dict[str, list[str]] = {
    card: [key for key, _ in specs] for card, specs in _CARD_DATASETS.items()
}

_STREET_SUFFIX_RE = re.compile(
    r"\b(STREET|ST|AVENUE|AVE|ROAD|RD|BOULEVARD|BLVD|PLACE|PL|DRIVE|DR|LANE|LN|COURT|CT|WAY|TERRACE|TER)\b",
    re.IGNORECASE,
)

_HOUSE_STREET_RE = re.compile(r"^(\d+[A-Z]?)\s+(.+)$", re.IGNORECASE)
_ICAO_FROM_LABEL_RE = re.compile(r"\(([a-f0-9]{6})\b", re.IGNORECASE)

_RECORD_LIMIT = 10
# Rows an NYC Open Data explore link lists (newest first). The PDF states this next to each link.
BROWSE_LIMIT = 200
_BROWSE_LIMIT = BROWSE_LIMIT
_MAX_ID_CLAUSES = 50

LinkScope = Literal["scan", "records"]


def _soql_escape(value: str) -> str:
    return (value or "").replace("'", "''")


def _explore_url(dataset_key: str, soql: str) -> str:
    path = _DATASETS[dataset_key]["path"]
    return f"{_BASE}/{path}/explore/query/{quote(soql, safe='')}"


def _hpd_explore_url(soql: str) -> str:
    path = _HPD_VIOLATIONS["path"]
    return f"{_BASE}/{path}/explore/query/{quote(soql, safe='')}"


def _select_soql(dataset_key: str, *, where: str, limit: int) -> str:
    meta = _DATASETS[dataset_key]
    return f"SELECT {meta['select']} WHERE {where} ORDER BY {meta['order_field']} DESC LIMIT {limit}"


def parse_address_parts(formatted_address: str) -> dict[str, str | None]:
    """House number, street token, and borough parsed from a geocoded NYC address."""
    if not formatted_address:
        return {"housenumber": None, "street_token": None, "street_line": None, "borough": None}
    first = formatted_address.split(",")[0].strip()
    match = _HOUSE_STREET_RE.match(first)
    housenumber = match.group(1).upper() if match else None
    street_line = (match.group(2) if match else first).strip()
    street_token = street_token_from_address(formatted_address)
    return {
        "housenumber": housenumber,
        "street_token": street_token,
        "street_line": street_line,
        "borough": borough_from_address(formatted_address),
    }


def street_token_from_address(formatted_address: str) -> str | None:
    """Core street name token for LIKE filters (e.g. LEFFERTS from 742 Lefferts Ave)."""
    if not formatted_address:
        return None
    first = formatted_address.split(",")[0].strip().upper()
    without_number = re.sub(r"^\d+[A-Z]?\s*", "", first).strip()
    without_suffix = _STREET_SUFFIX_RE.sub("", without_number).strip()
    parts = [p for p in without_suffix.split() if p]
    if not parts:
        return None
    # "W 42ND" / "EAST 14" — prefer the street name over a compass prefix.
    if len(parts) >= 2 and parts[0] in {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}:
        token = parts[1]
    else:
        token = parts[0]
    # HPD/Open Data store numbered streets as "WEST 42 STREET", not "42ND".
    token = re.sub(r"^(\d+)(ST|ND|RD|TH)$", r"\1", token)
    token = token.strip(" .")
    return token if len(token) >= 2 else None


def borough_from_address(formatted_address: str) -> str | None:
    """Best-effort NYC borough label for SODA filters."""
    upper = (formatted_address or "").upper()
    if "STATEN ISLAND" in upper or re.search(r",\s*STATEN\b", upper):
        return "STATEN ISLAND"
    if "BROOKLYN" in upper:
        return "BROOKLYN"
    if "QUEENS" in upper:
        return "QUEENS"
    if "BRONX" in upper:
        return "BRONX"
    if re.search(r"\bMANHATTAN\b", upper):
        return "MANHATTAN"
    if re.search(r",\s*NEW YORK(?:,|\s+\d)", upper):
        return "MANHATTAN"
    return None


def _scan_where(
    dataset_key: str,
    coord: Coordinate,
    *,
    radius_miles: float,
    start: date,
    end: date,
    subset: str | None,
) -> str | None:
    """SoQL WHERE identical to the scan's count for this dataset.

    None for BIS permits and evictions: their coordinates are text, and the
    casts the radius filter needs are not reliable on explore pages.
    """
    if dataset_key == "crime":
        return city_data.crime_where(coord, start, end, radius_miles=radius_miles)
    if dataset_key == "police_calls":
        return city_data.police_calls_where(coord, start, end, radius_miles=radius_miles)
    if dataset_key == "311":
        where = city_data.reports_311_where(coord, start, radius_miles=radius_miles, exclude_parking=True)
        if subset == "noise":
            where += f" AND {city_data.soql_311_noise()}"
        elif subset == "construction":
            where += f" AND {city_data.soql_311_construction()}"
        return where
    if dataset_key == "permits_now":
        return city_data.permits_now_where(coord, start, end, radius_miles=radius_miles)
    return None


def record_dataset_key(default_key: str, source_id: str) -> str:
    """DOB permit rows carry a NOW:/BIS: prefix that picks the dataset."""
    sid = (source_id or "").strip()
    if default_key in ("permits", "permits_now"):
        return "permits_now" if sid.startswith("NOW:") else "permits"
    return default_key


def _id_clause(dataset_key: str, source_id: str) -> str | None:
    raw = (source_id or "").strip()
    meta = _DATASETS[dataset_key]
    prefix = meta.get("id_prefix")
    if prefix and raw.startswith(prefix):
        raw = raw[len(prefix):]
    if not raw:
        return None
    # Every id field used here is text; unquoted values cause type-mismatch 400s and blank explore pages.
    if dataset_key == "evictions" and ":" in raw:
        court, docket, executed = (raw.split(":", 2) + ["", ""])[:3]
        parts = [f"{f}='{_soql_escape(v)}'" for f, v in (("court_index_number", court), ("docket_number", docket)) if v]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", executed):
            parts.append(f"executed_date='{executed}T00:00:00'")
        return "(" + " AND ".join(parts) + ")" if parts else None
    return f"{meta['id_field']}='{_soql_escape(raw)}'"


def dataset_label(dataset_key: str) -> str:
    return _DATASETS[dataset_key]["label"]


def record_url(dataset_key: str, source_id: str) -> str | None:
    """NYC Open Data explorer filtered to one dossier record."""
    dataset_key = record_dataset_key(dataset_key, source_id)
    clause = _id_clause(dataset_key, source_id)
    if not clause:
        return None
    return _explore_url(dataset_key, _select_soql(dataset_key, where=clause, limit=_RECORD_LIMIT))


def dossier_records_url(dataset_key: str, source_ids: list[str]) -> str | None:
    """NYC Open Data explorer filtered to exact dossier record IDs."""
    clauses: list[str] = []
    for sid in dict.fromkeys(s.strip() for s in source_ids if s and s.strip()):
        clause = _id_clause(dataset_key, sid)
        if clause:
            clauses.append(clause)
        if len(clauses) >= _MAX_ID_CLAUSES:
            break
    if not clauses:
        return None
    where = clauses[0] if len(clauses) == 1 else "(" + ") OR (".join(clauses) + ")"
    return _explore_url(dataset_key, _select_soql(dataset_key, where=where, limit=min(_BROWSE_LIMIT, len(clauses))))


def card_dataset_urls(
    card_id: str,
    coord: Coordinate,
    *,
    radius_miles: float,
    windows: dict[str, tuple[date, date]],
    dossier_ids: dict[str, list[str]] | None = None,
) -> list[tuple[str, str, str, LinkScope]]:
    """(label, url, dataset key, scope) for each dataset behind a card.

    scope "scan": the link applies the scan's own filter (same records as the count).
    scope "records": the link lists the exact records shown in the report.
    `windows` maps feed keys to the scan's (start, end) dates; datasets whose feed
    was unavailable during the scan get no link.
    """
    out: list[tuple[str, str, str, LinkScope]] = []
    for key, subset in _CARD_DATASETS.get(card_id, []):
        window = windows.get(_DATASETS[key]["feed"])
        if not window:
            continue
        where = _scan_where(key, coord, radius_miles=radius_miles, start=window[0], end=window[1], subset=subset)
        if where:
            url = _explore_url(key, _select_soql(key, where=where, limit=_BROWSE_LIMIT))
            out.append((dataset_label(key), url, key, "scan"))
            continue
        records = dossier_records_url(key, (dossier_ids or {}).get(key, []))
        if records:
            out.append((dataset_label(key), records, key, "records"))
    return out


def adsb_aircraft_url(icao24: str) -> str | None:
    """adsb.lol map focused on one aircraft (the ADS-B source ZerMap collects from)."""
    icao = (icao24 or "").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{6}", icao):
        return None
    return f"https://adsb.lol/?icao={icao}"


def adsb_area_url(coord: Coordinate) -> str:
    """adsb.lol live map centered on the scanned address."""
    return f"https://adsb.lol/?lat={coord.lat:.5f}&lon={coord.lng:.5f}&zoom=13"


def adsb_aircraft_from_label(label: str) -> str | None:
    match = _ICAO_FROM_LABEL_RE.search(label or "")
    return adsb_aircraft_url(match.group(1)) if match else None


def hpd_violations_url(formatted_address: str = "") -> str | None:
    """
    HPD housing violations on NYC Open Data filtered to the subject building. None without a
    house number and street (a place like "Union Square" is not one building).
    """
    parts = parse_address_parts(formatted_address)
    token = parts.get("street_token")
    if not parts.get("housenumber") or not token:
        return None
    clauses = [
        f"housenumber='{_soql_escape(str(parts['housenumber']))}'",
        f"upper(streetname) like '%{_soql_escape(str(token).upper())}%'",
    ]
    borough = parts.get("borough")
    if borough:
        clauses.append(f"upper(boro)='{_soql_escape(str(borough).upper())}'")
    where = " AND ".join(clauses)
    soql = (
        f"SELECT {_HPD_VIOLATIONS['select']} WHERE {where} "
        f"ORDER BY {_HPD_VIOLATIONS['order_field']} DESC LIMIT {_BROWSE_LIMIT}"
    )
    return _hpd_explore_url(soql)


def dining_listing_url(card: dict, formatted_address: str = "") -> str | None:
    """Business-specific Yelp or Google Maps listing for a dining row."""
    direct = (card.get("url") or "").strip()
    if direct:
        return direct
    name = (card.get("name") or "").strip()
    if not name:
        return None
    coords = card.get("coordinates") if isinstance(card.get("coordinates"), dict) else {}
    lat = coords.get("lat")
    lng = coords.get("lng")
    source = str(card.get("source") or "")
    if source == "yelp":
        loc = formatted_address or (f"{lat},{lng}" if lat is not None and lng is not None else "")
        if not loc:
            return None
        return (
            "https://www.yelp.com/search?"
            f"find_desc={quote(name)}&find_loc={quote(loc)}"
        )
    query = f"{name} near {formatted_address}" if formatted_address else name
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def dining_area_url(formatted_address: str, coord: Coordinate) -> str:
    """Google Maps search for restaurants near the scanned address."""
    if formatted_address:
        query = f"restaurants near {formatted_address}"
    else:
        query = f"restaurants near {coord.lat:.5f},{coord.lng:.5f}"
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"
