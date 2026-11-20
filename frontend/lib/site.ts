export const SITE_URL = "https://zermap.com";
export const SITE_NAME = "ZerMap";
export const SITE_TITLE = "ZerMap | Check an NYC address before you sign a lease";
/**
 * Flight noise is paused: in November 2026 the aircraft-position provider began capping how many requests
 * the collector may make, so passes can no longer be counted. The site's flight copy follows this switch.
 * Keep it in step with FLIGHT_NOISE_PAUSED in backend/services/flight_exposure.py (a backend test checks
 * that the two agree) and set both to false in the same change once flights are re-measured.
 */
export const FLIGHT_NOISE_PAUSED = true;

export const SITE_DESCRIPTION =
  "Free report for any NYC address: NYPD complaints, 311 requests, evictions" +
  (FLIGHT_NOISE_PAUSED ? " and construction permits" : ", construction permits and flight noise") +
  " from official city data, compared with apartment locations across NYC.";

/** Public contact address (NEXT_PUBLIC_CONTACT_EMAIL). Contact lines are hidden when unset. */
export const CONTACT_EMAIL = (process.env.NEXT_PUBLIC_CONTACT_EMAIL || "").trim();

/** Public place used for the homepage sample report (not anyone's home). */
export const SAMPLE_ADDRESS = "Union Square, New York, NY";

/** Placeholder in the search box; it's what gets checked when the box is left empty. */
export const EXAMPLE_ADDRESS = "350 W 42nd St, New York, NY 10036";

/** EXAMPLE_ADDRESS as [lng, lat] (NYC Planning GeoSearch); the homepage map draws its 2-mile circle here. */
export const EXAMPLE_LNG_LAT: [number, number] = [-73.992263, 40.757966];

/** Backend default scan radius (SCAN_RADIUS_MILES). Homepage copy and map assume it; reports use the live value. */
export const SCAN_RADIUS_MILES = 2;
