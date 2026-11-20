"""Institutional-grade PDF dossier — earnings-report layout with source deep links."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

from fpdf import FPDF

from models.schemas import Coordinate
from services import city_data, flight_exposure, source_links
from services.dossier_context import DossierContext
from services.threat_card_layout import label_band_rows

PDF_311_MAX = 200
PDF_CARD_RECORDS_MAX = 50

RISK_COLORS = {
    "EXTREME": (180, 40, 40),
    "HIGH": (180, 90, 20),
    "MODERATE": (140, 110, 20),
    "LOW": (30, 100, 60),
}

SEVERITY_LABELS = {
    "quiet": "Lower than most of NYC",
    "watch": "About typical for NYC",
    "elevated": "Higher than most of NYC",
    "unavailable": "Unavailable",
    "not_checked": "Not checked",
    "tip": "Tip",
}

_DRIVER_NAMES = {
    "area_safety": "NYPD complaints",
    "311": "311 requests",
    "permits": "Active construction permits",
    "evictions": "Residential evictions",
    "noise": "Noise complaints",
}

# Feeds behind each card (a card is unavailable when any of these didn't answer).
_CARD_FEEDS: dict[str, tuple[str, ...]] = {
    "high_churn": ("evictions",),
    "police_calls": ("police_calls",),
    "area_safety": ("crime",),
    "demolitions": ("permits", "311"),
    "noise_schedule": ("311",),
    "reports_311": ("311",),
}

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\u2600-\u27BF"
    "\uFE0F"
    "]+",
    flags=re.UNICODE,
)

_ASCII_REPLACEMENTS = str.maketrans({
    "\u2014": "-",
    "\u2013": "-",
    "\u2022": "*",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u00a9": "(c)",
    "\u00ae": "(R)",
})

# Institutional palette (navy / warm gray / gold accent)
_NAVY = (0, 45, 114)
_GOLD = (168, 139, 70)
_INK = (33, 33, 33)
_BODY = (68, 68, 68)
_MUTED = (120, 120, 120)
_RULE = (190, 190, 190)
_RULE_LIGHT = (220, 220, 220)
_WHITE = (255, 255, 255)
_LINK = (0, 45, 114)
_WATERMARK = (230, 230, 230)

_LINK_DISPLAY = {
    "Source": "View source record",
    "Browse all": "Browse records near this address",
    "Dataset": "View filtered records near this address",
    "Listing": "Open business listing",
    "HPD": "HPD violations for this address",
}

# Layout — generous margins like formal filings
_MARGIN_L = 20
_MARGIN_R = 20
_MARGIN_T = 22
_MARGIN_B = 18
_CONTENT_W = 210 - _MARGIN_L - _MARGIN_R
_PAGE_BOTTOM = 297 - _MARGIN_B - 8


def pdf_text(value: object, *, default: str = "", max_len: int = 0) -> str:
    if value is None:
        return default
    text = str(value)
    text = _EMOJI_RE.sub("", text)
    text = text.translate(_ASCII_REPLACEMENTS)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("latin-1", errors="ignore").decode("latin-1")
    text = text.strip() or default
    if max_len > 0 and len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _parse_hex_color(hex_color: str) -> tuple[int, int, int]:
    raw = (hex_color or "#787878").strip().lstrip("#")
    if len(raw) >= 6 and all(c in "0123456789abcdefABCDEF" for c in raw[:6]):
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    return 120, 120, 120


def _coord(ctx: DossierContext) -> Coordinate:
    return Coordinate(lat=ctx.coord_lat, lng=ctx.coord_lng)


def _iso_date(raw: object) -> date | None:
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None


def _feed(ctx: DossierContext, key: str) -> dict:
    return ctx.feeds.get(key) or {}


def _feed_ok(ctx: DossierContext, key: str) -> bool:
    return _feed(ctx, key).get("status") == "ok"


def _feed_window_text(ctx: DossierContext, key: str) -> str:
    f = _feed(ctx, key)
    return city_data.format_window(_iso_date(f.get("window_start")), _iso_date(f.get("window_end")))


def _feed_windows(ctx: DossierContext) -> dict[str, tuple[date, date]]:
    out: dict[str, tuple[date, date]] = {}
    for key, f in ctx.feeds.items():
        start, end = _iso_date(f.get("window_start")), _iso_date(f.get("window_end"))
        if f.get("status") == "ok" and start and end:
            out[key] = (start, end)
    return out


def _source_line(src: dict) -> str:
    if src.get("status") != "ok":
        return "Unavailable during this scan"
    parts = []
    if src.get("count") is not None:
        parts.append(f"{int(src['count']):,}")
    window = city_data.format_window(_iso_date(src.get("window_start")), _iso_date(src.get("window_end")))
    if window:
        parts.append(window)
    as_of = _iso_date(src.get("as_of"))
    if as_of:
        parts.append(f"data as of {as_of:%b} {as_of.day}, {as_of.year}")
    if src.get("provider"):
        parts.append(str(src["provider"]))
    return " | ".join(parts)


# ── Typography helpers ────────────────────────────────────────────────────────

def _font_sans(pdf: FPDF, style: str = "", size: int = 9) -> None:
    pdf.set_font("Helvetica", style, size)


def _font_serif(pdf: FPDF, style: str = "", size: int = 10) -> None:
    pdf.set_font("Times", style, size)


def _count_lines(pdf: FPDF, width: float, text: str, *, line_h: float = 4) -> int:
    if not text:
        return 0
    lines = pdf.multi_cell(width, line_h, pdf_text(text), split_only=True)
    return max(1, len(lines))


def _text_height(
    pdf: FPDF, width: float, text: str, *, line_h: float = 4,
    family: str = "sans", style: str = "", size: int = 9,
) -> float:
    if family == "serif":
        _font_serif(pdf, style, size)
    else:
        _font_sans(pdf, style, size)
    return _count_lines(pdf, width, text, line_h=line_h) * line_h


def _hrule(pdf: FPDF, *, y: float | None = None, color: tuple[int, int, int] = _RULE) -> None:
    y = pdf.get_y() if y is None else y
    pdf.set_draw_color(*color)
    pdf.set_line_width(0.2)
    pdf.line(_MARGIN_L, y, _MARGIN_L + _CONTENT_W, y)
    pdf.set_line_width(0.2)


def _ensure_space(pdf: FPDF, needed: float) -> None:
    if pdf.get_y() + needed > _PAGE_BOTTOM:
        pdf.add_page()


# A table heading plus the table header and its first row, so a heading never ends a page.
_HEADING_WITH_TABLE_MM = 30


# ── PDF document class ────────────────────────────────────────────────────────

class DossierPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self._running_section = ""
        self._property_label = ""

    def header(self) -> None:
        if self.page_no() <= 1:
            return
        self.set_y(10)
        _font_sans(self, "B", 7)
        self.set_text_color(*_NAVY)
        self.set_x(_MARGIN_L)
        self.cell(50, 4, "ZERMAP", ln=False)
        _font_sans(self, "", 7)
        self.set_text_color(*_MUTED)
        self.cell(80, 4, "Full Data Report", ln=False, align="C")
        if self._running_section:
            self.cell(0, 4, pdf_text(self._running_section, max_len=50), ln=True, align="R")
        else:
            self.ln(4)
        _hrule(self, y=16, color=_RULE_LIGHT)
        self.set_y(_MARGIN_T)

    def footer(self) -> None:
        self.set_y(-14)
        _hrule(self, color=_RULE_LIGHT)
        self.set_y(-11)
        _font_sans(self, "", 6.5)
        self.set_text_color(*_MUTED)
        self.set_x(_MARGIN_L)
        self.cell(90, 3, pdf_text(self._property_label, max_len=60), ln=False)
        self.cell(0, 3, f"Page {self.page_no()}/{{nb}}", align="R")

    def set_section(self, name: str) -> None:
        self._running_section = name


# ── Cover page ────────────────────────────────────────────────────────────────

def _render_cover(pdf: DossierPDF, address: str) -> None:
    pdf._property_label = pdf_text(address, max_len=80)
    # Gold accent rule at top
    pdf.set_fill_color(*_GOLD)
    pdf.rect(0, 0, 210, 1.2, "F")
    # Navy band
    pdf.set_fill_color(*_NAVY)
    pdf.rect(0, 1.2, 210, 52, "F")
    pdf.set_text_color(*_WHITE)
    _font_sans(pdf, "B", 9)
    pdf.set_xy(_MARGIN_L, 14)
    pdf.cell(0, 4, "ZERMAP", ln=True)
    _font_sans(pdf, "B", 26)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 12, "Full Data Report", ln=True)
    _font_sans(pdf, "", 10)
    pdf.set_text_color(200, 210, 225)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 5, "Neighborhood Intelligence & Municipal Data Dossier", ln=True)
    pdf.set_y(68)

    # Property block
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 4, "SUBJECT PROPERTY", ln=True)
    pdf.ln(2)
    _font_serif(pdf, "B", 14)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 6.5, pdf_text(address))
    pdf.ln(6)

    _hrule(pdf)
    pdf.ln(6)
    generated = datetime.now().strftime("%B %d, %Y")
    _font_sans(pdf, "", 8)
    pdf.set_text_color(*_BODY)
    for label, value in [
        ("Report Date", generated),
        ("Report Type", "Full raw-data disclosure"),
        # Aircraft positions are named only when the report can use them.
        ("Data Sources", "NYC Open Data, Yelp/Google Places"
                         + ("" if flight_exposure.FLIGHT_NOISE_PAUSED else ", ADS-B ingest")),
    ]:
        pdf.set_x(_MARGIN_L)
        _font_sans(pdf, "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.cell(32, 4.5, label, ln=False)
        _font_serif(pdf, "", 9)
        pdf.set_text_color(*_INK)
        pdf.cell(0, 4.5, pdf_text(value), ln=True)

    # Bottom disclaimer
    disc = (
        "This report aggregates publicly available municipal and third-party data for informational purposes only. "
        "It does not constitute legal, financial, or real-estate advice. Verify all figures at source before making decisions."
    )
    disc_h = _text_height(pdf, _CONTENT_W, disc, line_h=4, family="serif", size=8)
    pdf.set_y(260 - disc_h)
    _hrule(pdf)
    pdf.ln(4)
    _font_serif(pdf, "I", 8)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 4, disc)


# ── Section layout (earnings-report style) ────────────────────────────────────

def _section_opener(pdf: DossierPDF, number: int, title: str, *, subtitle: str = "") -> None:
    pdf.set_section(title)
    pdf.ln(4)
    _ensure_space(pdf, 28)
    y0 = pdf.get_y()
    # Watermark numeral
    _font_sans(pdf, "B", 42)
    pdf.set_text_color(*_WATERMARK)
    pdf.set_xy(_MARGIN_L + _CONTENT_W - 38, y0 - 2)
    pdf.cell(38, 16, f"{number:02d}", align="R")
    # Title
    pdf.set_xy(_MARGIN_L, y0)
    _font_sans(pdf, "B", 16)
    pdf.set_text_color(*_NAVY)
    pdf.cell(0, 8, pdf_text(title), ln=True)
    if subtitle:
        pdf.set_x(_MARGIN_L)
        _font_serif(pdf, "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(_CONTENT_W - 40, 4.5, pdf_text(subtitle))
    pdf.ln(2)
    _hrule(pdf, color=_GOLD)
    pdf.set_draw_color(*_RULE)
    pdf.ln(8)


def _subsection(pdf: DossierPDF, number: str, title: str) -> None:
    pdf.ln(5)
    _ensure_space(pdf, 12)
    _font_sans(pdf, "B", 10)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    if number and number != "-":
        heading = pdf_text(f"{number}  {title}")
    else:
        heading = pdf_text(title)
    pdf.cell(0, 5, heading, ln=True)
    _hrule(pdf, color=_RULE_LIGHT)
    pdf.ln(4)


def _body_paragraph(pdf: FPDF, text: str) -> None:
    body = pdf_text(text)
    if not body:
        return
    line_h = 5
    h = _text_height(pdf, _CONTENT_W, body, line_h=line_h, family="serif", size=10)
    _ensure_space(pdf, h + 4)
    _font_serif(pdf, "", 10)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, line_h, body)
    pdf.ln(4)


def _footnote(pdf: FPDF, text: str) -> None:
    _font_sans(pdf, "", 7)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 3.5, pdf_text(text))
    pdf.ln(2)


def _source_ref(pdf: FPDF, label: str, url: str, *, display: str = "") -> None:
    if not url:
        return
    disp = pdf_text(display or _LINK_DISPLAY.get(label, "View source"))
    text_w = _CONTENT_W - 24
    h = _text_height(pdf, text_w, disp, line_h=3.8, style="U", size=7.5)
    _ensure_space(pdf, h + 2)
    y0 = pdf.get_y()
    _font_sans(pdf, "B", 7)
    pdf.set_text_color(*_MUTED)
    pdf.set_xy(_MARGIN_L, y0)
    pdf.cell(22, 3.8, label.upper(), ln=False)
    _font_sans(pdf, "U", 7.5)
    pdf.set_text_color(*_LINK)
    pdf.set_xy(_MARGIN_L + 24, y0)
    pdf.multi_cell(text_w, 3.8, disp, link=url)
    pdf.set_y(y0 + h + 3)


def _kpi_row(pdf: FPDF, items: list[tuple[str, str]], *, accent: tuple[int, int, int] = _NAVY) -> None:
    """Earnings-style KPI strip: large value, small-caps label, vertical dividers."""
    n = len(items)
    if not n:
        return
    col_w = _CONTENT_W / n
    _ensure_space(pdf, 28)
    y0 = pdf.get_y()
    # Top rule
    pdf.set_draw_color(*accent)
    pdf.set_line_width(0.6)
    pdf.line(_MARGIN_L, y0, _MARGIN_L + _CONTENT_W, y0)
    pdf.set_line_width(0.2)
    row_h = 22
    for i, (label, value) in enumerate(items):
        x = _MARGIN_L + i * col_w
        if i > 0:
            pdf.set_draw_color(*_RULE_LIGHT)
            pdf.line(x, y0 + 3, x, y0 + row_h - 3)
        pdf.set_xy(x + 4, y0 + 5)
        _font_sans(pdf, "B", 18)
        pdf.set_text_color(*_INK)
        pdf.cell(col_w - 8, 8, pdf_text(str(value), max_len=14), ln=True)
        pdf.set_x(x + 4)
        _font_sans(pdf, "B", 6.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w - 8, 3.5, pdf_text(label.upper()), ln=True)
    # Bottom rule
    pdf.set_draw_color(*_RULE)
    pdf.line(_MARGIN_L, y0 + row_h, _MARGIN_L + _CONTENT_W, y0 + row_h)
    pdf.set_y(y0 + row_h + 6)


def _facts_table(pdf: FPDF, rows: list[tuple[str, str]]) -> None:
    """Two-column facts table — label | value, filing style."""
    line_h = 4.5
    row_heights = []
    label_w = 42
    val_w = _CONTENT_W - label_w
    for _, val in rows:
        row_heights.append(max(6, _text_height(pdf, val_w, val, line_h=line_h, family="serif", size=9) + 2))
    total_h = sum(row_heights)
    _ensure_space(pdf, total_h + 4)
    y = pdf.get_y()
    for (label, val), rh in zip(rows, row_heights):
        pdf.set_draw_color(*_RULE_LIGHT)
        pdf.line(_MARGIN_L, y + rh, _MARGIN_L + _CONTENT_W, y + rh)
        pdf.set_xy(_MARGIN_L, y + 2)
        _font_sans(pdf, "B", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(label_w, line_h, pdf_text(label.upper()), ln=False)
        _font_serif(pdf, "", 9)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(val_w, line_h, pdf_text(val))
        y += rh
    pdf.set_y(y + 4)


def _numbered_analysis(pdf: FPDF, title: str, points: list[str]) -> None:
    """Analysis block — serif numbered points, no tinted box."""
    pdf.ln(2)
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    pdf.cell(0, 4, pdf_text(title.upper()), ln=True)
    pdf.ln(2)
    for i, point in enumerate(points, start=1):
        pt = pdf_text(point)
        text_w = _CONTENT_W - 10
        h = _text_height(pdf, text_w, pt, line_h=4.8, family="serif", size=9.5)
        _ensure_space(pdf, h + 2)
        y0 = pdf.get_y()
        _font_sans(pdf, "B", 8)
        pdf.set_text_color(*_MUTED)
        pdf.set_xy(_MARGIN_L, y0)
        pdf.cell(8, 4.8, f"{i}.", ln=False)
        _font_serif(pdf, "", 9.5)
        pdf.set_text_color(*_INK)
        pdf.set_xy(_MARGIN_L + 10, y0)
        pdf.multi_cell(text_w, 4.8, pt)
        pdf.ln(2)
    pdf.ln(2)


# ── Institutional data tables ─────────────────────────────────────────────────

def _scaled_col_widths(columns: list[tuple[str, str, float]], *, link_w: float = 0) -> list[float]:
    raw = [w * _CONTENT_W for _, _, w in columns]
    data_w = _CONTENT_W - link_w
    total = sum(raw) or 1.0
    return [w * data_w / total for w in raw]


def _table_row_height(
    pdf: FPDF, col_widths: list[float], values: list[str],
    *, size: int = 8, line_h: float = 3.8, min_h: float = 6.5,
) -> float:
    _font_sans(pdf, "", size)
    max_lines = 1
    for val, w in zip(values, col_widths):
        n = _count_lines(pdf, max(w - 3, 8), val, line_h=line_h)
        max_lines = max(max_lines, n)
    return max(min_h, 3 + max_lines * line_h)


def _institutional_table(
    pdf: FPDF,
    columns: list[tuple[str, str, float]],
    rows: list[dict],
    *,
    link_key: str = "",
) -> None:
    link_w = 16.0 if link_key else 0.0
    col_widths = _scaled_col_widths(columns, link_w=link_w)
    header_h = 8

    _ensure_space(pdf, header_h + 6)
    y0 = pdf.get_y()
    pdf.set_fill_color(*_NAVY)
    pdf.rect(_MARGIN_L, y0, _CONTENT_W, header_h, "F")
    x = _MARGIN_L + 3
    _font_sans(pdf, "B", 7)
    pdf.set_text_color(*_WHITE)
    for (label, _, _), w in zip(columns, col_widths):
        pdf.set_xy(x, y0 + 2.5)
        pdf.cell(w - 3, 4, pdf_text(label.upper()), ln=False)
        x += w
    if link_w:
        pdf.set_xy(x, y0 + 2.5)
        pdf.cell(link_w - 3, 4, "SOURCE", ln=False)
    pdf.set_y(y0 + header_h)

    for i, row in enumerate(rows):
        values = [pdf_text(row.get(key, "")) for _, key, _ in columns]
        rh = _table_row_height(pdf, col_widths, values)
        _ensure_space(pdf, rh + 1)
        y0 = pdf.get_y()
        x = _MARGIN_L + 3
        _font_sans(pdf, "", 8)
        pdf.set_text_color(*_BODY)
        for val, w in zip(values, col_widths):
            pdf.set_xy(x, y0 + 2)
            pdf.multi_cell(max(w - 3, 8), 3.8, val)
            x += w
        if link_key:
            url = str(row.get(link_key, "") or "")
            pdf.set_xy(x, y0 + (rh - 4) / 2)
            if url:
                _font_sans(pdf, "U", 7)
                pdf.set_text_color(*_LINK)
                pdf.cell(link_w - 3, 4, "View", link=url, ln=False)
            else:
                pdf.set_text_color(*_MUTED)
                pdf.cell(link_w - 3, 4, "-", ln=False)
        pdf.set_draw_color(*_RULE_LIGHT)
        pdf.line(_MARGIN_L, y0 + rh, _MARGIN_L + _CONTENT_W, y0 + rh)
        pdf.set_y(y0 + rh)
    pdf.ln(4)


def _record_dataset_key(row: dict, default_key: str) -> str:
    if row.get("permit_status") == "311 complaint":
        return "311"
    return source_links.record_dataset_key(default_key, str(row.get("source_id") or ""))


# ── Data accessors ────────────────────────────────────────────────────────────

class CardData:
    def __init__(
        self, title: str, rows: list[dict], columns: list[tuple[str, str, float]],
        total: int | None, total_text: str, max_rows: int, dataset_key: str,
    ) -> None:
        self.title = title
        self.rows = rows
        self.columns = columns
        self.total = total
        self.total_text = total_text
        self.max_rows = max_rows
        self.dataset_key = dataset_key


_DATE_KEYS = frozenset({"occurred_at", "created_at", "filing_date"})


def _display_date(raw: object) -> str:
    """'2026-09-29T00:00:00.000' -> 'Sep 29, 2026'; keeps the time when the record has one.

    NYC Open Data timestamps are New York local time without an offset, so no conversion.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return text
    day = f"{dt:%b} {dt.day}, {dt.year}"
    if (dt.hour, dt.minute, dt.second) == (0, 0, 0):
        return day
    return f"{day} {dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def _with_location(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        copy = dict(r)
        lat, lng = copy.get("lat"), copy.get("lng")
        copy["_location"] = f"{lat}, {lng}" if lat is not None and lng is not None else ""
        out.append(copy)
    return out


def _within(ctx: DossierContext, key: str) -> str:
    window = _feed_window_text(ctx, key)
    radius = f"within {ctx.scan_radius_miles:g} mi"
    return f"{radius}, {window}" if window else radius


def _card_data(card_id: str, ctx: DossierContext) -> CardData | None:
    crime_cols = [
        ("Date", "occurred_at", 0.13),
        ("Offense", "crime_type", 0.22),
        ("Description", "description", 0.33),
        ("Location", "_location", 0.18),
    ]
    r311_cols = [
        ("Date", "created_at", 0.13),
        ("Complaint", "complaint_type", 0.20),
        ("Descriptor", "descriptor", 0.37),
        ("Location", "_location", 0.16),
    ]
    permit_cols = [
        ("Issued", "filing_date", 0.13),
        ("Type", "permit_type", 0.17),
        ("Status", "permit_status", 0.13),
        ("Details", "job_description", 0.41),
    ]
    eviction_cols = [
        ("Executed", "filing_date", 0.16),
        ("Address", "address", 0.40),
        ("Location", "_location", 0.28),
    ]

    def _total(key: str, part: str | None = None) -> int | None:
        f = _feed(ctx, key)
        if f.get("status") != "ok":
            return None
        return int((f.get("breakdown") or {}).get(part, 0)) if part else int(f.get("total") or 0)

    if card_id == "high_churn":
        n = _total("evictions")
        return CardData("Residential Evictions", _with_location(ctx.evictions), eviction_cols, n,
                        f"{n or 0:,} {_within(ctx, 'evictions')}", PDF_CARD_RECORDS_MAX, "evictions")
    if card_id == "area_safety":
        n = _total("crime")
        return CardData("NYPD Complaints", _with_location(ctx.crime), crime_cols, n,
                        f"{n or 0:,} {_within(ctx, 'crime')}", PDF_CARD_RECORDS_MAX, "crime")
    if card_id == "demolitions":
        permits_n, construction_n = _total("permits"), _total("311", "construction")
        construction = [r for r in ctx.reports_311 if city_data.is_311_construction(r)]
        combined = list(ctx.permits) + [
            {**r, "filing_date": r.get("created_at"), "permit_type": r.get("complaint_type"),
             "permit_status": "311 complaint", "job_description": r.get("descriptor")}
            for r in construction
        ]
        total = (permits_n or 0) + (construction_n or 0)
        permits_text = (
            f"{permits_n:,} active {'permit' if permits_n == 1 else 'permits'} {_within(ctx, 'permits')}"
            if permits_n is not None else "DOB permits unavailable"
        )
        construction_text = (
            f"{construction_n:,} construction {'complaint' if construction_n == 1 else 'complaints'} to 311 "
            f"({_feed_window_text(ctx, '311')})"
            if construction_n is not None else "311 unavailable"
        )
        text = f"{permits_text}; {construction_text}"
        return CardData("Permits & Construction", combined, permit_cols, total, text, PDF_CARD_RECORDS_MAX, "permits")
    if card_id == "noise_schedule":
        n = _total("311", "noise")
        noise = [r for r in ctx.reports_311 if city_data.is_311_noise(r)]
        return CardData("Noise Complaints", _with_location(noise), r311_cols, n,
                        f"{n or 0:,} {_within(ctx, '311')}", PDF_CARD_RECORDS_MAX, "311")
    if card_id == "reports_311":
        n = _total("311")
        return CardData("311 Requests", _with_location(ctx.reports_311), r311_cols, n,
                        f"{n or 0:,} {_within(ctx, '311')}", PDF_311_MAX, "311")
    return None


def _dossier_ids_for_card(card_id: str, ctx: DossierContext) -> dict[str, list[str]]:
    """Record IDs (in table order) for datasets linked by exact records instead of the scan filter."""
    def _ids(rows: list[dict], prefix: str = "") -> list[str]:
        out = []
        for r in rows[:PDF_CARD_RECORDS_MAX]:
            sid = str(r.get("source_id") or "").strip()
            if sid and sid.startswith(prefix):
                out.append(sid)
        return out

    if card_id == "high_churn":
        return {"evictions": _ids(ctx.evictions)}
    if card_id == "demolitions":
        return {"permits": _ids([r for r in ctx.permits if str(r.get("source_id") or "").startswith("BIS:")])}
    return {}


def _police_calls_rows(ctx: DossierContext) -> list[dict]:
    f = _feed(ctx, "police_calls")
    breakdown = f.get("breakdown") or {}
    rows = [
        {"label": "Critical priority", "count": f"{int(breakdown.get('critical', 0)):,}"},
        {"label": "Serious priority", "count": f"{int(breakdown.get('serious', 0)):,}"},
        {"label": "Non-critical priority", "count": f"{int(breakdown.get('non_critical', 0)):,}"},
    ]
    for call_type, n in f.get("top_types") or []:
        rows.append({"label": f"Most common: {call_type}", "count": f"{int(n):,}"})
    return rows


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_overview(pdf: DossierPDF, ctx: DossierContext, client: dict) -> None:
    pdf.add_page()
    _section_opener(pdf, 1, "Executive Overview",
                    subtitle="Property identification, wellness assessment, and summary findings")

    _subsection(pdf, "1.1", "Subject Property")
    _font_serif(pdf, "B", 12)
    pdf.set_text_color(*_INK)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 5.5, pdf_text(ctx.formatted_address))
    pdf.ln(3)
    _facts_table(pdf, [
        ("Coordinates", f"{ctx.coord_lat:.5f}, {ctx.coord_lng:.5f}"),
        ("Scan Radius", f"{ctx.scan_radius_miles:g} miles"),
        ("Scan Timestamp", ctx.scanned_at[:19].replace("T", " ") + " UTC"),
    ])

    if ctx.data_sources:
        _subsection(pdf, "-", "Data Sources (count | date range | data as of | provider)")
        _facts_table(pdf, [(str(src.get("label", "")), _source_line(src)) for src in ctx.data_sources])
        _footnote(pdf, "NYPD publishes complaints and calls quarterly, so their date ranges end at the newest "
                       "published day rather than today. A record from the last day or two can show as empty on "
                       "NYC Open Data at random; reloading the page, sometimes a few times, shows it.")

    _subsection(pdf, "1.2", "Wellness Assessment")
    if ctx.score_available:
        risk_level = pdf_text(client.get("risk_level", "MODERATE"), default="MODERATE")
        r, g, b = RISK_COLORS.get(risk_level, (120, 120, 120))
        _kpi_row(pdf, [
            ("Wellness Score", f"{client.get('danger_score', '-')}"),
            ("Rating", pdf_text(client.get("risk_label", ""))),
            ("Risk Level", risk_level.title()),
        ], accent=(r, g, b))
    else:
        _kpi_row(pdf, [("Wellness Score", "Not scored"), ("Rating", "-"), ("Risk Level", "-")], accent=_MUTED)
    bands = "  |  ".join(f"{low}-{high}: {label}" for low, high, label in reversed(label_band_rows()))
    _footnote(pdf, f"Scale: 0 (worst) to 100 (best).  {bands}")

    _subsection(pdf, "1.3", "Summary of Findings")
    _body_paragraph(pdf, str(client.get("risk_description", "") or "No summary available."))
    driver = _DRIVER_NAMES.get(str(client.get("banner_driver") or ""))
    if driver:
        pdf.ln(2)
        _font_sans(pdf, "B", 7.5)
        pdf.set_text_color(*_MUTED)
        pdf.set_x(_MARGIN_L)
        pdf.cell(0, 4, "PRIMARY DRIVER", ln=True)
        _body_paragraph(pdf, driver)


def _render_threat_card(pdf: DossierPDF, card: dict, ctx: DossierContext, sec: str, idx: int) -> None:
    card_id = str(card.get("id", ""))
    title = pdf_text(card.get("title", ""))
    severity = str(card.get("severity_level") or "unavailable")
    sev = SEVERITY_LABELS.get(severity, severity.replace("_", " ").title())
    if card.get("nyc_percentile") is not None and severity in ("quiet", "watch", "elevated"):
        pct = int(card["nyc_percentile"])
        sev += (f" (higher than at {pct}% of NYC apartment locations)" if pct >= 50
                else f" (lower than at {100 - pct}% of NYC apartment locations)")
    subtitle = pdf_text(card.get("subtitle", ""))

    pdf.ln(4 if idx > 1 else 0)
    _subsection(pdf, sec, title)
    _font_sans(pdf, "B", 7.5)
    pdf.set_text_color(*_MUTED)
    pdf.set_x(_MARGIN_L)
    pdf.cell(18, 4, "NYC LEVEL", ln=False)
    _font_sans(pdf, "B", 8)
    cr, cg, cb = _parse_hex_color(str(card.get("border_color", "")))
    pdf.set_text_color(cr, cg, cb)
    pdf.cell(0, 4, pdf_text(sev), ln=True)
    if subtitle:
        _body_paragraph(pdf, subtitle)

    dossier_ids = _dossier_ids_for_card(card_id, ctx)
    for label, url, ds_key, scope in source_links.card_dataset_urls(
        card_id,
        _coord(ctx),
        radius_miles=ctx.scan_radius_miles,
        windows=_feed_windows(ctx),
        dossier_ids=dossier_ids,
    ):
        short = label.replace(" (NYC Open Data)", "")
        if scope == "scan":
            # The link applies the scan's own filter, but an explore page lists a capped number of rows.
            display = (f"{short} - the records counted in this scan "
                       f"(the page lists up to {source_links.BROWSE_LIMIT:,}, newest first")
            display += "; one row per permit and work type)" if ds_key == "permits_now" else ")"
        elif ds_key == "permits":
            # BIS stores coordinates as text, so its link lists the counted permits by ID, not by area.
            n = len(dossier_ids.get(ds_key, []))
            counted = (_feed(ctx, "permits").get("extra") or {}).get("bis_total", n)
            display = (f"{short} - the {n:,} BIS permits counted in this scan" if n >= counted
                       else f"{short} - {n:,} of the {counted:,} BIS permits counted in this scan")
        else:
            n = len(dossier_ids.get(ds_key, []))
            display = f"{short} - the {n:,} records listed in this report"
        _source_ref(pdf, "Source", url, display=display)

    hpd_url = source_links.hpd_violations_url(ctx.formatted_address) if card_id == "tenant_warnings" else None
    if hpd_url:
        _source_ref(pdf, "HPD", hpd_url, display="HPD violations for this address (NYC Open Data)")

    bullets = [pdf_text(b) for b in (card.get("bullets") or []) if str(b or "").strip()]
    if bullets:
        _numbered_analysis(pdf, "Analysis", bullets)

    if card_id in ("tenant_warnings", "oven_effect"):
        return
    if card_id == "flight_path":
        _render_flight(pdf, ctx, inline=True)
        return

    missing = [_feed(ctx, k).get("label") or k for k in _CARD_FEEDS.get(card_id, ()) if not _feed_ok(ctx, k)]
    if missing:
        _footnote(pdf, f"Unavailable during this scan: {', '.join(missing)}. NYC Open Data didn't respond, "
                       "so no records are shown.")
        if len(missing) == len(_CARD_FEEDS.get(card_id, ())):
            return

    if card_id == "police_calls":
        pdf.ln(2)
        _ensure_space(pdf, _HEADING_WITH_TABLE_MM)
        _font_sans(pdf, "B", 8)
        pdf.set_text_color(*_NAVY)
        pdf.set_x(_MARGIN_L)
        total = _feed(ctx, "police_calls").get("total") or 0
        pdf.cell(0, 4, pdf_text(f"SUPPORTING DATA - NYPD CRIME-IN-PROGRESS CALLS  "
                                f"({int(total):,} {_within(ctx, 'police_calls')})"), ln=True)
        pdf.ln(2)
        _institutional_table(pdf, [("Category", "label", 0.75), ("Calls", "count", 0.25)], _police_calls_rows(ctx))
        _footnote(pdf, "Calls are summarized by priority and type here. The source link applies this scan's "
                       f"filter and lists up to {source_links.BROWSE_LIMIT:,} of those call records, newest first.")
        return

    data = _card_data(card_id, ctx)
    if not data:
        return

    pdf.ln(2)
    _ensure_space(pdf, _HEADING_WITH_TABLE_MM)
    _font_sans(pdf, "B", 8)
    pdf.set_text_color(*_NAVY)
    pdf.set_x(_MARGIN_L)
    pdf.multi_cell(_CONTENT_W, 4, pdf_text(f"SUPPORTING DATA - {data.title.upper()}  ({data.total_text})"))
    pdf.ln(2)

    table_rows = []
    for row in data.rows[:data.max_rows]:
        r = dict(row)
        for _, key, _ in data.columns:
            if key in _DATE_KEYS:
                r[key] = _display_date(r.get(key))
        dk = _record_dataset_key(row, data.dataset_key)
        r["_url"] = source_links.record_url(dk, str(r.get("source_id") or "")) or ""
        table_rows.append(r)

    if not table_rows:
        _footnote(pdf, "No matching records within the scan radius for this date range.")
        return
    _institutional_table(pdf, data.columns, table_rows, link_key="_url")
    if data.total is not None and len(table_rows) < data.total:
        _footnote(pdf, f"Showing {len(table_rows):,} of {data.total:,} records. Counts and the Wellness Score "
                       "use the full total.")


def _distance_text(card: dict) -> str:
    value, unit = card.get("distance_value"), card.get("distance_unit")
    if value is None:
        return "-"
    if unit == "feet":
        return f"{int(round(float(value))):,} ft"
    return f"{float(value):g} mi"


_PROVIDER_NAMES = {"google_places": "Google", "yelp": "Yelp"}


def _render_dining(pdf: DossierPDF, candidates: list[dict], *, formatted_address: str, coord: Coordinate) -> None:
    pdf.add_page()
    _section_opener(pdf, 3, "Dining & Nightlife",
                    subtitle="Top-rated restaurants and bars within 2 miles (Yelp / Google Places)")
    if not candidates:
        _footnote(pdf, "Restaurant rankings unavailable from configured APIs.")
        return

    _source_ref(
        pdf,
        "Browse all",
        source_links.dining_area_url(formatted_address, coord),
        display="View nearby restaurants on Google Maps",
    )

    cols = [
        ("#", "_rank", 0.05),
        ("Establishment", "name", 0.26),
        ("Category", "category", 0.14),
        ("Rating", "_rating", 0.08),
        ("Reviews", "_reviews", 0.09),
        ("Distance", "_distance", 0.10),
        ("Provider", "source", 0.10),
    ]
    table_rows = []
    for i, card in enumerate(candidates, start=1):
        rating = card.get("rating")
        reviews = card.get("review_count")
        table_rows.append({
            "_rank": str(i),
            "name": pdf_text(card.get("name", "Unknown")),
            "category": pdf_text(card.get("category", "")),
            "source": _PROVIDER_NAMES.get(str(card.get("source") or ""), pdf_text(card.get("source", ""))),
            "_rating": f"{rating}" if rating is not None else "-",
            "_reviews": f"{reviews:,}" if reviews else "-",
            "_distance": _distance_text(card),
            "_url": source_links.dining_listing_url(card, formatted_address) or "",
        })
    _institutional_table(pdf, cols, table_rows, link_key="_url")


def _render_flight(pdf: DossierPDF, ctx: DossierContext, *, inline: bool = False) -> None:
    exposure = ctx.flight_exposure or {}
    if not exposure.get("show_flight_feature"):
        if inline:
            _footnote(pdf, "Insufficient ADS-B data for this block.")
        return

    if not inline:
        pdf.add_page()
        _section_opener(pdf, 4, "Flight Noise & Exposure",
                        subtitle="ADS-B-derived aircraft exposure vs. NYC block baselines")

    obs_days = exposure.get("observation_days", 7)
    radius = exposure.get("radius_miles") or ctx.scan_radius_miles
    night = float(exposure.get("night_overflights_per_hour") or 0)
    day = float(exposure.get("day_overflights_per_hour") or 0)

    _subsection(pdf, "4.1" if not inline else "-", "Exposure Metrics" if not inline else "Flight Exposure Metrics")
    stats: list[tuple[str, str]] = [
        ("Night passes/hr", f"{night:.2f}"),
        ("Day passes/hr", f"{day:.2f}"),
        ("Observation Window", f"{obs_days} days"),
    ]
    for key, label in [("night_percentile", "Night Percentile"), ("day_percentile", "Day Percentile")]:
        v = exposure.get(key)
        if v is not None:
            stats.append((label, f"{v:.0%}"))
    _kpi_row(pdf, stats)

    notes = []
    if exposure.get("headline"):
        notes.append(str(exposure.get("headline")))
    if exposure.get("detail"):
        notes.append(str(exposure.get("detail")))
    alt = exposure.get("typical_altitude_ft")
    if alt is not None:
        notes.append(f"Typical median altitude: {alt:,} ft")
    notes.append(
        "A pass is one aircraft seen inside the radius; it counts as a new pass only after more than "
        "10 minutes unseen there. Night is 10 pm to 7 am New York time."
    )
    notes.append(
        f"Radius {radius:g} mi  |  Level {exposure.get('elevation_level', 'n/a')}  |  "
        f"Coverage {exposure.get('data_quality', 'n/a')}  |  ADS-B positions {int(exposure.get('sample_count') or 0):,}"
    )
    _numbered_analysis(pdf, "Exposure Notes", notes)
    _source_ref(
        pdf,
        "Source",
        source_links.adsb_area_url(_coord(ctx)),
        display="Live aircraft map around this address (adsb.lol, the source ZerMap records from)",
    )

    paths = ctx.flight_paths or []
    if paths:
        _subsection(pdf, "4.2" if not inline else "-", f"Recent Aircraft Tracks ({len(paths)})")
        path_cols = [
            ("#", "_n", 0.06), ("Route", "label", 0.22), ("Callsign", "callsign", 0.16),
            ("Closest", "closest", 0.14), ("Altitude", "altitude", 0.14), ("Positions", "vertices", 0.12),
        ]
        path_rows = [{
            "_n": str(i), "label": pdf_text(p.get("label", "")),
            "callsign": pdf_text(p.get("callsign") or "n/a"),
            "closest": f"{p.get('closest_miles', 'n/a')} mi",
            "altitude": f"{p.get('median_altitude_ft', 'n/a')} ft",
            "vertices": str(len(p.get("path") or [])),
            "_url": source_links.adsb_aircraft_from_label(str(p.get("label", ""))) or "",
        } for i, p in enumerate(paths, start=1)]
        _institutional_table(pdf, path_cols, path_rows, link_key="_url")

    adsb = ctx.adsb_samples or []
    if adsb:
        cap = 50 if inline else 80
        shown = min(len(adsb), cap)
        total = max(ctx.adsb_sample_total, len(adsb))
        _subsection(pdf, "4.3" if not inline else "-", f"ADS-B Observations (newest {shown:,} of {total:,})")
        adsb_cols = [
            ("#", "_n", 0.05), ("Observed (UTC)", "observed_at", 0.22),
            ("ICAO24", "icao24", 0.12), ("Position", "position", 0.22),
            ("Baro Alt", "baro", 0.11), ("Geo Alt", "geo", 0.11),
        ]
        adsb_rows = [{
            "_n": str(i),
            "observed_at": pdf_text(r.get("observed_at", "")),
            "icao24": pdf_text(r.get("icao24", "")),
            "position": f"{r.get('lat', '')}, {r.get('lng', '')}",
            "baro": f"{r.get('baro_alt_m', 'n/a')} m",
            "geo": f"{r.get('geo_alt_m', 'n/a')} m",
            "_url": source_links.adsb_aircraft_url(str(r.get("icao24") or "")) or "",
        } for i, r in enumerate(adsb[:cap], start=1)]
        _institutional_table(pdf, adsb_cols, adsb_rows, link_key="_url")
        if total > shown:
            _footnote(pdf, f"{total - shown:,} more ADS-B positions inside the radius were used for the pass counts.")


def build_dossier_pdf(ctx: DossierContext, client: dict) -> bytes:
    pdf = DossierPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=_MARGIN_B)
    pdf.set_margins(_MARGIN_L, _MARGIN_T, _MARGIN_R)
    pdf.add_page()

    _render_cover(pdf, ctx.formatted_address)
    _render_overview(pdf, ctx, client)

    cards = client.get("threat_cards") or []
    pdf.add_page()
    _section_opener(pdf, 2, "Threat Analysis",
                    subtitle=f"{len(cards)} risk dimensions with AI interpretation and municipal source records")

    for i, card in enumerate(cards, start=1):
        _render_threat_card(pdf, card, ctx, f"2.{i}", i)

    _render_dining(pdf, ctx.dining_candidates or [], formatted_address=ctx.formatted_address, coord=_coord(ctx))

    if ctx.flight_exposure and ctx.flight_exposure.get("show_flight_feature"):
        if not any(str(c.get("id")) == "flight_path" for c in cards):
            _render_flight(pdf, ctx, inline=False)

    return bytes(pdf.output())
