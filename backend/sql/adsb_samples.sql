-- ADS-B sample storage (prototype).
-- Stores aircraft position samples so we can compute "flight exposure" over time.
--
-- Canonical migration (for CI): supabase/migrations/20260211120000_adsb_samples.sql
-- Apply manually: paste this file into Supabase SQL Editor, or rely on GitHub Action
-- "Deploy Supabase migrations" after configuring repository secrets (see README).

create table if not exists public.adsb_samples (
  id bigserial primary key,
  observed_at timestamptz not null,
  icao24 text not null,
  lat double precision not null,
  lng double precision not null,
  baro_alt_m double precision null,
  geo_alt_m double precision null,
  on_ground boolean null,
  velocity_mps double precision null,
  true_track_deg double precision null,
  source text not null default 'opensky'
);

create index if not exists adsb_samples_observed_at_idx on public.adsb_samples (observed_at desc);
create index if not exists adsb_samples_icao24_idx on public.adsb_samples (icao24);
create index if not exists adsb_samples_lat_lng_idx on public.adsb_samples (lat, lng);

-- Optional: de-dupe best-effort (same plane + timestamp + rounded position)
-- You can add a unique index if you want stricter de-dupe once sampling cadence is known.
