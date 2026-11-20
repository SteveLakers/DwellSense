#!/usr/bin/env python3
"""
Measure what /scan counts look like at typical NYC apartment locations.

Sample: NYC PLUTO residential lots with 3+ units, drawn with probability
proportional to residential units (systematic PPS, fixed seed), so the sample
reflects where NYC renters actually live. At each point we run the exact feed
queries /scan uses (same radius, same windows) and write the sorted values to
backend/data/nyc_baselines.json. Nothing is estimated or hand-tuned.

Read-only: NYC Open Data + SELECTs on Supabase adsb_samples.

Usage (from backend/):
    venv/bin/python scripts/calibrate_nyc_baselines.py [--points 200] [--flight-points 60]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

from models.schemas import Coordinate  # noqa: E402
from services import city_data, flight_exposure, socrata  # noqa: E402
from services.nyc_baselines import BASELINES_PATH  # noqa: E402

PLUTO_DATASET = "64uk-42ks"
SEED = 20261002
logger = logging.getLogger("calibrate")


def load_lots() -> tuple[list[dict], str]:
    rows, truncated = socrata.query_all(
        PLUTO_DATASET,
        where="unitsres >= 3 AND latitude IS NOT NULL AND longitude IS NOT NULL",
        select="bbl, borough, unitsres, latitude, longitude",
        order="bbl",
        page_size=50_000,
        max_rows=400_000,
        timeout=120.0,
    )
    if truncated:
        raise SystemExit("PLUTO read truncated — raise max_rows")
    version = (socrata.query(PLUTO_DATASET, {"$select": "version", "$limit": 1}) or [{}])[0].get("version", "")
    lots = []
    for r in rows:
        try:
            lots.append({
                "bbl": str(r["bbl"]).split(".")[0],
                "borough": r.get("borough") or "",
                "units": int(float(r["unitsres"])),
                "lat": float(r["latitude"]),
                "lng": float(r["longitude"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return lots, version


def pps_sample(lots: list[dict], n: int, seed: int) -> list[dict]:
    """Systematic probability-proportional-to-size sample on residential units."""
    rng = random.Random(seed)
    total = sum(l["units"] for l in lots)
    step = total / n
    targets = [rng.random() * step + k * step for k in range(n)]
    picks: list[dict] = []
    cum = 0
    i = 0
    for lot in lots:
        cum += lot["units"]
        while i < n and targets[i] < cum:
            picks.append(dict(lot))
            i += 1
    rng.shuffle(picks)  # flight subset = first K points, a random subset
    return picks


async def measure_point(point: dict, *, with_flights: bool) -> dict:
    coord = Coordinate(lat=point["lat"], lng=point["lng"])
    crime, calls, r311, permits, evictions = await asyncio.gather(
        city_data.get_crime_feed(coord, include_rows=False),
        city_data.get_police_calls_feed(coord),
        city_data.get_311_feed(coord, include_rows=False),
        city_data.get_permits_feed(coord, include_rows=False),
        city_data.get_evictions_feed(coord, include_rows=False),
    )
    feeds = (crime, calls, r311, permits, evictions)
    bad = [f.key for f in feeds if not f.available or f.source != "nyc_open_data"]
    if bad:
        raise RuntimeError(f"unavailable: {', '.join(bad)}")
    values = {
        "crime_total": crime.count(),
        "crime_major_felonies": crime.part("major_felonies"),
        "crime_violent": crime.part("violent"),
        "police_calls_total": calls.count(),
        "police_calls_critical": calls.part("critical"),
        "reports_311_total": r311.count(),
        "reports_311_noise": r311.part("noise"),
        "reports_311_construction": r311.part("construction"),
        "permits_total": permits.count(),
        "permits_demolition": permits.part("demolition"),
        "evictions_total": evictions.count(),
    }
    windows = {f.key: [str(f.window_start), str(f.window_end)] for f in feeds}
    if with_flights:
        # limited=False: wait for slow reads instead of dropping the busiest locations.
        window = await asyncio.to_thread(flight_exposure.load_adsb_window, coord, limited=False)
        if window is None or window.truncated or not window.covered:
            raise RuntimeError("ADS-B window unavailable")
        rates = flight_exposure.pass_rates(window.rows, window.covered)
        values["flight_night_passes_per_hr"] = round(rates.night_per_hr, 4)
        values["flight_day_passes_per_hr"] = round(rates.day_per_hr, 4)
        windows["flights"] = [window.since.isoformat(), window.until.isoformat()]
    return {"values": values, "windows": windows}


async def run(points: int, flight_points: int, concurrency: int) -> None:
    t0 = time.time()
    lots, version = await asyncio.to_thread(load_lots)
    logger.info("PLUTO %s: %s lots with 3+ units", version, len(lots))
    sample = pps_sample(lots, points, SEED)
    await asyncio.to_thread(city_data.refresh_bis_snapshot)

    sem = asyncio.Semaphore(concurrency)
    results: list[dict | None] = [None] * len(sample)
    failures: dict[int, str] = {}

    async def worker(idx: int) -> None:
        point = sample[idx]
        for attempt in range(3):
            async with sem:
                try:
                    results[idx] = await measure_point(point, with_flights=idx < flight_points)
                    failures.pop(idx, None)
                    return
                except Exception as e:  # noqa: BLE001 — record and retry
                    failures[idx] = str(e)[:200]
            await asyncio.sleep(5 * (attempt + 1))

    done = 0

    async def tracked(idx: int) -> None:
        nonlocal done
        await worker(idx)
        done += 1
        if done % 10 == 0 or done == len(sample):
            logger.info("%s/%s points (%.0fs)", done, len(sample), time.time() - t0)

    await asyncio.gather(*(tracked(i) for i in range(len(sample))))

    measured = [(sample[i], r) for i, r in enumerate(results) if r is not None]
    if len(measured) < 0.9 * len(sample):
        raise SystemExit(f"Only {len(measured)}/{len(sample)} points measured — not writing baselines. {failures}")

    metric_keys = sorted({k for _, r in measured for k in r["values"]})
    metrics = {}
    for key in metric_keys:
        vals = sorted(float(r["values"][key]) for _, r in measured if key in r["values"])
        n = len(vals)
        metrics[key] = {
            "n": n,
            "p50": vals[n // 2],
            "p90": vals[min(n - 1, int(0.9 * n))],
            "values": vals,
        }
    windows: dict[str, list[str]] = {}
    for _, r in measured:
        for key, span in r["windows"].items():
            windows.setdefault(key, span)
    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "radius_miles": city_data.get_scan_radius_miles(),
            "sample": {
                "source": f"NYC PLUTO {version} ({PLUTO_DATASET})",
                "filter": "unitsres >= 3",
                "weighting": "systematic PPS on residential units",
                "seed": SEED,
                "requested_points": len(sample),
                "measured_points": len(measured),
                "flight_points": sum(1 for _, r in measured if "flight_night_passes_per_hr" in r["values"]),
            },
            "windows": windows,
            "failed_points": len(sample) - len(measured),
        },
        "metrics": metrics,
        "points": [
            {"bbl": p["bbl"], "borough": p["borough"], "units": p["units"], "lat": p["lat"], "lng": p["lng"],
             **r["values"]}
            for p, r in measured
        ],
    }
    BASELINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINES_PATH.write_text(json.dumps(out, indent=1) + "\n")
    logger.info("Wrote %s (%s points, %.0fs)", BASELINES_PATH, len(measured), time.time() - t0)
    for key, spec in metrics.items():
        logger.info("  %-28s n=%-4s p50=%-10s p90=%s", key, spec["n"], spec["p50"], spec["p90"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--points", type=int, default=200)
    parser.add_argument("--flight-points", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "services.city_data", "services.socrata"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    asyncio.run(run(args.points, args.flight_points, args.concurrency))


if __name__ == "__main__":
    main()
