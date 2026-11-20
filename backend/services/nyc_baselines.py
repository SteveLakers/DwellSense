"""
NYC reference distributions for "compared with typical NYC apartment locations".

Values are measured by scripts/calibrate_nyc_baselines.py at a deterministic random
sample of residential lots (NYC PLUTO, 3+ units, weighted by unit count) using the
same queries and windows as /scan. Nothing here is hand-tuned.
"""

from __future__ import annotations

import bisect
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BASELINES_PATH = Path(__file__).resolve().parent.parent / "data" / "nyc_baselines.json"

# 311 volume moves with the seasons and NYPD publishes a new quarter every three months, so the
# comparison counts drift from what a scan counts. Past this age the log asks for a re-run.
STALE_AFTER_DAYS = 45


def _measured_day(meta: dict) -> date | None:
    """New York calendar day the comparison counts were measured (meta.generated_at)."""
    try:
        stamp = datetime.fromisoformat(str(meta.get("generated_at")))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(ZoneInfo("America/New_York")).date()


@dataclass(frozen=True)
class Baseline:
    key: str
    values: tuple[float, ...]  # sorted ascending

    @property
    def n(self) -> int:
        return len(self.values)

    def quantile(self, q: float) -> float:
        if not self.values:
            return 0.0
        q = max(0.0, min(1.0, q))
        pos = q * (self.n - 1)
        lo = int(pos)
        hi = min(self.n - 1, lo + 1)
        frac = pos - lo
        return self.values[lo] * (1 - frac) + self.values[hi] * frac

    def percentile(self, x: float) -> float:
        """Mid-rank share of sampled locations below x (ties count half), in [0, 1]."""
        if not self.values:
            return 0.0
        below = bisect.bisect_left(self.values, x)
        ties = bisect.bisect_right(self.values, x) - below
        return (below + 0.5 * ties) / self.n


@lru_cache(maxsize=1)
def _load() -> tuple[dict[str, Baseline], dict]:
    try:
        raw = json.loads(BASELINES_PATH.read_text())
    except FileNotFoundError:
        logger.error("NYC baselines missing at %s — run scripts/calibrate_nyc_baselines.py", BASELINES_PATH)
        return {}, {}
    except (OSError, ValueError) as e:
        logger.error("NYC baselines unreadable (%s)", e)
        return {}, {}
    from services.city_data import get_scan_radius_miles

    calibrated = (raw.get("meta") or {}).get("radius_miles")
    if calibrated is None or abs(float(calibrated) - get_scan_radius_miles()) > 1e-9:
        # Counts grow with area, so percentiles from another radius would be wrong.
        logger.error(
            "NYC baselines were calibrated at %s mi but SCAN_RADIUS_MILES is %s — NYC comparisons disabled "
            "until scripts/calibrate_nyc_baselines.py is re-run.", calibrated, get_scan_radius_miles(),
        )
        return {}, {}
    metrics = {
        key: Baseline(key=key, values=tuple(sorted(float(v) for v in spec.get("values", []))))
        for key, spec in (raw.get("metrics") or {}).items()
        if spec.get("values")
    }
    measured = _measured_day(raw.get("meta") or {})
    if measured is not None:
        age = (datetime.now(ZoneInfo("America/New_York")).date() - measured).days
        if age > STALE_AFTER_DAYS:
            logger.warning(
                "NYC baselines were measured %s days ago (%s). Re-run scripts/calibrate_nyc_baselines.py "
                "so NYC comparisons match current 311 and NYPD volumes.", age, measured,
            )
    return metrics, raw.get("meta") or {}


def get(key: str) -> Baseline | None:
    return _load()[0].get(key)


def meta() -> dict:
    return _load()[1]


def measured_on() -> str | None:
    """Day the comparison counts were measured (YYYY-MM-DD, New York time); shown with every report."""
    day = _measured_day(meta())
    return day.isoformat() if day else None


def percentile(key: str, x: float) -> float | None:
    b = get(key)
    return b.percentile(x) if b else None
