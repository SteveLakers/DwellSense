/** Display formatting shared by cards, map popups and the data-sources panel. */

export function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return n === 1 ? one : many;
}

/** Backend sends feet under 1,000 ft and miles (1 decimal) beyond that. */
export function distanceParts(value: number, unit: "feet" | "miles"): { value: string; unit: string } {
  if (unit === "feet") return { value: formatCount(Math.round(value)), unit: "ft" };
  return { value: String(Number(value.toFixed(1))), unit: "mi" };
}

export function formatDistance(value: number, unit: "feet" | "miles"): string {
  const p = distanceParts(value, unit);
  return `${p.value} ${p.unit}`;
}

const MONTH = new Intl.DateTimeFormat("en-US", { month: "short", timeZone: "UTC" });

function parseIsoDay(iso?: string | null): Date | null {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return null;
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "Jun 30, 2026" from an ISO date (calendar day, no timezone shift). */
export function formatIsoDay(iso?: string | null): string | null {
  const d = parseIsoDay(iso);
  return d ? `${MONTH.format(d)} ${d.getUTCDate()}, ${d.getUTCFullYear()}` : null;
}

/** "Jun 1–30, 2026", "Sep 3 – Oct 2, 2026" or "Dec 3, 2025 – Jan 2, 2026". */
export function formatDateRange(start?: string | null, end?: string | null): string | null {
  const a = parseIsoDay(start);
  const b = parseIsoDay(end);
  if (!a || !b) return formatIsoDay(start) ?? formatIsoDay(end);
  const sameYear = a.getUTCFullYear() === b.getUTCFullYear();
  if (sameYear && a.getUTCMonth() === b.getUTCMonth()) {
    if (a.getUTCDate() === b.getUTCDate()) return formatIsoDay(end);
    return `${MONTH.format(a)} ${a.getUTCDate()}–${b.getUTCDate()}, ${b.getUTCFullYear()}`;
  }
  const left = sameYear ? `${MONTH.format(a)} ${a.getUTCDate()}` : formatIsoDay(start);
  return `${left} – ${formatIsoDay(end)}`;
}

/** "350 West 42nd Street, New York, New York 10036, United States" → street line + the rest, without the country. */
export function splitAddress(formatted: string): { line1: string; line2: string | null } {
  const parts = formatted
    .split(",")
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length > 1 && /^(united states|usa|us)$/i.test(parts[parts.length - 1])) parts.pop();
  const [line1, ...rest] = parts;
  return { line1: line1 ?? formatted.trim(), line2: rest.length ? rest.join(", ") : null };
}

/** "40.7577° N, 73.9918° W" for the geocoded point a report is centered on. */
export function formatCoordinates({ lat, lng }: { lat: number; lng: number }): string {
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lng).toFixed(4)}° ${lng >= 0 ? "E" : "W"}`;
}

const KEEP_UPPER = new Set(["NYC", "NYPD", "HPD", "DOB", "ADS-B"]);

/** Backend card titles arrive in capitals ("TENANT CHURN"); show them as "Tenant churn". */
export function sentenceCase(title: string): string {
  if (/[a-z]/.test(title)) return title;
  const words = title.split(/(\s+)/).map((w) => (KEEP_UPPER.has(w) ? w : w.toLowerCase()));
  const joined = words.join("");
  const first = joined.search(/\S/);
  return first < 0 ? joined : joined.slice(0, first) + joined[first].toUpperCase() + joined.slice(first + 1);
}

/** For text placed into Mapbox popup HTML (labels come from city datasets). */
export function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Status emoji the backend prefixes to scored labels (routers/scan.py). */
const LABEL_EMOJI = ["🚨", "⚠️", "⚠", "🟡", "✅", "🌟", "✨"];

/** "🟡 Average" → "Average"; labels without a status emoji ("Not scored") are unchanged. */
export function stripLeadingEmoji(label: string): string {
  const s = label.trimStart();
  const hit = LABEL_EMOJI.find((e) => s.startsWith(e));
  return hit ? s.slice(hit.length).trimStart() : s;
}
