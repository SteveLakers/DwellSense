"""In-memory dossier store — raw scan rows for PDF generation (local + single-instance)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

_DOSSIER_TTL_SEC = 30 * 60
_MAX_DOSSIERS = 300
ADSB_PDF_ROWS = 80

_pending_dossiers: dict[str, tuple[float, DossierContext]] = {}


def feed_summary(feed: Any) -> dict:
    """Serializable FeedResult summary (exact totals + windows) for the PDF."""
    return {
        "key": feed.key,
        "label": feed.label,
        "status": "ok" if feed.available else "unavailable",
        "total": feed.total if feed.available else None,
        "breakdown": dict(feed.breakdown),
        "top_types": list(feed.top_types),
        "window_start": feed.window_start.isoformat() if feed.window_start else None,
        "window_end": feed.window_end.isoformat() if feed.window_end else None,
        "as_of": feed.as_of.isoformat() if feed.as_of else None,
        "source": feed.source,
        "rows_sampled": feed.rows_sampled,
        "note": feed.note,
        "extra": dict(feed.extra),
    }


@dataclass
class DossierContext:
    formatted_address: str
    coord_lat: float
    coord_lng: float
    scan_radius_miles: float
    scanned_at: str

    # Rows loaded for map / PDF tables (newest first; may be a subset — see feeds[...]["rows_sampled"]).
    crime: list[dict]
    reports_311: list[dict]
    permits: list[dict]
    evictions: list[dict]

    # feed key -> feed_summary(); totals here are exact in-radius counts.
    feeds: dict[str, dict]
    data_sources: list[dict]
    score_available: bool

    logistics: list[dict]
    dining_candidates: list[dict]

    flight_paths: list[dict]
    adsb_samples: list[dict]
    flight_exposure: dict | None

    map_swarm_shown: int
    map_swarm_total: int | None
    map_zones_count: int

    adsb_sample_total: int = 0
    dossier_token: str = field(default="")

    def __post_init__(self) -> None:
        # Keep memory bounded: the PDF lists the newest samples and states the true total.
        self.adsb_sample_total = len(self.adsb_samples)
        self.adsb_samples = sorted(
            self.adsb_samples, key=lambda r: str(r.get("observed_at") or ""), reverse=True
        )[:ADSB_PDF_ROWS]


def _purge_expired() -> None:
    now = time.monotonic()
    for key, (expires, _) in list(_pending_dossiers.items()):
        if expires < now:
            del _pending_dossiers[key]
    while len(_pending_dossiers) > _MAX_DOSSIERS:
        oldest = min(_pending_dossiers, key=lambda k: _pending_dossiers[k][0])
        del _pending_dossiers[oldest]


def store_dossier(ctx: DossierContext) -> str:
    token = secrets.token_urlsafe(24)
    ctx.dossier_token = token
    _pending_dossiers[token] = (time.monotonic() + _DOSSIER_TTL_SEC, ctx)
    _purge_expired()
    return token


def get_dossier(token: str) -> DossierContext | None:
    _purge_expired()
    key = (token or "").strip()
    if not key:
        return None
    entry = _pending_dossiers.get(key)
    if not entry:
        return None
    expires, ctx = entry
    if expires < time.monotonic():
        del _pending_dossiers[key]
        return None
    return ctx
