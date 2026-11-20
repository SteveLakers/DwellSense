"""Scoring, NYC comparisons, flight passes, card bullets, record links and formatting.

Run from backend/:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("SCAN_RADIUS_MILES", None)

from models.schemas import Coordinate, FlightExposure  # noqa: E402
from routers import scan as scan_router  # noqa: E402
from services import city_data, flight_exposure, nyc_baselines, places, socrata, source_links  # noqa: E402
from services.socrata import SocrataError  # noqa: E402
from services.ai_analysis import (  # noqa: E402
    _accept_bottom_line,
    _classify_gemini_error,
    _flight_card_percentile,
    _parse_ai_json,
)
from services.flight_exposure import count_passes, pass_rates  # noqa: E402
from services.geocoding import nyc_county  # noqa: E402
from services.nyc_baselines import Baseline  # noqa: E402
from services.pdf_dossier import _display_date, _distance_text  # noqa: E402
from services.places import _miles_to_display  # noqa: E402
from services.threat_card_layout import (  # noqa: E402
    CardChromeContext,
    ScanCounts,
    build_risk_description,
    card_severity,
    cards_from_specs_and_bullets,
    compute_risk_from_counts,
    compute_score,
)

NYC = ZoneInfo("America/New_York")


def _q(metric: str, q: float) -> int:
    baseline = nyc_baselines.get(metric)
    assert baseline is not None, f"baseline {metric} missing"
    return int(round(baseline.quantile(q)))


def _typical(**overrides) -> ScanCounts:
    values = {
        "crime": _q("crime_total", 0.5),
        "reports_311": _q("reports_311_total", 0.5),
        "permits": _q("permits_total", 0.5),
        "evictions": _q("evictions_total", 0.5),
    }
    values.update(overrides)
    return ScanCounts(**values)


class BaselineTests(unittest.TestCase):
    def test_mid_rank_percentile(self):
        b = Baseline("x", (1.0, 2.0, 2.0, 3.0))
        self.assertEqual(b.percentile(0), 0.0)
        self.assertEqual(b.percentile(2), 0.5)
        self.assertEqual(b.percentile(10), 1.0)

    def test_calibration_file_loads_for_default_radius(self):
        self.assertEqual(nyc_baselines.meta().get("radius_miles"), 2.0)
        for metric in ("crime_total", "reports_311_total", "permits_total", "evictions_total"):
            self.assertIsNotNone(nyc_baselines.get(metric), metric)

    def test_measured_day_is_the_new_york_date(self):
        # 02:52 UTC on Oct 3 is still Oct 2 in New York.
        self.assertEqual(nyc_baselines._measured_day({"generated_at": "2026-10-03T02:52:45+00:00"}), date(2026, 10, 2))
        self.assertIsNone(nyc_baselines._measured_day({}))
        self.assertIsNone(nyc_baselines._measured_day({"generated_at": "not a date"}))

    def test_reports_can_say_when_the_comparison_was_measured(self):
        self.assertRegex(nyc_baselines.measured_on() or "", r"^\d{4}-\d{2}-\d{2}$")

    def test_baselines_were_measured_with_the_current_311_construction_definition(self):
        # "311 construction complaints" stopped counting HEAT/HOT WATER "ENTIRE BUILDING" rows on
        # 2026-11-20. A baseline file measured before that would compare a count with a different
        # kind of count, so re-run scripts/calibrate_nyc_baselines.py whenever the definition changes.
        self.assertGreaterEqual(nyc_baselines.measured_on() or "", "2026-11-20")

    def test_calibration_waits_for_slow_flight_reads(self):
        # The calibration script must not drop the busiest locations to a scan's time budget.
        with mock.patch.object(flight_exposure, "_get_client"), \
                mock.patch.object(flight_exposure, "covered_hours", return_value=set()), \
                mock.patch.object(flight_exposure, "_fetch_slice", return_value=([], False)) as fetch:
            flight_exposure._window_cache.clear()
            flight_exposure.pause_reads(60)
            try:
                window = flight_exposure.load_adsb_window(Coordinate(lat=40.7584, lng=-73.9922), limited=False)
            finally:
                flight_exposure._paused_until = 0.0
                flight_exposure._window_cache.clear()
        self.assertIsNotNone(window)
        self.assertTrue(all(call.args[0][3] == float("inf") for call in fetch.call_args_list))


class ScoreTests(unittest.TestCase):
    def test_needs_nypd_data(self):
        result = compute_score(_typical(crime=None))
        self.assertFalse(result.available)
        self.assertIn("crime", result.unavailable_factors)

    def test_needs_enough_weight(self):
        self.assertFalse(compute_score(ScanCounts(crime=100, permits=10)).available)

    def test_unavailable_source_is_left_out_not_zero(self):
        full = compute_score(_typical())
        without = compute_score(_typical(evictions=None))
        self.assertTrue(without.available)
        self.assertEqual(without.unavailable_factors, ["evictions"])
        self.assertIsNone(without.percentiles["evictions"])
        # A zero would have pulled the score up; leaving it out keeps it near the full score.
        zeroed = compute_score(_typical(evictions=0))
        self.assertLessEqual(abs(without.score - full.score), abs(zeroed.score - full.score) + 1)

    def test_high_crime_caps_the_score(self):
        quiet = {
            "reports_311": _q("reports_311_total", 0.05),
            "permits": _q("permits_total", 0.05),
            "evictions": _q("evictions_total", 0.05),
        }
        counts = _typical(crime=_q("crime_total", 0.65), **quiet)
        result = compute_score(counts)
        self.assertGreater(result.base_score, 38)
        self.assertEqual(result.score, 38)
        self.assertEqual(result.caps_applied, ["crime"])
        description, _ = build_risk_description(counts, result)
        self.assertIn(
            "Capped at 38: a higher score needs NYPD complaints in the lowest 57% of NYC apartment locations.",
            description,
        )

    def test_unavailable_note_keeps_acronyms(self):
        counts = _typical(permits=None)
        description, _ = build_risk_description(counts, compute_score(counts))
        self.assertIn("DOB permits unavailable — scored on the other sources.", description)

    def test_not_scored_banner(self):
        risk = compute_risk_from_counts(ScanCounts())
        self.assertFalse(risk["score_available"])
        self.assertEqual(risk["risk_label"], "Not scored")
        self.assertIsNone(risk["banner_driver"])


class SeverityTests(unittest.TestCase):
    def test_fixed_tiers(self):
        ctx = CardChromeContext()
        self.assertEqual(card_severity("tenant_warnings", ctx), "not_checked")
        self.assertEqual(card_severity("oven_effect", ctx), "tip")

    def test_missing_data_is_unavailable_not_quiet(self):
        self.assertEqual(card_severity("high_churn", CardChromeContext()), "unavailable")

    def test_card_with_one_source_missing_is_unavailable(self):
        construction = _q("reports_311_construction", 0.95)
        both = ScanCounts(permits=_q("permits_total", 0.1), reports_311_construction=construction)
        self.assertEqual(card_severity("demolitions", CardChromeContext(counts=both)), "elevated")
        permits_missing = ScanCounts(permits=None, reports_311_construction=construction)
        self.assertEqual(card_severity("demolitions", CardChromeContext(counts=permits_missing)), "unavailable")

    def test_percentile_tiers(self):
        for q, tier in ((0.1, "quiet"), (0.5, "watch"), (0.95, "elevated")):
            ctx = CardChromeContext(counts=ScanCounts(evictions=_q("evictions_total", q)))
            self.assertEqual(card_severity("high_churn", ctx), tier, q)

    def test_flight_card_uses_its_highest_percentile(self):
        fx = FlightExposure(
            night_overflights_per_hour=4.3, day_overflights_per_hour=24.1, data_quality="good",
            show_flight_feature=True, night_percentile=0.617, day_percentile=0.8, combined_percentile=0.694,
        )
        p = _flight_card_percentile(fx)
        self.assertEqual(p, 0.8)
        ctx = CardChromeContext(flight_percentile=p, show_flight_feature=True)
        self.assertEqual(card_severity("flight_path", ctx), "elevated")


class CardBulletTests(unittest.TestCase):
    def test_keeps_takeaway_and_drops_blanks(self):
        cards = cards_from_specs_and_bullets({"high_churn": ["a", "", None, "b", "c", "takeaway", "extra"]})
        churn = next(c for c in cards if c["id"] == "high_churn")
        self.assertEqual(churn["bullets"], ["a", "b", "c", "takeaway"])

    def test_bottom_line_filter(self):
        self.assertEqual(
            _accept_bottom_line("Ask the landlord how long the scaffolding will stay up."),
            "Ask the landlord how long the scaffolding will stay up.",
        )
        self.assertIsNotNone(_accept_bottom_line("Visit on a weeknight evening to hear the block."))
        for bad in (
            "Over 300 complaints were filed nearby.",
            "Quieter than most of NYC.",
            "Above average noise for the city.",
            "Expect fewer residential evictions in this area.",
            "Walk around the block at different times in NYPD's latest data.",
            "Ask about noise complaints filed recently.",
            "<b>Visit at night</b>",
            "x" * 121,
            None,
        ):
            self.assertIsNone(_accept_bottom_line(bad), bad)


class FlightPassTests(unittest.TestCase):
    T0 = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)  # 12:00 New York

    def _rows(self, icao: str, minutes: list[int]) -> list[dict]:
        return [{"icao24": icao, "observed_at": (self.T0 + timedelta(minutes=m)).isoformat()} for m in minutes]

    def test_circling_helicopter_is_one_pass(self):
        self.assertEqual(len(count_passes(self._rows("abc123", list(range(30))))), 1)

    def test_gap_over_ten_minutes_starts_a_new_pass(self):
        self.assertEqual(len(count_passes(self._rows("abc123", [0, 1, 2, 20, 21]))), 2)
        self.assertEqual(len(count_passes(self._rows("abc123", [0, 10]))), 1)

    def test_aircraft_counted_separately(self):
        rows = self._rows("abc123", [0, 1]) + self._rows("def456", [0, 1])
        self.assertEqual(len(count_passes(rows)), 2)

    def test_rates_split_by_new_york_night(self):
        noon = datetime(2026, 9, 30, 12, tzinfo=NYC).astimezone(timezone.utc)
        late = datetime(2026, 9, 30, 23, tzinfo=NYC).astimezone(timezone.utc)
        rows = self._rows("abc123", [0, 1]) + [
            {"icao24": "def456", "observed_at": (late + timedelta(minutes=5)).isoformat()},
        ]
        rates = pass_rates(rows, {noon, late})
        self.assertEqual((rates.day_passes, rates.night_passes), (1, 1))
        self.assertEqual((rates.day_hours, rates.night_hours), (1, 1))
        self.assertEqual((rates.day_per_hr, rates.night_per_hr), (1.0, 1.0))


class FlightReadLimitTests(unittest.TestCase):
    """A slow or failing read of stored positions must not hold up a scan or be repeated."""

    COORD = Coordinate(lat=40.7584, lng=-73.9922)

    def setUp(self):
        self._paused = flight_exposure._paused_until
        flight_exposure._paused_until = 0.0
        flight_exposure._window_cache.clear()

    def tearDown(self):
        flight_exposure._paused_until = self._paused
        flight_exposure._window_cache.clear()

    def test_slice_stops_when_the_time_budget_is_spent(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        args = (start, start + timedelta(hours=6), (40.7, 40.8, -74.0, -73.9), time.monotonic() - 1, threading.Event())
        with mock.patch.object(flight_exposure, "thread_client") as client:
            with self.assertRaises(TimeoutError):
                flight_exposure._fetch_slice(args)
        client.assert_not_called()

    def test_slice_stops_when_another_slice_failed(self):
        start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        stop = threading.Event()
        stop.set()
        args = (start, start + timedelta(hours=6), (40.7, 40.8, -74.0, -73.9), time.monotonic() + 60, stop)
        with mock.patch.object(flight_exposure, "thread_client") as client:
            with self.assertRaises(TimeoutError):
                flight_exposure._fetch_slice(args)
        client.assert_not_called()

    def test_nothing_is_read_while_flight_noise_is_paused(self):
        with mock.patch.object(flight_exposure, "FLIGHT_NOISE_PAUSED", True), \
                mock.patch.object(flight_exposure, "load_adsb_window") as load:
            fx = flight_exposure.compute_exposure(self.COORD)
            self.assertEqual((fx.data_quality, fx.show_flight_feature, fx.elevation_level),
                             ("unavailable", False, "unavailable"))
            self.assertEqual(flight_exposure.fetch_raw_adsb_samples(self.COORD), [])
        load.assert_not_called()

    def test_flight_pause_matches_the_site_and_the_baselines(self):
        # The website has its own switch for the flight copy: both must say the same thing.
        site_ts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "frontend", "lib", "site.ts")
        if os.path.exists(site_ts):
            with open(site_ts, encoding="utf-8") as fh:
                found = re.search(r"export const FLIGHT_NOISE_PAUSED = (true|false);", fh.read())
            self.assertIsNotNone(found, "FLIGHT_NOISE_PAUSED missing from frontend/lib/site.ts")
            self.assertEqual(found.group(1) == "true", flight_exposure.FLIGHT_NOISE_PAUSED)
        # Turning flights back on needs flight baselines measured at the collector's current rate.
        if not flight_exposure.FLIGHT_NOISE_PAUSED:
            for metric in ("flight_night_passes_per_hr", "flight_day_passes_per_hr"):
                self.assertIsNotNone(nyc_baselines.get(metric), metric)

    def test_failed_read_is_unavailable_and_not_repeated(self):
        with mock.patch.object(flight_exposure, "FLIGHT_NOISE_PAUSED", False), \
                mock.patch.object(flight_exposure, "_get_client"), \
                mock.patch.object(flight_exposure, "_fetch_slice", side_effect=RuntimeError("down")) as fetch:
            with self.assertLogs("services.flight_exposure", level="ERROR"):
                self.assertIsNone(flight_exposure.load_adsb_window(self.COORD))
            calls = fetch.call_count
            self.assertGreaterEqual(calls, 1)
            self.assertTrue(flight_exposure.reads_paused())
            # The scan asks twice more; neither starts another read.
            self.assertIsNone(flight_exposure.load_adsb_window(self.COORD))
            self.assertEqual(flight_exposure.compute_exposure(self.COORD).data_quality, "unavailable")
            self.assertEqual(flight_exposure.fetch_raw_adsb_samples(self.COORD), [])
            self.assertEqual(fetch.call_count, calls)

    def test_scan_gives_up_on_a_hung_flight_read(self):
        async def hung():
            await asyncio.sleep(5)
            return "late"

        started = time.monotonic()
        with mock.patch.object(scan_router, "FLIGHT_READ_TIME_LIMIT_SECONDS", 0.05):
            with self.assertLogs("routers.scan", level="WARNING"):
                result = asyncio.run(scan_router._flight_read(hung(), "fallback", "test read"))
        self.assertEqual(result, "fallback")
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertTrue(flight_exposure.reads_paused())

    def test_unavailable_exposure_shows_nothing(self):
        fx = flight_exposure.unavailable_exposure()
        self.assertEqual((fx.data_quality, fx.show_flight_feature, fx.sample_count), ("unavailable", False, 0))

    def test_source_list_marks_flights_unavailable_without_a_comparison(self):
        until = datetime(2026, 11, 20, 10, tzinfo=timezone.utc)
        window = flight_exposure.AdsbWindow(
            rows=[{"observed_at": "2026-11-19T12:00:00+00:00"}], since=until - timedelta(days=7), until=until,
            days=7, radius_miles=2.0, covered={until - timedelta(hours=1)},
        )
        measured = dict(night_overflights_per_hour=1.0, day_overflights_per_hour=5.0, data_quality="good")
        # Positions were read but there is no NYC flight baseline: the report has no flight section.
        paused = scan_router._flight_source(window, FlightExposure(**measured, elevation_level="unavailable"))
        self.assertEqual((paused.status, paused.count, paused.window_start), ("unavailable", None, None))
        compared = scan_router._flight_source(window, FlightExposure(**measured, elevation_level="typical"))
        self.assertEqual((compared.status, compared.count), ("ok", 1))
        self.assertEqual(scan_router._flight_source(None, None).status, "unavailable")


class Construction311Tests(unittest.TestCase):
    """'311 construction complaints' must be construction, not every row that mentions a building."""

    @staticmethod
    def _row(complaint_type: str, descriptor: str = "") -> dict:
        return {"complaint_type": complaint_type, "descriptor": descriptor}

    def test_heat_and_tree_complaints_are_not_construction(self):
        for ctype, desc in (
            ("HEAT/HOT WATER", "ENTIRE BUILDING"),
            ("Overgrown Tree/Branches", "Hitting Building"),
            ("Building/Use", "Illegal Conversion Of Residential Building/Space"),
            ("Special Projects Inspection Team (SPIT)", "Illegal Hotel Rooms In Residential Building"),
        ):
            self.assertFalse(city_data.is_311_construction(self._row(ctype, desc)), (ctype, desc))

    def test_construction_complaints_are_counted(self):
        for ctype, desc in (
            ("Noise", "Noise: Construction Before/After Hours (NM1)"),
            ("General Construction/Plumbing", "Building Permit - None"),
            ("Street Condition", "Blocked - Construction"),
            ("Air Quality", "Dust from Construction"),
            ("Scaffold Safety", ""),
            ("Cranes and Derricks", ""),
            ("Construction Safety Enforcement", "Demolition - Unsafe"),
        ):
            self.assertTrue(city_data.is_311_construction(self._row(ctype, desc)), (ctype, desc))

    def test_group_summary_leaves_heat_out_of_construction(self):
        total, breakdown, _, _ = city_data._summarize_311_groups([
            ("HEAT/HOT WATER", "ENTIRE BUILDING", 700),
            ("Noise", "Noise: Construction Before/After Hours (NM1)", 30),
            ("General Construction/Plumbing", "Building Permit - None", 12),
            ("Illegal Parking", "Blocked Hydrant", 99),
        ])
        self.assertEqual(total, 742)  # parking is excluded from the total
        self.assertEqual(breakdown["construction"], 42)
        self.assertEqual(breakdown["noise"], 30)

    def test_source_link_filter_matches_the_count(self):
        soql = city_data.soql_311_construction()
        self.assertNotIn("BUILDING", soql)
        for word in ("CONSTRUCTION", "SCAFFOLD", "DEMOLITION", "CRANE"):
            self.assertIn(f"upper(complaint_type) like '%{word}%'", soql)
            self.assertIn(f"upper(descriptor) like '%{word}%'", soql)

    def test_map_pins_do_not_file_building_use_or_heat_under_construction(self):
        # Pins are filed by complaint type only (a construction-noise complaint stays a noise pin).
        self.assertEqual(city_data._classify_311(self._row("General Construction/Plumbing"))[0], "construction")
        self.assertEqual(city_data._classify_311(self._row("Building/Use"))[0], "report")
        self.assertEqual(city_data._classify_311(self._row("HEAT/HOT WATER", "ENTIRE BUILDING"))[0], "fire")

    def test_map_pin_words_match_whole_words(self):
        self.assertEqual(city_data._classify_311(self._row("Rodent", "Rat Sighting"))[0], "rat")
        self.assertEqual(city_data._classify_311(self._row("Special Operations"))[0], "report")
        self.assertEqual(city_data._classify_311(self._row("Literature Request"))[0], "report")
        self.assertEqual(city_data._classify_311(self._row("PAINT/PLASTER", "CEILING"))[0], "report")
        self.assertEqual(city_data._classify_311(self._row("Graffiti"))[0], "graffiti")


class SourceLinkTests(unittest.TestCase):
    def test_scan_links_are_capped_and_the_cap_is_public(self):
        # pdf_dossier prints this cap next to every scan-scope link.
        self.assertEqual(source_links.BROWSE_LIMIT, 200)
        urls = source_links.card_dataset_urls(
            "reports_311", Coordinate(lat=40.7584, lng=-73.9922), radius_miles=2.0,
            windows={"311": (date(2026, 10, 22), date(2026, 11, 20))},
        )
        self.assertTrue(urls)
        self.assertIn(f"LIMIT%20{source_links.BROWSE_LIMIT}", urls[0][1])

    def test_eviction_id_includes_execution_date(self):
        self.assertEqual(
            source_links._id_clause("evictions", "0328034/24:039654:2026-05-18"),
            "(court_index_number='0328034/24' AND docket_number='039654' "
            "AND executed_date='2026-05-18T00:00:00')",
        )

    def test_ids_are_quoted_and_escaped(self):
        self.assertEqual(source_links._id_clause("crime", "12'3"), "cmplnt_num='12''3'")
        self.assertEqual(source_links._id_clause("permits", "BIS:456"), "permit_si_no='456'")

    def test_permit_ids_route_to_their_dataset(self):
        self.assertEqual(source_links.record_dataset_key("permits", "NOW:B001-I1"), "permits_now")
        self.assertEqual(source_links.record_dataset_key("permits_now", "BIS:123"), "permits")

    def test_record_url_opens_filtered_explorer(self):
        url = source_links.record_url("311", "65000001")
        self.assertTrue(url.startswith("https://data.cityofnewyork.us/"))
        self.assertIn("/explore/query/", url)
        self.assertIn("65000001", url)

    def test_adsb_links(self):
        self.assertEqual(source_links.adsb_aircraft_url("A1B2C3"), "https://adsb.lol/?icao=a1b2c3")
        self.assertIsNone(source_links.adsb_aircraft_url("not-hex"))

    def test_hpd_link_needs_a_building(self):
        url = source_links.hpd_violations_url("350 West 42nd Street, New York, New York 10036, United States")
        self.assertIn("/wvxf-dwi5/explore/query/", url)
        self.assertIn("housenumber%3D%27350%27", url)
        self.assertIsNone(source_links.hpd_violations_url("Union Square, New York, New York 10003, United States"))


class GeocodeScopeTests(unittest.TestCase):
    @staticmethod
    def _feature(district: str, region: str) -> dict:
        return {"context": [
            {"id": "postcode.1", "text": "00000"},
            {"id": "district.2", "text": district},
            {"id": "region.3", "short_code": region, "text": "New York"},
        ]}

    def test_five_boroughs_accepted(self):
        for county in ("New York County", "Kings County", "Queens County", "Bronx County", "Richmond County"):
            self.assertEqual(nyc_county(self._feature(county, "US-NY")), county)

    def test_outside_nyc_rejected(self):
        self.assertIsNone(nyc_county(self._feature("Nassau County", "US-NY")))
        self.assertIsNone(nyc_county(self._feature("Onondaga County", "US-NY")))
        self.assertIsNone(nyc_county(self._feature("Hudson County", "US-NJ")))
        self.assertIsNone(nyc_county({"context": []}))


class BisPermitListTests(unittest.TestCase):
    CENTER = Coordinate(lat=40.7584, lng=-73.9922)
    TODAY = date(2026, 10, 2)
    START = date(2026, 7, 5)

    def setUp(self):
        self._saved = (city_data._bis_snapshot, city_data._bis_loading, city_data.BIS_SNAPSHOT_WAIT_SECONDS)

    def tearDown(self):
        city_data._bis_snapshot, city_data._bis_loading, city_data.BIS_SNAPSHOT_WAIT_SECONDS = self._saved

    @staticmethod
    def _row(si, lat, issued="09/01/2026", expires="03/01/2027", ptype="DM"):
        return {"permit_si_no": si, "permit_type": ptype, "permit_subtype": "", "job_type": "DM",
                "issuance_date": issued, "expiration_date": expires,
                "gis_latitude": str(lat), "gis_longitude": "-73.9922"}

    def _load(self, raw):
        rows = [p for p in (city_data._parse_bis_row(r) for r in raw) if p]
        city_data._bis_snapshot = city_data._BisSnapshot(loaded_at=time.monotonic(), rows=rows)

    def test_parse_rejects_unusable_rows(self):
        self.assertIsNotNone(city_data._parse_bis_row(self._row("1", 40.76)))
        self.assertIsNone(city_data._parse_bis_row(self._row("2", "")))
        self.assertIsNone(city_data._parse_bis_row(self._row("3", 40.76, issued="")))
        self.assertIsNone(city_data._parse_bis_row(self._row("4", 40.76, ptype="PL")))

    def test_filters_by_distance_and_window_newest_first(self):
        self._load([
            self._row("1", 40.7600, issued="08/01/2026"),
            self._row("2", 40.7700, issued="09/15/2026"),
            self._row("3", 40.8100),                        # ~3.6 mi north
            self._row("4", 40.7600, issued="07/04/2026"),   # issued before the window
            self._row("5", 40.7600, expires="10/01/2026"),  # expired
        ])
        near = city_data.bis_permits_near(self.CENTER, self.START, self.TODAY, radius_miles=2.0)
        self.assertEqual([r["permit_si_no"] for r in near], ["2", "1"])

    def test_unavailable_when_list_cannot_load(self):
        city_data._bis_snapshot, city_data._bis_loading = None, None
        city_data.BIS_SNAPSHOT_WAIT_SECONDS = 5.0
        with mock.patch.object(city_data.socrata, "query_all", side_effect=SocrataError("down")):
            with self.assertRaises(SocrataError):
                city_data.bis_permits_near(self.CENTER, self.START, self.TODAY)
        self.assertIsNone(city_data._bis_loading)

    def test_stale_list_is_not_used(self):
        self._load([self._row("1", 40.76)])
        city_data._bis_snapshot.loaded_at -= city_data.BIS_SNAPSHOT_MAX_AGE_SECONDS + 1
        self.assertIsNone(city_data._fresh_bis_rows())

    def test_failed_newest_date_lookup_leaves_date_blank(self):
        with mock.patch.object(city_data.socrata, "latest_date", side_effect=SocrataError("HTTP 429")):
            with self.assertLogs("services.city_data", level="WARNING"):
                self.assertIsNone(city_data._display_latest(city_data.PERMITS_BIS_DATASET, "dobrundate"))

    def test_wait_for_list_stops_at_the_scan_time_limit(self):
        city_data._bis_snapshot, city_data._bis_loading = None, threading.Event()  # a load already running
        city_data.BIS_SNAPSHOT_WAIT_SECONDS = 30.0
        started = time.monotonic()
        with socrata.time_limit(0.1):
            with self.assertRaises(SocrataError):
                city_data.bis_permits_near(self.CENTER, self.START, self.TODAY)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_citywide_load_ignores_the_scan_time_limit(self):
        city_data._bis_snapshot, city_data._bis_loading = None, None
        limits_seen = []

        def fake_query_all(*args, **kwargs):
            limits_seen.append(socrata.time_left())
            return [self._row("1", 40.76)], False

        with mock.patch.object(city_data.socrata, "query_all", side_effect=fake_query_all):
            with socrata.time_limit(5.0):
                near = city_data.bis_permits_near(self.CENTER, self.START, self.TODAY)
        self.assertEqual(limits_seen, [None])
        self.assertEqual([r["permit_si_no"] for r in near], ["1"])


class TimeLimitTests(unittest.TestCase):
    def test_request_gives_up_at_the_limit(self):
        with mock.patch.object(socrata.requests, "get", side_effect=requests.Timeout("slow")) as get:
            started = time.monotonic()
            with socrata.time_limit(0.2):
                with self.assertRaises(SocrataError):
                    socrata.query("erm2-nwe9", {"$limit": 1})
        self.assertLess(time.monotonic() - started, 1.0)  # retries alone would wait 4.5 s
        self.assertLessEqual(get.call_args.kwargs["timeout"], 0.2)

    def test_no_limit_outside_a_scan(self):
        self.assertIsNone(socrata.time_left())

    def test_limit_reaches_worker_threads(self):
        async def feed():
            left = await asyncio.to_thread(socrata.time_left)
            return city_data.FeedResult(key="crime", label="NYPD complaints", status="ok", total=0,
                                        extra={"left": left})

        result = asyncio.run(city_data.with_time_limit("crime", feed(), 5.0))
        self.assertTrue(0 < result.extra["left"] <= 5.0)
        self.assertIsNone(socrata.time_left())

    def test_slow_feed_is_unavailable(self):
        async def stuck_feed():
            await asyncio.sleep(5)
            return city_data.FeedResult(key="311", label="311 service requests", status="ok", total=1)

        started = time.monotonic()
        with mock.patch.object(city_data, "_TIME_LIMIT_GRACE_SECONDS", 0.05):
            feed = asyncio.run(city_data.with_time_limit("311", stuck_feed(), 0.1))
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(feed.available)
        self.assertEqual((feed.label, feed.note), ("311 service requests", "NYC Open Data did not respond."))
        self.assertEqual(feed.dataset_ids, (city_data.REPORTS_311_DATASET,))


class LogPrivacyTests(unittest.TestCase):
    """Error text that reaches the logs leaves out the scanned location (the privacy page promises it)."""

    COORD = Coordinate(lat=40.757966, lng=-73.992263)

    def assertNoLocation(self, text: str) -> None:
        self.assertNotIn("40.7", text)
        self.assertNotIn("73.9", text)
        self.assertIsNone(re.search(r"\d\.\d{4}", text), text)

    def _query_error(self, params: dict, **get_mock) -> str:
        with mock.patch.object(socrata.requests, "get", **get_mock), mock.patch.object(socrata, "_pause"):
            with self.assertRaises(SocrataError) as caught:
                socrata.query("5uac-w243", params)
        return str(caught.exception)

    def test_socrata_connection_error_hides_the_request_url_coordinates(self):
        def refuse(url, params=None, **kwargs):
            path = requests.Request("GET", url, params=params).prepare().path_url
            raise requests.ConnectionError(
                f"HTTPSConnectionPool(host='data.cityofnewyork.us', port=443): Max retries exceeded with url: {path}"
            )

        for where in (
            socrata.within_circle("lat_lon", self.COORD, 2.0),
            socrata.numeric_circle("latitude", "longitude", self.COORD, 2.0),
        ):
            message = self._query_error({"$where": where}, side_effect=refuse)
            self.assertIn("ConnectionError", message)
            self.assertNoLocation(message)

    def test_socrata_error_body_hides_echoed_coordinates(self):
        where = socrata.within_circle("lat_lon", self.COORD, 2.0)
        for body in (
            json.dumps({"message": f'Could not parse SoQL query "SELECT * WHERE {where}"', "errorCode": "query.compiler.malformed"}),
            "x" * 196 + where[len("within_circle(lat_lon, "):],  # a coordinate cut by the 200-character limit
        ):
            resp = mock.Mock(ok=False, status_code=400, text=body, headers={})
            message = self._query_error({"$where": where}, return_value=resp)
            self.assertIn("HTTP 400", message)
            self.assertNoLocation(message)

    def test_yelp_failure_logs_no_coordinates(self):
        url = requests.Request(
            "GET", places.YELP_BUSINESS_SEARCH_URL, params={"latitude": self.COORD.lat, "longitude": self.COORD.lng}
        ).prepare().url
        failures = (
            (requests.HTTPError(f"400 Client Error: Bad Request for url: {url}", response=mock.Mock(status_code=400)), "HTTP 400"),
            (requests.ConnectionError(f"Max retries exceeded with url: {url}"), "ConnectionError"),
        )
        for failure, shown in failures:
            with mock.patch.object(places.requests, "get", side_effect=failure):
                with self.assertLogs("services.places", level="WARNING") as logs:
                    self.assertEqual(places._get_top_restaurants_bars_yelp(self.COORD, "key", limit=4), [])
            self.assertIn(shown, logs.output[0])
            self.assertNoLocation("\n".join(logs.output))

    def test_gemini_parse_error_leaves_out_the_reply(self):
        with self.assertRaises(ValueError) as caught:
            _parse_ai_json('{"bottom_lines": {"high_churn": "Ask the super at 350 Fifth Avenue about')
        self.assertNotIn("Fifth Avenue", str(caught.exception))
        self.assertEqual(_classify_gemini_error(caught.exception)[0], "json_parse")


class FormatTests(unittest.TestCase):
    def test_distance_display(self):
        self.assertEqual(_miles_to_display(0.1), (528, "feet"))
        self.assertEqual(_miles_to_display(0.4693), (0.5, "miles"))

    def test_pdf_distance_text(self):
        self.assertEqual(_distance_text({"distance_value": 850, "distance_unit": "feet"}), "850 ft")
        self.assertEqual(_distance_text({"distance_value": 0.5, "distance_unit": "miles"}), "0.5 mi")
        self.assertEqual(_distance_text({}), "-")

    def test_pdf_record_dates(self):
        self.assertEqual(_display_date("2026-09-29T00:00:00.000"), "Sep 29, 2026")
        self.assertEqual(_display_date("2026-10-02T02:02:47.000"), "Oct 2, 2026 2:02 AM")
        self.assertEqual(_display_date("2026-10-02T14:30:00"), "Oct 2, 2026 2:30 PM")
        self.assertEqual(_display_date("2026-09-30"), "Sep 30, 2026")
        self.assertEqual(_display_date(None), "")
        self.assertEqual(_display_date("not a date"), "not a date")


if __name__ == "__main__":
    unittest.main()
