"""
Google Gemini AI — writes one bottom-line sentence per data card. Card chrome,
fact bullets and the Wellness Score come from Python (services.threat_card_layout).
"""

import os
import re
import json
import time
import asyncio
import hashlib
import logging
from collections import OrderedDict
from dataclasses import dataclass
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from models.schemas import Coordinate, FlightPath, FlightExposure, LogisticsCard
from services import city_data, nyc_baselines
from services.threat_card_layout import (
    CardChromeContext,
    ScanCounts,
    card_percentile,
    card_severity,
    cards_from_specs_and_bullets,
    compute_risk_from_counts,
    filter_threat_cards_for_exposure,
)

logger = logging.getLogger(__name__)

# Bump this when bullet formatting / merge rules change so in-memory caches don't
# serve stale card text across deploys.
_ANALYSIS_CACHE_VERSION = "2026-11-20-construction-311-window-v6"

_PENDING_BULLETS_TTL_SEC = 300

# Allow override via env (Railway / local).
# Default raised so Gemini can finish during end-to-end debugging.
# Set GEMINI_TIMEOUT_SECONDS=0 (or negative) to disable the asyncio wait_for guard.
_GEMINI_TIMEOUT_RAW = os.getenv("GEMINI_TIMEOUT_SECONDS", "300").strip()
if not _GEMINI_TIMEOUT_RAW:
    _GEMINI_TIMEOUT = 300.0
else:
    _GEMINI_TIMEOUT = float(_GEMINI_TIMEOUT_RAW)
_GEMINI_TIMEOUT_REPORT: float | None = None if _GEMINI_TIMEOUT <= 0 else _GEMINI_TIMEOUT
_GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "4096"))

_PLACEHOLDER_GEMINI_KEYS = frozenset(
    {
        "",
        "your_gemini_api_key_here",
        "your_google_ai_api_key_here",
    }
)


def _effective_gemini_key(raw: str | None = None) -> str:
    """Strip key / BOM; treat empty and common .env.example placeholders as unset."""
    s = (raw if raw is not None else (os.getenv("GEMINI_API_KEY") or "")).strip().lstrip("\ufeff")
    if not s:
        return ""
    lower = s.lower()
    if lower in _PLACEHOLDER_GEMINI_KEYS or "your_gemini_api_key" in lower:
        return ""
    if s.startswith("<") and s.endswith(">"):
        return ""
    return s


def _sanitize_error_detail(text: str, max_len: int = 240) -> str:
    """
    Return a short, user-safe error snippet for JSON responses.
    Never echo API keys (defense-in-depth; keys shouldn't appear in exceptions anyway).
    """
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return ""
    # Redact common secret-ish patterns if they ever leak through upstream errors.
    s = re.sub(r"(?i)(api[_-]?key|token)\s*[:=]\s*\S+", r"\1=<redacted>", s)
    return s[:max_len]


def _classify_gemini_error(e: Exception) -> tuple[str, str]:
    """
    Map exceptions to (kind, detail) where kind is a coarse category for clients.
    detail is sanitized and safe to return in JSON.
    """
    detail = _sanitize_error_detail(str(e))

    # google.api_core.GoogleAPICallError has structured fields
    if isinstance(e, google_exceptions.GoogleAPICallError):
        code = getattr(e, "grpc_status_code", None) or getattr(e, "code", None)
        reason = getattr(e, "reason", None) or ""
        msg = f"{reason} {detail}".strip().lower()

        if isinstance(e, google_exceptions.NotFound) or "not found" in msg or "was not found" in msg or "404" in msg:
            return "not_found", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.PermissionDenied) or "permission denied" in msg or "403" in msg:
            return "auth", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.ResourceExhausted) or "resource exhausted" in msg or "429" in msg:
            return "quota", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.InvalidArgument) or "invalid argument" in msg or "400" in msg:
            return "bad_request", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.Unauthenticated) or "unauthenticated" in msg or "401" in msg:
            return "auth", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.ServiceUnavailable) or "503" in msg or "unavailable" in msg:
            return "unavailable", _sanitize_error_detail(f"{reason} {detail}".strip())
        if isinstance(e, google_exceptions.DeadlineExceeded) or "deadline exceeded" in msg:
            return "deadline", _sanitize_error_detail(f"{reason} {detail}".strip())

        if code is not None:
            return "api_error", _sanitize_error_detail(f"{type(e).__name__} code={code} {detail}".strip())

        return "api_error", _sanitize_error_detail(f"{type(e).__name__} {detail}".strip())

    # Non-Google errors / wrapped errors
    msg = detail.lower()
    if isinstance(e, json.JSONDecodeError) or "jsondecodeerror" in type(e).__name__.lower():
        return "json_parse", _sanitize_error_detail(str(e))
    if "could not parse json" in msg or "could not parse" in msg:
        if "truncat" in msg or "unterminated" in msg or "unexpected end" in msg:
            return "truncated_output", detail
        return "json_parse", detail
    if "empty gemini response" in msg or "blocked" in msg or "no candidates" in msg:
        return "empty", detail
    if "deadline exceeded" in msg:
        return "deadline", detail
    if "ssl" in msg or "certificate" in msg:
        return "tls", detail
    if "timed out" in msg or "timeout" in msg:
        # Should normally be asyncio.TimeoutError, but keep a fallback for library wording
        return "timeout", detail
    if "not found" in msg or "was not found" in msg or "404" in msg:
        return "not_found", detail
    if "permission denied" in msg or "403" in msg or "invalid api key" in msg or "api key not valid" in msg:
        return "auth", detail
    if "429" in msg or "resource exhausted" in msg or "quota" in msg or "rate limit" in msg:
        return "quota", detail
    if "401" in msg or "unauthenticated" in msg:
        return "auth", detail
    if "400" in msg or "invalid argument" in msg:
        return "bad_request", detail
    if "503" in msg or "service unavailable" in msg:
        return "unavailable", detail

    return "unknown", detail


# ── Scan facts ────────────────────────────────────────────────────────────────

_ANALYSIS_CACHE_MAX = 500
_analysis_cache: "OrderedDict[str, dict]" = OrderedDict()


def _cache_get(key: str) -> dict | None:
    hit = _analysis_cache.get(key)
    if hit is not None:
        _analysis_cache.move_to_end(key)
    return hit


def _cache_put(key: str, value: dict) -> None:
    _analysis_cache[key] = value
    _analysis_cache.move_to_end(key)
    while len(_analysis_cache) > _ANALYSIS_CACHE_MAX:
        _analysis_cache.popitem(last=False)


@dataclass(frozen=True)
class ScanFacts:
    crime: city_data.FeedResult
    police_calls: city_data.FeedResult
    reports_311: city_data.FeedResult
    permits: city_data.FeedResult
    evictions: city_data.FeedResult
    counts: ScanCounts
    radius_miles: float

    @classmethod
    def build(
        cls,
        *,
        crime: city_data.FeedResult,
        police_calls: city_data.FeedResult,
        reports_311: city_data.FeedResult,
        permits: city_data.FeedResult,
        evictions: city_data.FeedResult,
    ) -> "ScanFacts":
        return cls(
            crime=crime,
            police_calls=police_calls,
            reports_311=reports_311,
            permits=permits,
            evictions=evictions,
            counts=ScanCounts.from_feeds(
                crime=crime,
                police_calls=police_calls,
                reports_311=reports_311,
                permits=permits,
                evictions=evictions,
            ),
            radius_miles=city_data.get_scan_radius_miles(),
        )


@dataclass
class PendingBulletsContext:
    address: str
    coord: Coordinate
    facts: ScanFacts
    logistics: list[LogisticsCard]
    flight_path: FlightPath | None
    flight_exposure: FlightExposure | None
    chrome_ctx: CardChromeContext
    template_bullets: dict[str, list[str]]
    risk: dict
    cache_key: str


_pending_bullets: dict[str, tuple[float, PendingBulletsContext]] = {}


def _visible_threat_cards(
    bullets_by_id: dict[str, list[str]],
    chrome: CardChromeContext,
) -> list[dict]:
    cards = cards_from_specs_and_bullets(bullets_by_id, chrome)
    return filter_threat_cards_for_exposure(
        cards, show_flight_feature=chrome.show_flight_feature
    )


def _purge_expired_pending() -> None:
    now = time.monotonic()
    for key, (expires, _) in list(_pending_bullets.items()):
        if expires < now:
            del _pending_bullets[key]


def _store_pending(ctx: PendingBulletsContext) -> str:
    _purge_expired_pending()
    _pending_bullets[ctx.cache_key] = (time.monotonic() + _PENDING_BULLETS_TTL_SEC, ctx)
    return ctx.cache_key


def _gemini_meta(
    *,
    configured: bool,
    status: str | None,
    latency_ms: int | None = None,
    error_kind: str | None = None,
    error_detail: str | None = None,
) -> dict:
    return {
        "gemini_configured": configured,
        "gemini_status": status,
        "gemini_latency_ms": latency_ms,
        "gemini_timeout_seconds": _GEMINI_TIMEOUT_REPORT,
        "gemini_error_kind": error_kind,
        "gemini_error_detail": error_detail,
    }


# Cards that may get a fourth bullet from Gemini (only when the card's data loaded).
GEMINI_CARD_IDS = ("high_churn", "police_calls", "area_safety", "demolitions", "noise_schedule", "reports_311")

BULLETS_SYSTEM_PROMPT = """You are ZerMap, a renter-focused assistant for NYC apartment hunters.
You receive a data brief about one NYC address. For each card listed below, write ONE
practical step a renter can take because of this signal: something to check, to ask the
landlord or broker, or to try during a visit (e.g. "Visit on a weeknight evening to hear the block.").

Rules:
- Plain English, one sentence, at most ~90 characters, starting with a verb.
- Advice only. Don't restate the data or say whether anything is more, fewer, higher or
  lower: the card already shows the counts and the NYC comparison. No digits.
- nyc_level tells you how notable each signal is; for "lower than most of NYC" signals,
  suggest a light check rather than a warning.
- Never invent facts that aren't in the brief.
- high_churn = residential evictions carried out by NYC Marshals (not court filings).
- police_calls = crime-in-progress 911 calls dispatched to NYPD (not complaints).
- area_safety = NYPD crime complaints; major felonies are the seven index crimes.
- demolitions = active DOB permits for disruptive work plus 311 construction complaints.
- noise_schedule = 311 noise complaints only.
- reports_311 = all 311 requests except parking and vehicle complaints.
- Don't mention dates or how recent the data is (NYPD data lags by months), and never
  say "this week", "lately" or "recently".
- Skip any card listed under UNAVAILABLE (return an empty string for it).
- No markdown, no HTML.

Return ONLY valid JSON (no markdown fences) in exactly this shape:
{"bottom_lines": {"high_churn": "...", "police_calls": "...", "area_safety": "...",
"demolitions": "...", "noise_schedule": "...", "reports_311": "..."}}
"""


def _extract_text_from_response(response) -> str:
    """
    google-generativeai sometimes raises on .text when content is blocked or empty.
    Fall back to walking candidates/parts.
    """
    try:
        t = (response.text or "").strip()
        if t:
            return t
    except (ValueError, AttributeError) as e:
        logger.warning("Gemini response.text unavailable: %s", e)

    try:
        cand = response.candidates[0]
        parts = cand.content.parts
        chunks = []
        for p in parts:
            if hasattr(p, "text") and p.text:
                chunks.append(p.text)
        return "\n".join(chunks).strip()
    except (IndexError, AttributeError, KeyError) as e:
        logger.warning("Could not read Gemini candidates: %s", e)
    return ""


def _parse_ai_json(raw: str) -> dict:
    """Parse JSON from model output; tolerate markdown fences and leading junk."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s else s
        s = s.strip()
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", s)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    # The reply can repeat the address from the brief, and this message gets logged.
    raise ValueError(f"Could not parse JSON from Gemini output ({len(s)} chars)")


# ── Wording helpers ───────────────────────────────────────────────────────────

def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return singular if n == 1 else (plural or f"{singular}s")


def _nice_type(name: str) -> str:
    """'UNSANITARY CONDITION' -> 'Unsanitary Condition'; mixed-case names unchanged."""
    s = " ".join(str(name or "").split())
    return s.title() if s.isupper() else s


def _top_phrase(top: list[tuple[str, int]], n: int = 2) -> str:
    parts = [f"{_nice_type(name)} ({count:,})" for name, count in top[:n] if name]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"


_COMPARE_SUBJECT = {
    "high_churn": ("Evictions", "are"),
    "police_calls": ("Crime-in-progress calls", "are"),
    "area_safety": ("Major felonies", "are"),
    "demolitions": ("Construction activity", "is"),
    "noise_schedule": ("Noise complaints", "are"),
    "reports_311": ("Requests to 311", "are"),
}


def _compare_sentence(card_id: str, chrome: CardChromeContext) -> str:
    p = card_percentile(card_id, chrome)
    if p is None:
        return ""
    pct = int(round(p * 100))
    subject, verb = _COMPARE_SUBJECT[card_id]
    if pct >= 50:
        return f"{subject} here {verb} higher than at {pct}% of NYC apartment locations."
    return f"{subject} here {verb} lower than at {100 - pct}% of NYC apartment locations."


def _unavailable(label: str, *, scored: bool) -> list[str]:
    return [
        f"{label} are unavailable right now.",
        "NYC Open Data didn't respond, so we're not guessing.",
        "Left out of the Wellness Score this time." if scored else "Try the scan again in a few minutes.",
    ]


def _window_text(f: city_data.FeedResult) -> str:
    return city_data.format_window(f.window_start, f.window_end)


def build_template_bullets(
    facts: ScanFacts,
    chrome: CardChromeContext,
    *,
    flight_exposure: FlightExposure | None,
    flight_path: FlightPath | None,
) -> dict[str, list[str]]:
    """Every bullet from exact counts; Gemini may append a fourth takeaway (see _apply_bottom_lines)."""
    r = f"{facts.radius_miles:g} mi"
    out: dict[str, list[str]] = {}

    ev = facts.evictions
    if not ev.available:
        out["high_churn"] = _unavailable("Eviction records", scored=True)
    else:
        n = ev.count()
        out["high_churn"] = [
            f"{n:,} residential {_plural(n, 'eviction')} within {r} ({_window_text(ev)})."
            if n else f"No residential evictions within {r} ({_window_text(ev)}).",
            "Counts evictions carried out by NYC Marshals, not court filings.",
            _compare_sentence("high_churn", chrome),
        ]

    calls = facts.police_calls
    if not calls.available:
        out["police_calls"] = _unavailable("NYPD call records", scored=False)
    else:
        n = calls.count()
        critical = calls.part("critical")
        out["police_calls"] = [
            f"{n:,} crime-in-progress {_plural(n, 'call')} to NYPD within {r} ({_window_text(calls)})."
            if n else f"No crime-in-progress calls to NYPD within {r} ({_window_text(calls)}).",
            f"{critical:,} {'was' if critical == 1 else 'were'} critical, like shots fired or a burglary in progress."
            if n else "That window ends at the newest data NYPD has published.",
            _compare_sentence("police_calls", chrome),
        ]

    crime = facts.crime
    if not crime.available:
        out["area_safety"] = _unavailable("NYPD complaint records", scored=True)
    else:
        n = crime.count()
        major = crime.part("major_felonies")
        out["area_safety"] = [
            f"{n:,} NYPD crime {_plural(n, 'complaint')} within {r} ({_window_text(crime)})."
            if n else f"No NYPD crime complaints within {r} ({_window_text(crime)}).",
            f"{major:,} major {_plural(major, 'felony', 'felonies')}: "
            f"{crime.part('violent'):,} violent, {crime.part('property'):,} property."
            if n else "That window ends at the newest data NYPD has published.",
            _compare_sentence("area_safety", chrome),
        ]

    out["tenant_warnings"] = [
        "HPD Online lists each building's open violations and complaints.",
        "Look up this building there before you sign.",
        "Ask the landlord about open violations, heat and pests.",
    ]

    permits, r311 = facts.permits, facts.reports_311
    if not permits.available and not r311.available:
        out["demolitions"] = _unavailable("DOB permit and 311 records", scored=True)
    else:
        construction = r311.part("construction")
        c311 = (
            f"311 also logged {construction:,} construction {_plural(construction, 'complaint')} "
            f"({_window_text(r311)})."
            if r311.available else "311 construction complaints are unavailable right now."
        )
        if permits.available:
            n = permits.count()
            demo = permits.part("demolition")
            b1 = (
                f"{n:,} active DOB {_plural(n, 'permit')} for disruptive work within {r} "
                f"(issued {_window_text(permits)})."
                if n else f"No active DOB permits for disruptive work within {r} (issued {_window_text(permits)})."
            )
            b2 = f"Includes {demo:,} full {_plural(demo, 'demolition')}. {c311}" if n else c311
        else:
            b1 = "DOB permit records are unavailable right now."
            b2 = c311
        out["demolitions"] = [b1, b2, _compare_sentence("demolitions", chrome)]

    if not r311.available:
        out["noise_schedule"] = _unavailable("311 records", scored=True)
        out["reports_311"] = _unavailable("311 records", scored=True)
    else:
        noise = r311.part("noise")
        noise_top = _top_phrase(r311.extra.get("noise_top", []))
        out["noise_schedule"] = [
            f"{noise:,} noise {_plural(noise, 'complaint')} to 311 within {r} ({_window_text(r311)})."
            if noise else f"No noise complaints to 311 within {r} ({_window_text(r311)}).",
            f"Most often: {noise_top}." if noise and noise_top else "Covers residential, street and business noise reports.",
            _compare_sentence("noise_schedule", chrome),
        ]
        n = r311.count()
        top = _top_phrase(r311.top_types)
        out["reports_311"] = [
            f"{n:,} {_plural(n, 'request')} to 311 within {r} ({_window_text(r311)})."
            if n else f"No requests to 311 within {r} ({_window_text(r311)}).",
            f"Most common: {top}." if n and top else "Parking and vehicle complaints are excluded.",
            _compare_sentence("reports_311", chrome),
        ]

    if not flight_exposure or not flight_exposure.show_flight_feature:
        out["flight_path"] = ["", "", ""]
    else:
        out["flight_path"] = [
            flight_exposure.headline or "More low-altitude flights than most NYC apartment locations.",
            flight_exposure.detail or "Based on stored ADS-B aircraft positions.",
            "Cyan lines on the map are recent real flight tracks."
            if flight_path is not None
            else "No recent tracks crossed the map area during the latest sample.",
        ]

    out["oven_effect"] = [
        "Afternoon heat depends on which way the unit faces.",
        "West- and south-facing windows can raise summer AC costs.",
        "Ask which way the windows face, or visit on a sunny afternoon.",
    ]
    return out


# ── Gemini bottom lines ───────────────────────────────────────────────────────

_COMPARISON_RE = re.compile(
    r"\b(nyc|new york|percent|percentile|average|typical|than|citywide|more|fewer|less|higher|lower"
    r"|quieter|louder|safer|busier|calmer|worse|better)\b|%",
    re.IGNORECASE,
)
_RECENCY_RE = re.compile(r"\b(data|latest|recent|recently|lately|this week|this month)\b", re.IGNORECASE)


def _accept_bottom_line(text: object) -> str | None:
    """Gemini text is used only if it is short and plain advice: no numbers, NYC comparisons
    or claims about how recent the data is.

    Counts, date ranges and the NYC comparison come from code; a model restating them can get them wrong.
    """
    if not isinstance(text, str):
        return None
    s = " ".join(text.split()).strip()
    if not s or len(s) > 120 or "<" in s or ">" in s:
        return None
    if any(ch.isdigit() for ch in s) or _COMPARISON_RE.search(s) or _RECENCY_RE.search(s):
        return None
    return s


def _feed_line(name: str, f: city_data.FeedResult, fields: dict[str, object]) -> str:
    if not f.available:
        return f"{name}: UNAVAILABLE"
    window = city_data.format_window(f.window_start, f.window_end)
    body = "; ".join(f"{k}={v}" for k, v in fields.items() if v not in (None, ""))
    return f"{name} [{window}]: {body}"


_NYC_LEVEL_WORDS = {
    "quiet": "lower than most NYC apartment locations",
    "watch": "about typical for NYC",
    "elevated": "higher than most NYC apartment locations",
}


def _pct_field(card_id: str, chrome: CardChromeContext) -> str | None:
    return _NYC_LEVEL_WORDS.get(card_severity(card_id, chrome))


def build_gemini_brief(ctx: PendingBulletsContext) -> str:
    f, chrome = ctx.facts, ctx.chrome_ctx

    def top(fr: city_data.FeedResult) -> str:
        return ", ".join(f"{_nice_type(k)}:{v}" for k, v in fr.top_types[:3])

    unavailable = [
        card for card, fr in (
            ("high_churn", f.evictions), ("police_calls", f.police_calls), ("area_safety", f.crime),
            ("noise_schedule", f.reports_311), ("reports_311", f.reports_311),
        ) if not fr.available
    ]
    if not f.permits.available and not f.reports_311.available:
        unavailable.append("demolitions")
    fx = ctx.flight_exposure
    if fx and fx.show_flight_feature:
        flight_text = fx.headline or "Above typical NYC flight exposure."
    elif fx is None or fx.elevation_level == "unavailable":
        # Not compared (paused, unreadable or no baseline): never tell the model it is typical.
        flight_text = "Not measured (no flight section in this report)."
    else:
        flight_text = "Typical for NYC (card hidden)."
    lines = [
        f"ADDRESS: {ctx.address}",
        f"RADIUS_MILES: {f.radius_miles:g}",
        _feed_line("NYPD_COMPLAINTS (newest NYPD release)", f.crime, {
            "total": f.crime.count(), "major_felonies": f.crime.part("major_felonies"),
            "violent": f.crime.part("violent"), "property": f.crime.part("property"),
            "top": top(f.crime), "major_felonies_nyc_level": _pct_field("area_safety", chrome),
        }),
        _feed_line("NYPD_CRIME_IN_PROGRESS_CALLS (newest NYPD release)", f.police_calls, {
            "total": f.police_calls.count(), "critical": f.police_calls.part("critical"),
            "nyc_level": _pct_field("police_calls", chrome),
        }),
        _feed_line("SR311 (parking/vehicle excluded)", f.reports_311, {
            "total": f.reports_311.count(), "noise": f.reports_311.part("noise"),
            "construction": f.reports_311.part("construction"), "top": top(f.reports_311),
            "nyc_level": _pct_field("reports_311", chrome),
            "noise_nyc_level": _pct_field("noise_schedule", chrome),
        }),
        _feed_line("DOB_ACTIVE_PERMITS (issued in window, still open)", f.permits, {
            "total": f.permits.count(), "full_demolitions": f.permits.part("demolition"),
            "scaffolds_and_sheds": f.permits.part("scaffold_shed"),
            "construction_nyc_level": _pct_field("demolitions", chrome),
        }),
        _feed_line("RESIDENTIAL_EVICTIONS (carried out by NYC Marshals)", f.evictions, {
            "total": f.evictions.count(), "nyc_level": _pct_field("high_churn", chrome),
        }),
        f"FLIGHT: {flight_text}",
        f"UNAVAILABLE: {', '.join(unavailable) if unavailable else 'none'}",
    ]
    return "\n".join(lines)


def _apply_bottom_lines(
    template: dict[str, list[str]],
    lines: dict[str, object],
    *,
    chrome: CardChromeContext,
) -> dict[str, list[str]]:
    """Accepted takeaways are appended after the three fact bullets, which stay unchanged."""
    out = {k: v[:] for k, v in template.items()}
    for cid in GEMINI_CARD_IDS:
        if card_severity(cid, chrome) not in ("quiet", "watch", "elevated"):
            continue
        accepted = _accept_bottom_line(lines.get(cid))
        if accepted and cid in out:
            out[cid].append(accepted)
    return out


async def _run_gemini_bullets(ctx: PendingBulletsContext) -> dict:
    """Gemini writes one bottom line per data card; template bullets stay on any failure."""
    def result(bullets: dict[str, list[str]], **meta) -> dict:
        return {**ctx.risk, "threat_cards": _visible_threat_cards(bullets, ctx.chrome_ctx), **_gemini_meta(**meta)}

    raw_gemini_env = (os.getenv("GEMINI_API_KEY") or "").strip()
    gemini_api_key = _effective_gemini_key(raw_gemini_env)
    if not gemini_api_key:
        return result(ctx.template_bullets, configured=False, status="no_key" if not raw_gemini_env else "placeholder")

    gemini_model_name = (os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel(
        model_name=gemini_model_name,
        system_instruction=BULLETS_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=0.35,
            max_output_tokens=_GEMINI_MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
        ),
    )
    brief = build_gemini_brief(ctx)

    async def _call() -> dict[str, list[str]]:
        if _GEMINI_TIMEOUT > 0:
            response = await asyncio.wait_for(
                asyncio.to_thread(model.generate_content, brief),
                timeout=_GEMINI_TIMEOUT,
            )
        else:
            response = await asyncio.to_thread(model.generate_content, brief)
        raw = _extract_text_from_response(response)
        if not raw:
            logger.error("Gemini returned empty text. prompt_feedback=%s", getattr(response, "prompt_feedback", None))
            raise ValueError("Empty Gemini response (blocked or no candidates)")
        data = _parse_ai_json(raw)
        lines = data.get("bottom_lines") if isinstance(data, dict) else None
        if not isinstance(lines, dict):
            raise ValueError("Missing or invalid 'bottom_lines' object in Gemini JSON")
        return _apply_bottom_lines(ctx.template_bullets, lines, chrome=ctx.chrome_ctx)

    for attempt in range(2):
        t0 = time.monotonic()
        try:
            bullets_by_id = await _call()
            return result(bullets_by_id, configured=True, status="ok", latency_ms=int((time.monotonic() - t0) * 1000))
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.error("Gemini timed out after %.1fs (measured %.0fms) — using template bullets.", _GEMINI_TIMEOUT, latency_ms)
            return result(ctx.template_bullets, configured=True, status="timeout", latency_ms=latency_ms)
        except Exception as e:
            if attempt == 0:
                logger.warning("Gemini attempt 1 failed (%s), retrying once…", e)
                await asyncio.sleep(1.5)
                continue
            latency_ms = int((time.monotonic() - t0) * 1000)
            error_kind, error_detail = _classify_gemini_error(e)
            logger.exception("Gemini failed after retry (kind=%s, %.0fms) — using template bullets", error_kind, latency_ms)
            return result(
                ctx.template_bullets, configured=True, status="error", latency_ms=latency_ms,
                error_kind=error_kind, error_detail=error_detail or None,
            )
    return result(ctx.template_bullets, configured=True, status="error")


async def complete_deferred_bullets(bullets_token: str) -> dict | None:
    """Finish a deferred Gemini bullets call using a token from POST /scan."""
    token = (bullets_token or "").strip()
    if not token:
        return None

    hit = _cache_get(token)
    if hit and hit.get("gemini_status") not in (None, "pending"):
        return hit

    _purge_expired_pending()
    pending = _pending_bullets.get(token)
    if not pending:
        return None
    _, ctx = pending

    result = await _run_gemini_bullets(ctx)
    _cache_put(ctx.cache_key, result)
    _pending_bullets.pop(token, None)
    return result


def _cache_key(address: str, facts: ScanFacts, flight_exposure: FlightExposure | None, key_fp: str) -> str:
    def feed_tag(fr: city_data.FeedResult) -> str:
        if not fr.available:
            return f"{fr.key}:u"
        return f"{fr.key}:{fr.total}:{sorted(fr.breakdown.items())}:{fr.window_start}:{fr.window_end}"

    fx = flight_exposure
    fx_tag = f"fx{int(fx.show_flight_feature)}:{_flight_card_percentile(fx)}:{fx.headline}" if fx else "fx-"
    payload = "|".join([
        _ANALYSIS_CACHE_VERSION,
        str(nyc_baselines.meta().get("generated_at", "")),
        address,
        *(feed_tag(fr) for fr in (facts.crime, facts.police_calls, facts.reports_311, facts.permits, facts.evictions)),
        fx_tag,
        key_fp,
    ])
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _flight_card_percentile(fx: FlightExposure | None) -> float | None:
    """Highest of the night / day / combined NYC percentiles, like other cards' highest metric."""
    if not fx:
        return None
    values = [p for p in (fx.night_percentile, fx.day_percentile, fx.combined_percentile) if p is not None]
    return max(values) if values else None


async def analyze(
    address: str,
    coord: Coordinate,
    facts: ScanFacts,
    logistics: list[LogisticsCard],
    flight_path: FlightPath | None,
    flight_exposure: FlightExposure | None,
    *,
    defer_gemini: bool = False,
) -> dict:
    """
    Python builds the Wellness Score, card chrome and fact bullets; Gemini only adds
    one bottom line per data card. Template bullets are used whenever Gemini is off.
    """
    show_flight = bool(flight_exposure and flight_exposure.show_flight_feature)
    chrome_ctx = CardChromeContext(
        counts=facts.counts,
        flight_percentile=_flight_card_percentile(flight_exposure) if show_flight else None,
        show_flight_feature=show_flight,
    )

    raw_gemini_env = (os.getenv("GEMINI_API_KEY") or "").strip()
    gemini_api_key = _effective_gemini_key(raw_gemini_env)
    if not gemini_api_key and raw_gemini_env:
        logger.warning(
            "GEMINI_API_KEY is set but looks like a placeholder or template; Gemini is disabled. "
            "Use a real key from Google AI Studio on the backend (Railway), not the frontend."
        )

    key_fp = hashlib.sha256(gemini_api_key.encode()).hexdigest()[:12] if gemini_api_key else "none"
    cache_key = _cache_key(address, facts, flight_exposure, key_fp)
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit

    risk = compute_risk_from_counts(facts.counts)
    template = build_template_bullets(
        facts,
        chrome_ctx,
        flight_exposure=flight_exposure,
        flight_path=flight_path if show_flight else None,
    )

    if not gemini_api_key:
        result = {
            **risk,
            "threat_cards": _visible_threat_cards(template, chrome_ctx),
            **_gemini_meta(configured=False, status="placeholder" if raw_gemini_env else "no_key"),
        }
        _cache_put(cache_key, result)
        return result

    pending_ctx = PendingBulletsContext(
        address=address,
        coord=coord,
        facts=facts,
        logistics=logistics,
        flight_path=flight_path if show_flight else None,
        flight_exposure=flight_exposure,
        chrome_ctx=chrome_ctx,
        template_bullets=template,
        risk=risk,
        cache_key=cache_key,
    )

    if defer_gemini:
        return {
            **risk,
            "threat_cards": _visible_threat_cards(template, chrome_ctx),
            "bullets_token": _store_pending(pending_ctx),
            **_gemini_meta(configured=True, status="pending"),
        }

    result = await _run_gemini_bullets(pending_ctx)
    _cache_put(cache_key, result)
    return result
