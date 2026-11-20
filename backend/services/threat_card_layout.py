"""
Fixed threat-card chrome (ids, emoji, titles, subtitles) and the Wellness Score.

Every comparison is against real measurements at sampled NYC apartment locations
(services/nyc_baselines.py). Sources that did not answer are left out of the score
and labeled unavailable — never treated as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services import city_data, nyc_baselines

# ── Inputs ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ScanCounts:
    """Exact in-radius counts per source; None = source unavailable for this scan."""

    crime: int | None = None
    crime_major_felonies: int | None = None
    crime_violent: int | None = None
    police_calls: int | None = None
    police_calls_critical: int | None = None
    reports_311: int | None = None
    reports_311_noise: int | None = None
    reports_311_construction: int | None = None
    permits: int | None = None
    permits_demolition: int | None = None
    evictions: int | None = None

    @classmethod
    def from_feeds(
        cls,
        *,
        crime: city_data.FeedResult,
        police_calls: city_data.FeedResult,
        reports_311: city_data.FeedResult,
        permits: city_data.FeedResult,
        evictions: city_data.FeedResult,
    ) -> "ScanCounts":
        def total(f: city_data.FeedResult) -> int | None:
            return f.count() if f.available else None

        def part(f: city_data.FeedResult, name: str) -> int | None:
            return f.part(name) if f.available else None

        return cls(
            crime=total(crime),
            crime_major_felonies=part(crime, "major_felonies"),
            crime_violent=part(crime, "violent"),
            police_calls=total(police_calls),
            police_calls_critical=part(police_calls, "critical"),
            reports_311=total(reports_311),
            reports_311_noise=part(reports_311, "noise"),
            reports_311_construction=part(reports_311, "construction"),
            permits=total(permits),
            permits_demolition=part(permits, "demolition"),
            evictions=total(evictions),
        )


def nyc_percentile(metric: str, value: int | float | None) -> float | None:
    """Share of sampled NYC apartment locations below value (None if unmeasured)."""
    if value is None:
        return None
    return nyc_baselines.percentile(metric, float(value))


# ── Score model ───────────────────────────────────────────────────────────────

# factor -> (baseline metric, weight). Weights sum to 1.
_SCORE_FACTORS: dict[str, tuple[str, float]] = {
    "crime": ("crime_total", 0.40),
    "311": ("reports_311_total", 0.26),
    "permits": ("permits_total", 0.14),
    "evictions": ("evictions_total", 0.20),
}
# Minimum weight that must be measured to show a score (e.g. NYPD + 311, or NYPD + two others).
_MIN_SCORED_WEIGHT = 0.66
_DENSE_CITY_OFFSET = 5

# Soft ceilings, as NYC percentiles (highest first).
_CAPS: dict[str, list[tuple[float, int]]] = {
    "crime": [(0.57, 38), (0.24, 50), (0.11, 58)],
    "evictions": [(0.83, 44), (0.66, 54)],
    "permits": [(0.81, 52), (0.66, 62)],
}
_CAP_NAMES = {"crime": "NYPD complaints", "evictions": "residential evictions", "permits": "active construction permits"}

# Excellent / Outstanding need several signals that are low for NYC.
_TOP_TIER_BLOCKERS = {"crime": 0.108, "evictions": 0.656, "311": 0.959, "permits": 0.75}
_TOP_TIER_SOFT = {"311": 0.81, "permits": 0.5}
_TOP_TIER_SOFT_MIN_SCORE = 86

# Wellness score 0–100, higher is better.
LABEL_BANDS: list[tuple[int, str, str]] = [
    (15, "EXTREME", "Terrible"),
    (28, "HIGH", "Bad"),
    (48, "MODERATE", "Average"),
    (62, "LOW", "Good"),
    (75, "LOW", "Very Good"),
    (83, "LOW", "Great"),
    (92, "LOW", "Excellent"),
    (100, "LOW", "Outstanding"),
]


def label_band_rows() -> list[tuple[int, int, str]]:
    """(low, high, label) rows for display, derived from LABEL_BANDS."""
    rows = []
    low = 0
    for ceiling, _, label in LABEL_BANDS:
        rows.append((low, ceiling, label))
        low = ceiling + 1
    return rows


def _factor_value(counts: ScanCounts, factor: str) -> int | None:
    return {
        "crime": counts.crime,
        "311": counts.reports_311,
        "permits": counts.permits,
        "evictions": counts.evictions,
    }[factor]


def score_percentiles(counts: ScanCounts) -> dict[str, float | None]:
    return {
        factor: nyc_percentile(metric, _factor_value(counts, factor))
        for factor, (metric, _) in _SCORE_FACTORS.items()
    }


def _label_for_score(score: int, pcts: dict[str, float | None], counts: ScanCounts) -> tuple[str, str]:
    risk_level, risk_label = "MODERATE", "Average"
    for ceiling, level, label in LABEL_BANDS:
        if score <= ceiling:
            risk_level, risk_label = level, label
            break
    if risk_label not in ("Excellent", "Outstanding"):
        return risk_level, risk_label

    if any(p is None for p in pcts.values()):
        return "LOW", "Great"
    all_zero = all((_factor_value(counts, f) or 0) == 0 for f in _SCORE_FACTORS)
    if all_zero:
        # An empty radius is more likely missing coverage than proof of excellence.
        return "LOW", "Very Good"
    if any((pcts[f] or 0) >= cut for f, cut in _TOP_TIER_BLOCKERS.items()):
        return "LOW", "Great"
    if any((pcts[f] or 0) >= cut for f, cut in _TOP_TIER_SOFT.items()):
        return "LOW", "Excellent" if score >= _TOP_TIER_SOFT_MIN_SCORE else "Great"
    return risk_level, risk_label


@dataclass(frozen=True)
class ScoreResult:
    available: bool
    score: int
    base_score: int
    percentiles: dict[str, float | None]
    caps_applied: list[str]
    unavailable_factors: list[str]


def compute_score(counts: ScanCounts) -> ScoreResult:
    pcts = score_percentiles(counts)
    measured = {f: p for f, p in pcts.items() if p is not None}
    weight = sum(_SCORE_FACTORS[f][1] for f in measured)
    unavailable = [f for f, p in pcts.items() if p is None]
    if weight < _MIN_SCORED_WEIGHT or "crime" not in measured:
        return ScoreResult(False, 0, 0, pcts, [], unavailable)

    hazard = sum(_SCORE_FACTORS[f][1] * p for f, p in measured.items()) / weight
    base = int(round(max(0.0, min(100.0, 100.0 - hazard * 100.0)))) - _DENSE_CITY_OFFSET
    base = max(0, base)
    score = base
    caps: list[str] = []
    for factor, steps in _CAPS.items():
        p = measured.get(factor)
        if p is None:
            continue
        for cut, ceiling in steps:
            if p >= cut:
                if score > ceiling:
                    score = ceiling
                    caps.append(factor)
                break
    return ScoreResult(True, score, base, pcts, caps, unavailable)


# ── Banner text ───────────────────────────────────────────────────────────────

_BANNER_FACTORS: dict[str, tuple[str, float, str, str]] = {
    # driver -> (baseline metric, tie-break weight, singular, plural)
    "area_safety": ("crime_total", 0.40, "NYPD complaint", "NYPD complaints"),
    "311": ("reports_311_total", 0.26, "request to 311", "requests to 311"),
    "permits": ("permits_total", 0.14, "active construction permit", "active construction permits"),
    "evictions": ("evictions_total", 0.20, "residential eviction", "residential evictions"),
    "noise": ("reports_311_noise", 0.11, "noise complaint", "noise complaints"),
}
_MIN_DRIVER_PERCENTILE = 0.60
_SECOND_DRIVER_WITHIN = 0.14
_UNAVAILABLE_NAMES = {
    "crime": "NYPD complaints",
    "311": "311 requests",
    "permits": "DOB permits",
    "evictions": "evictions",
}


def _driver_values(counts: ScanCounts) -> dict[str, int | None]:
    return {
        "area_safety": counts.crime,
        "311": counts.reports_311,
        "permits": counts.permits,
        "evictions": counts.evictions,
        "noise": counts.reports_311_noise,
    }


def pick_banner_drivers(counts: ScanCounts) -> list[tuple[str, int, float]]:
    """1–2 signals that stand out most vs. NYC apartment locations (percentile, not raw volume)."""
    candidates = []
    for kind, value in _driver_values(counts).items():
        metric, weight, _, _ = _BANNER_FACTORS[kind]
        p = nyc_percentile(metric, value)
        if value is None or p is None or p < _MIN_DRIVER_PERCENTILE:
            continue
        candidates.append((kind, value, p, weight * p))
    candidates.sort(key=lambda row: (-row[2], -row[3]))
    drivers = [(k, v, p) for k, v, p, _ in candidates[:1]]
    if len(candidates) > 1 and candidates[1][2] >= candidates[0][2] - _SECOND_DRIVER_WITHIN:
        drivers.append(candidates[1][:3])
    return drivers


def _driver_phrase(kind: str, value: int, percentile: float, *, first: bool) -> str:
    _, _, singular, plural = _BANNER_FACTORS[kind]
    word = singular if value == 1 else plural
    pct = int(round(percentile * 100))
    if first:
        return f"{value:,} {word} — higher than at {pct}% of NYC apartment locations"
    return f"{value:,} {word} (higher than at {pct}%)"


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _binding_cap(result: ScoreResult) -> tuple[str, float, int] | None:
    """(factor, percentile cut, ceiling) of the cap that set the final score."""
    if not result.caps_applied:
        return None
    factor = result.caps_applied[-1]
    p = result.percentiles.get(factor)
    for cut, ceiling in _CAPS[factor]:
        if p is not None and p >= cut:
            return factor, cut, ceiling
    return None


def build_risk_description(counts: ScanCounts, result: ScoreResult) -> tuple[str, str | None]:
    mi = f"{city_data.get_scan_radius_miles():g} mi"
    missing = [_UNAVAILABLE_NAMES[f] for f in result.unavailable_factors]
    if not result.available:
        return (
            f"Not scored: {_join_names(missing) or 'too few sources'} unavailable right now. "
            "The cards below show what did load.",
            None,
        )

    drivers = pick_banner_drivers(counts)
    if drivers:
        parts = [_driver_phrase(k, v, p, first=i == 0) for i, (k, v, p) in enumerate(drivers)]
        sentence = f"{'; '.join(parts)} — within {mi}."
    else:
        sentence = f"Nothing stands out compared with typical NYC apartment locations within {mi}."

    notes = []
    cap = _binding_cap(result)
    if cap:
        factor, cut, ceiling = cap
        notes.append(
            f"Capped at {ceiling}: a higher score needs {_CAP_NAMES[factor]} in the lowest "
            f"{round(cut * 100)}% of NYC apartment locations."
        )
    if missing:
        names = _join_names(missing)
        notes.append(f"{names[:1].upper()}{names[1:]} unavailable — scored on the other sources.")
    text = " ".join([sentence, *notes])
    return text, (drivers[0][0] if drivers else None)


def compute_risk_from_counts(counts: ScanCounts) -> dict[str, Any]:
    """`danger_score` is the Wellness Score: 0–100 where 100 is best."""
    result = compute_score(counts)
    description, driver = build_risk_description(counts, result)
    if not result.available:
        return {
            "danger_score": 0,
            "risk_level": "MODERATE",
            "risk_label": "Not scored",
            "risk_description": description,
            "banner_driver": None,
            "score_available": False,
        }
    risk_level, risk_label = _label_for_score(result.score, result.percentiles, counts)
    return {
        "danger_score": result.score,
        "risk_level": risk_level,
        "risk_label": risk_label,
        "risk_description": description,
        "banner_driver": driver,
        "score_available": True,
    }


# ── Cards ─────────────────────────────────────────────────────────────────────

# Order matches the UI carousel / Gemini system prompt.
CARD_SPECS: list[dict[str, Any]] = [
    {
        "id": "high_churn",
        "emoji": "🏃‍♂️",
        "title": "TENANT CHURN",
        "subtitle": "Residential evictions carried out by NYC Marshals.",
    },
    {
        "id": "police_calls",
        "emoji": "🚓",
        "title": "POLICE CALLS",
        "subtitle": "Crime-in-progress 911 calls dispatched to NYPD.",
    },
    {
        "id": "area_safety",
        "emoji": "🛡️",
        "title": "AREA SAFETY",
        "subtitle": "NYPD crime complaints, including the seven major felonies.",
    },
    {
        "id": "tenant_warnings",
        "emoji": "🗣️",
        "title": "TENANT WARNINGS",
        "subtitle": "Building violations aren't checked yet — look them up on HPD Online.",
    },
    {
        "id": "demolitions",
        "emoji": "🚧",
        "title": "CONSTRUCTION & DEMOLITIONS",
        "subtitle": "Active DOB permits for disruptive work and 311 construction complaints.",
    },
    {
        "id": "noise_schedule",
        "emoji": "🔊",
        "title": "NOISE COMPLAINTS",
        "subtitle": "311 noise complaints from neighbors.",
    },
    {
        "id": "flight_path",
        "emoji": "✈️",
        "title": "FLIGHT NOISE",
        "subtitle": "Low-altitude aircraft passes vs. NYC apartment locations (ADS-B).",
    },
    {
        "id": "reports_311",
        "emoji": "🐀",
        "title": "311 REPORTS",
        "subtitle": "311 service requests (parking and vehicle complaints excluded).",
    },
    {
        "id": "oven_effect",
        "emoji": "☀️",
        "title": "OVEN EFFECT",
        "subtitle": "General tip — not measured for this building.",
    },
]

# Card -> baseline metrics; severity uses the highest percentile among them, so a card with any
# metric unavailable is unavailable (the missing one could be the highest).
CARD_METRICS: dict[str, list[tuple[str, str]]] = {
    "high_churn": [("evictions_total", "evictions")],
    "police_calls": [("police_calls_total", "police_calls")],
    "area_safety": [("crime_major_felonies", "crime_major_felonies")],
    "demolitions": [("permits_total", "permits"), ("reports_311_construction", "reports_311_construction")],
    "noise_schedule": [("reports_311_noise", "reports_311_noise")],
    "reports_311": [("reports_311_total", "reports_311")],
}
_FIXED_SEVERITY = {"tenant_warnings": "not_checked", "oven_effect": "tip"}
_TIER_WATCH = 0.35
_TIER_ELEVATED = 0.70


def ordered_card_ids() -> list[str]:
    return [c["id"] for c in CARD_SPECS]


def filter_threat_cards_for_exposure(
    cards: list[dict[str, Any]],
    *,
    show_flight_feature: bool,
) -> list[dict[str, Any]]:
    """Hide the flight card when exposure is typical for NYC (not renter-actionable)."""
    if show_flight_feature:
        return cards
    return [c for c in cards if c.get("id") != "flight_path"]


@dataclass(frozen=True)
class CardChromeContext:
    counts: ScanCounts = ScanCounts()
    flight_percentile: float | None = None
    show_flight_feature: bool = False


_SEVERITY_CHROME: dict[str, tuple[str, str]] = {
    "quiet": ("#059669", "#6ee7b7"),
    "watch": ("#d97706", "#fbbf24"),
    "elevated": ("#f43f5e", "#fda4af"),
    "unavailable": ("#64748b", "#94a3b8"),
    "not_checked": ("#64748b", "#94a3b8"),
    "tip": ("#0284c7", "#7dd3fc"),
}


def card_percentile(card_id: str, ctx: CardChromeContext) -> float | None:
    if card_id == "flight_path":
        return ctx.flight_percentile
    best: float | None = None
    for metric, field_name in CARD_METRICS.get(card_id, []):
        p = nyc_percentile(metric, getattr(ctx.counts, field_name))
        if p is None:
            return None
        if best is None or p > best:
            best = p
    return best


def card_severity(card_id: str, ctx: CardChromeContext) -> str:
    if card_id in _FIXED_SEVERITY:
        return _FIXED_SEVERITY[card_id]
    p = card_percentile(card_id, ctx)
    if p is None:
        return "unavailable"
    if p >= _TIER_ELEVATED:
        return "elevated"
    if p >= _TIER_WATCH:
        return "watch"
    return "quiet"


def cards_from_specs_and_bullets(
    bullets_by_id: dict[str, list[str]],
    chrome: CardChromeContext | None = None,
) -> list[dict[str, Any]]:
    """Merge fixed chrome with up to four bullets per card — three facts plus an optional
    Gemini takeaway (order follows CARD_SPECS)."""
    ctx = chrome or CardChromeContext()
    out: list[dict[str, Any]] = []
    for spec in CARD_SPECS:
        cid = spec["id"]
        raw = bullets_by_id.get(cid)
        if not isinstance(raw, list):
            raw = []
        b = [s for s in (str(x).strip() for x in raw if x is not None) if s][:4]
        severity = card_severity(cid, ctx)
        border_color, text_color = _SEVERITY_CHROME[severity]
        p = card_percentile(cid, ctx) if severity in ("quiet", "watch", "elevated") else None
        out.append({
            **spec,
            "border_color": border_color,
            "text_color": text_color,
            "severity_level": severity,
            "nyc_percentile": int(round(p * 100)) if p is not None else None,
            "bullets": b,
        })
    return out
