"use client";

import { useEffect, useRef, useCallback } from "react";
import mapboxgl from "mapbox-gl";
import { DataSource, FlightExposure, MapData, LogisticsCard } from "@/lib/types";
import { flightPathToLineLngLat, flightPathToRouteLatLng, filterFlightPathsWithinRadius } from "@/lib/flightPathDisplay";
import { escapeHtml, formatCount, formatDistance, plural } from "@/lib/format";
import { reviewCountLabel } from "@/lib/proximityCards";

mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN || "";

// NYC viewport lock (approx city bounds)
const NYC_MAX_BOUNDS: mapboxgl.LngLatBoundsLike = [
  [-74.2591, 40.4774], // SW
  [-73.7004, 40.9176], // NE
];

/** Minimum real ADS-B vertices required to render a track (matches backend ADSB_PATH_MIN_POINTS). */
const MIN_FLIGHT_PATH_POINTS = 5;

const SWARM_EMOJI: Record<string, string> = {
  police:       "🚓",
  rat:          "🐀",
  permit:       "🚧",
  construction: "🚧",
  truck:        "🚛",
  bus:          "🚌",
  noise:        "🔊",
  fire:         "🔥",
  water:        "💧",
  trash:        "🗑️",
  graffiti:     "🎨",
  report:       "📋",
};

const SWARM_COLOR: Record<string, string> = {
  police:       "#1D4ED8",
  rat:          "#7E22CE",
  permit:       "#C2410C",
  construction: "#C2410C",
  truck:        "#A16207",
  bus:          "#4D7C0F",
  noise:        "#A16207",
  fire:         "#B91C1C",
  water:        "#0369A1",
  trash:        "#15803D",
  graffiti:     "#A21CAF",
  report:       "#57534E",
};

const INK = "#151515";
const TAXI = "#FFCC00";

const LOGISTICS_PIN_EMOJI: Record<string, string> = {
  subway: "🚇",
  train: "🚆",
  bus: "🚌",
  grocery: "🛒",
  airport: "✈️",
  mall: "🛍️",
  targetstore: "🎯",
  walmart: "🛒",
  traderjoes: "🥑",
};

function logisticsPinEmoji(card: LogisticsCard): string {
  if (card.type.startsWith("dining-")) {
    return card.emoji?.trim() || "🍽️";
  }
  if (card.type === "grocery") {
    return "🛒";
  }
  const byType = LOGISTICS_PIN_EMOJI[card.type];
  if (byType) return byType;
  const fromCard = card.emoji?.trim();
  if (fromCard && fromCard !== "📍") return fromCard;
  return "🏪";
}

function zoneKindLabel(color: string): string {
  switch (color) {
    case "#ef4444":
      return "NYPD complaint";
    case "#a855f7":
      return "311 rodent complaint";
    case "#f97316":
      return "DOB permit";
    case "#3b82f6":
    default:
      return "311 request";
  }
}

/** Legend rows for pin types present on the map (types from backend city_data.build_swarm). */
const SWARM_LEGEND: { emoji: string; types: string[]; label: (present: Set<string>) => string }[] = [
  { emoji: "🚓", types: ["police"], label: () => "NYPD complaints" },
  {
    emoji: "🚧",
    types: ["permit", "construction"],
    label: (p) =>
      p.has("permit") && p.has("construction")
        ? "DOB permits & 311 construction"
        : p.has("permit")
          ? "DOB permits"
          : "311 construction",
  },
  { emoji: "🐀", types: ["rat"], label: () => "Rodents (311)" },
  { emoji: "🔊", types: ["noise"], label: () => "Noise (311)" },
  { emoji: "🔥", types: ["fire"], label: () => "Heat & hot water (311)" },
  { emoji: "💧", types: ["water"], label: () => "Water & sewer (311)" },
  { emoji: "🗑️", types: ["trash"], label: () => "Sanitation (311)" },
  { emoji: "🎨", types: ["graffiti"], label: () => "Graffiti (311)" },
  { emoji: "🚛", types: ["truck"], label: () => "Traffic (311)" },
  { emoji: "📋", types: ["report"], label: () => "Other 311" },
];

/** Colours reach popup HTML from the backend, so only plain hex values are let through. */
function safeColor(color: string): string {
  return /^#[0-9a-f]{3,8}$/i.test(color.trim()) ? color.trim() : "#63625B";
}

function popupHtml(title: string, color: string, lines: (string | null | undefined)[]): string {
  const body = lines
    .filter((l): l is string => Boolean(l))
    .map((l) => `<div style="font-size:13px;line-height:1.35;color:#45453f;margin-top:4px">${escapeHtml(l)}</div>`)
    .join("");
  return (
    `<div style="display:flex;align-items:center;gap:7px;font-size:14px;font-weight:700;line-height:1.25;color:${INK}">` +
    `<span style="flex:none;width:10px;height:10px;border-radius:2px;background:${safeColor(color)}"></span>` +
    `${escapeHtml(title)}</div>${body}`
  );
}

/** Sources whose records become map pins (backend city_data.build_swarm). */
const PIN_SOURCE_KEYS = ["crime", "311", "permits"];

/** "A", "A and B", "A, B and C" */
function joinLabels(labels: string[]): string {
  if (labels.length <= 1) return labels.join("");
  return `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

interface Props {
  mapData: MapData;
  logistics: LogisticsCard[];
  activeRoute: string | null;
  flightExposure?: FlightExposure | null;
  /** Lets the caption say when a source that feeds the pins did not answer. */
  dataSources?: DataSource[];
}

export default function MapComponent({ mapData, logistics, activeRoute, flightExposure, dataSources }: Props) {
  const scanRadiusMi = mapData.scan_radius_miles ?? 2;
  const scanRadiusLabel = Number.isInteger(scanRadiusMi)
    ? `${scanRadiusMi} mi`
    : `${scanRadiusMi.toFixed(1)} mi`;
  const showFlightFeature = Boolean(flightExposure?.show_flight_feature);

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const trackPlaneMarkersRef = useRef<mapboxgl.Marker[]>([]);
  const trackProgressRef = useRef<number[]>([]);
  const trackLastTimeRef = useRef(0);
  const trackRafRef = useRef<number>();
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const flightVertexMarkersRef = useRef<mapboxgl.Marker[]>([]);
  const zonePopupRef = useRef<mapboxgl.Popup | null>(null);
  const zoneHoveredIdRef = useRef<number | null>(null);

  // ── Build map on mount ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: [mapData.target.lng, mapData.target.lat],
      zoom: 14,
      scrollZoom: true,
      maxBounds: NYC_MAX_BOUNDS,
      minZoom: 10.5,
      maxZoom: 17.5,
    });
    map.addControl(new mapboxgl.NavigationControl(), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      addZones(map);
      addSwarm(map);
      addLogisticsPins(map);
      addTargetPin(map);
      const initialPaths = getFlightPaths();
      upsertFlightPaths(map, initialPaths);
      // Per-path plane animations (ADS-B polylines or corridor segments)
      startTrackPlaneAnimations(map, initialPaths);
      // Route source — empty at first, filled on hover
      map.addSource("route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-glow",
        type: "line",
        source: "route",
        paint: { "line-color": INK, "line-width": 10, "line-opacity": 0.15 },
      });
      map.addLayer({
        id: "route-line",
        type: "line",
        source: "route",
        paint: { "line-color": INK, "line-width": 3, "line-dasharray": [2, 2] },
      });
    });

    return () => {
      const swarmMarkers = markersRef.current;
      const planeMarkers = trackPlaneMarkersRef.current;
      const vertexMarkers = flightVertexMarkersRef.current;
      if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
      zonePopupRef.current?.remove();
      zonePopupRef.current = null;
      zoneHoveredIdRef.current = null;
      planeMarkers.forEach((m) => m.remove());
      trackPlaneMarkersRef.current = [];
      vertexMarkers.forEach((m) => m.remove());
      flightVertexMarkersRef.current = [];
      swarmMarkers.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
    };
  // Mount once per MapComponent instance (ResultsDashboard key resets on new scan).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Update route when activeRoute changes ───────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const source = map.getSource("route") as mapboxgl.GeoJSONSource | undefined;
    if (!source) return;

    if (!activeRoute) {
      source.setData({ type: "FeatureCollection", features: [] });
      map.flyTo({ center: [mapData.target.lng, mapData.target.lat], zoom: 14, duration: 800 });
      // Reset route line colors
      map.setPaintProperty("route-glow", "line-color", INK);
      map.setPaintProperty("route-line", "line-color", INK);
      return;
    }

    const card = logistics.find((c) => c.type === activeRoute);
    if (!card) return;

    const color = card.color;
    map.setPaintProperty("route-glow", "line-color", color);
    map.setPaintProperty("route-line", "line-color", color);

    source.setData({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "LineString",
            coordinates: [
              [mapData.target.lng, mapData.target.lat],
              [card.coordinates.lng, card.coordinates.lat],
            ],
          },
        },
      ],
    });

    map.fitBounds(
      [
        [Math.min(mapData.target.lng, card.coordinates.lng), Math.min(mapData.target.lat, card.coordinates.lat)],
        [Math.max(mapData.target.lng, card.coordinates.lng), Math.max(mapData.target.lat, card.coordinates.lat)],
      ],
      { padding: 80, duration: 800 }
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRoute, logistics, mapData.target.lat, mapData.target.lng]);

  // ── Update flight corridors when new scan data arrives ──────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const paths = getFlightPaths();

    const apply = () => {
      if (!map.isStyleLoaded()) return;

      upsertFlightPaths(map, paths);
      upsertFlightPathVertices(map, paths);

      // Always restart per-path animations on new scan data
      if (!paths.length) {
        trackPlaneMarkersRef.current.forEach((m) => m.remove());
        trackPlaneMarkersRef.current = [];
        flightVertexMarkersRef.current.forEach((m) => m.remove());
        flightVertexMarkersRef.current = [];
        if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
        trackRafRef.current = undefined;
      } else {
        startTrackPlaneAnimations(map, paths);
      }
    };

    // If the map isn't ready yet, queue until style loads (common on first scan)
    if (!map.isStyleLoaded()) {
      const onIdle = () => {
        if (!map.isStyleLoaded()) return;
        map.off("idle", onIdle);
        apply();
      };
      map.on("idle", onIdle);
      return () => {
        map.off("idle", onIdle);
      };
    }

    apply();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData.flight_path, mapData.flight_paths, showFlightFeature]);

  // ── Recenter map when the scanned property moves ────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const apply = () => {
      if (!map.isStyleLoaded()) return;
      map.flyTo({ center: [mapData.target.lng, mapData.target.lat], zoom: 14, duration: 800 });
    };

    if (!map.isStyleLoaded()) {
      const onIdle = () => {
        if (!map.isStyleLoaded()) return;
        map.off("idle", onIdle);
        apply();
      };
      map.on("idle", onIdle);
      return () => {
        map.off("idle", onIdle);
      };
    }

    apply();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapData.target.lat, mapData.target.lng]);

  // ── Helpers ─────────────────────────────────────────────────────────────────

  const getFlightPaths = () => {
    if (!showFlightFeature) return [];
    const raw = mapData.flight_paths?.filter(Boolean) ?? [];
    const paths = raw.length
      ? raw
      : mapData.flight_path
        ? [mapData.flight_path]
        : [];
    const radiusMi = mapData.scan_radius_miles ?? 2;
    return filterFlightPathsWithinRadius(paths, mapData.target, radiusMi);
  };

  const addZones = (map: mapboxgl.Map) => {
    if (!mapData.zones.length) return;

    const sourceId = "threat-zones";
    const layerId = "threat-zones-fill";

    map.addSource(sourceId, {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: mapData.zones.map((zone, i) => ({
          type: "Feature" as const,
          id: i,
          properties: {
            label: zone.label,
            color: zone.color,
            radius_meters: zone.radius_meters,
            detail: zone.detail ?? zoneKindLabel(zone.color),
          },
          geometry: {
            type: "Point" as const,
            coordinates: [zone.lng, zone.lat],
          },
        })),
      },
    });

    map.addLayer({
      id: layerId,
      source: sourceId,
      type: "circle",
      paint: {
        "circle-radius": [
          "interpolate",
          ["linear"],
          ["zoom"],
          10,
          ["/", ["get", "radius_meters"], 100],
          15,
          ["/", ["get", "radius_meters"], 10],
        ],
        "circle-color": ["get", "color"],
        "circle-opacity": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          0.38,
          0.15,
        ],
        "circle-stroke-color": ["get", "color"],
        "circle-stroke-width": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          3.5,
          2,
        ],
        "circle-stroke-opacity": [
          "case",
          ["boolean", ["feature-state", "hover"], false],
          1,
          0.6,
        ],
      },
    });

    const popup =
      zonePopupRef.current ??
      new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
        offset: 12,
      });
    zonePopupRef.current = popup;

    const clearHover = () => {
      if (zoneHoveredIdRef.current !== null) {
        map.setFeatureState(
          { source: sourceId, id: zoneHoveredIdRef.current },
          { hover: false }
        );
        zoneHoveredIdRef.current = null;
      }
      map.getCanvas().style.cursor = "";
      popup.remove();
    };

    map.on("mouseenter", layerId, (e) => {
      const feature = e.features?.[0];
      if (!feature) return;
      const id = feature.id;
      if (typeof id !== "number") return;

      clearHover();
      zoneHoveredIdRef.current = id;
      map.setFeatureState({ source: sourceId, id }, { hover: true });
      map.getCanvas().style.cursor = "pointer";

      const label = String(feature.properties?.label ?? "Municipal record");
      const color = String(feature.properties?.color ?? "#3b82f6");
      const detail = String(feature.properties?.detail ?? "");
      popup.setLngLat(e.lngLat).setHTML(popupHtml(label, color, [detail])).addTo(map);
    });

    map.on("mousemove", layerId, (e) => {
      if (popup.isOpen()) {
        popup.setLngLat(e.lngLat);
      }
    });

    map.on("mouseleave", layerId, clearHover);
  };

  const addSwarm = (map: mapboxgl.Map) => {
    mapData.swarm.forEach((pin) => {
      const color = SWARM_COLOR[pin.type] || "#57534E";
      // Outer node: Mapbox sets transform on this element for map position — never set transform here.
      const outer = document.createElement("div");
      outer.style.cssText = `
        width: 22px; height: 22px; cursor: pointer; pointer-events: auto;
        display: flex; align-items: center; justify-content: center;
      `;
      const inner = document.createElement("div");
      inner.style.cssText = `
        font-size: 12px; display: flex; align-items: center; justify-content: center;
        width: 100%; height: 100%;
        background: #ffffff; border: 1.5px solid ${color};
        border-radius: 50%; box-shadow: 0 1px 2px rgba(21,21,21,0.3);
        transition: transform 0.15s;
        transform-origin: center center;
      `;
      inner.textContent = SWARM_EMOJI[pin.type] || "📋";
      outer.appendChild(inner);

      // Popup shown on hover only — prevents icons from jumping on click
      const popup = new mapboxgl.Popup({
        offset: 14,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(popupHtml(pin.label, color, [pin.detail]));

      outer.addEventListener("mouseenter", () => {
        inner.style.transform = "scale(1.4)";
        outer.style.zIndex = "9999";
        popup.setLngLat([pin.lng, pin.lat]).addTo(map);
      });
      outer.addEventListener("mouseleave", () => {
        inner.style.transform = "";
        outer.style.zIndex = "";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
        .setLngLat([pin.lng, pin.lat])
        .addTo(map);
      markersRef.current.push(marker);
    });
  };

  const addLogisticsPins = (map: mapboxgl.Map) => {
    logistics.forEach((card) => {
      const pinEmoji = logisticsPinEmoji(card);
      const outer = document.createElement("div");
      outer.style.cssText = `
        width: 36px; height: 36px; cursor: pointer; pointer-events: auto;
        display: flex; align-items: center; justify-content: center;
      `;
      const inner = document.createElement("div");
      inner.style.cssText = `
        font-size: 19px; display: flex; align-items: center; justify-content: center;
        width: 100%; height: 100%;
        background: #ffffff; border: 2.5px solid ${safeColor(card.color)};
        border-radius: 50%; box-shadow: 0 2px 4px rgba(21,21,21,0.3);
        transition: transform 0.2s;
        transform-origin: center center;
      `;
      inner.textContent = pinEmoji;
      outer.appendChild(inner);

      const ratingLine =
        card.type.startsWith("dining-") && card.rating != null
          ? `★ ${card.rating.toFixed(1)}${card.review_count != null ? ` (${reviewCountLabel(card) ?? ""})` : ""}`
          : null;

      const popup = new mapboxgl.Popup({
        offset: 20,
        closeButton: false,
        closeOnClick: false,
        anchor: "bottom",
      }).setHTML(
        popupHtml(card.name, card.color, [
          `${card.category}, ${formatDistance(card.distance_value, card.distance_unit)} away`,
          ratingLine,
        ])
      );

      outer.addEventListener("mouseenter", () => {
        inner.style.transform = "scale(1.15)";
        popup.setLngLat([card.coordinates.lng, card.coordinates.lat]).addTo(map);
      });
      outer.addEventListener("mouseleave", () => {
        inner.style.transform = "";
        popup.remove();
      });

      const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
        .setLngLat([card.coordinates.lng, card.coordinates.lat])
        .addTo(map);
      markersRef.current.push(marker);
    });
  };

  const addTargetPin = (map: mapboxgl.Map) => {
    // Outer node is positioned by Mapbox (transform); the pulse animates an inner node only.
    const el = document.createElement("div");
    el.style.cssText = "width: 30px; height: 30px; cursor: pointer; z-index: 2;";
    const pulse = document.createElement("span");
    pulse.className = "pin-pulse";
    pulse.style.cssText =
      `position: absolute; left: 5px; top: 5px; width: 20px; height: 20px; border-radius: 9999px; background: ${TAXI};`;
    const dot = document.createElement("span");
    dot.style.cssText =
      `position: absolute; left: 5px; top: 5px; width: 20px; height: 20px; border-radius: 9999px; background: ${INK};` +
      ` border: 4px solid ${TAXI}; box-shadow: 0 0 0 2px ${INK}, 0 4px 10px rgba(21,21,21,0.4);`;
    el.append(pulse, dot);

    const popup = new mapboxgl.Popup({ offset: 18, closeButton: false })
      .setHTML(popupHtml("This address", TAXI, [`${mapData.target.lat.toFixed(5)}, ${mapData.target.lng.toFixed(5)}`]));

    const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
      .setLngLat([mapData.target.lng, mapData.target.lat])
      .setPopup(popup)
      .addTo(map);
    markersRef.current.push(marker);
  };

  const upsertFlightPathVertices = (map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    flightVertexMarkersRef.current.forEach((m) => m.remove());
    flightVertexMarkersRef.current = [];

    paths.forEach((p) => {
      const verts = p.path?.filter(Boolean) ?? [];
      if (verts.length < MIN_FLIGHT_PATH_POINTS) return;

      verts.forEach((c) => {
        const outer = document.createElement("div");
        outer.style.cssText =
          "width: 10px; height: 10px; display: flex; align-items: center; justify-content: center; pointer-events: none;";
        const inner = document.createElement("div");
        inner.style.cssText = `
          width: 6px; height: 6px; border-radius: 50%;
          background: #22d3ee; border: 1px solid #0e7490;
        `;
        outer.appendChild(inner);

        const marker = new mapboxgl.Marker({ element: outer, anchor: "center" })
          .setLngLat([c.lng, c.lat])
          .addTo(map);
        flightVertexMarkersRef.current.push(marker);
      });
    });
  };

  const upsertFlightPaths = (map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    const toLineCoords = (p: (typeof paths)[number]) => flightPathToLineLngLat(p);

    const data = {
      type: "FeatureCollection" as const,
      features: paths.map((p) => ({
        type: "Feature" as const,
        properties: { label: p.label },
        geometry: {
          type: "LineString" as const,
          coordinates: toLineCoords(p),
        },
      })),
    };

    const existing = map.getSource("flight-paths") as mapboxgl.GeoJSONSource | undefined;
    if (existing) {
      existing.setData(data);
      const hasRealTracks = paths.some((p) => (p.path?.length ?? 0) >= MIN_FLIGHT_PATH_POINTS);
      const dash = hasRealTracks ? null : ([2, 3] as [number, number]);
      map.setPaintProperty("flight-paths-line", "line-dasharray", dash as unknown as number[]);
      if (map.getLayer("flight-paths-glow")) {
        map.setPaintProperty("flight-paths-glow", "line-dasharray", dash as unknown as number[]);
      }
      return;
    }

    map.addSource("flight-paths", { type: "geojson", data });
    const hasRealTracks = paths.some((p) => (p.path?.length ?? 0) >= MIN_FLIGHT_PATH_POINTS);
    const dashPaint = hasRealTracks ? {} : { "line-dasharray": [2, 3] as [number, number] };
    const lineLayout = { "line-cap": "round" as const, "line-join": "round" as const };

    map.addLayer({
      id: "flight-paths-glow",
      type: "line",
      source: "flight-paths",
      layout: lineLayout,
      paint: {
        "line-color": "#22d3ee",
        "line-width": 11,
        "line-opacity": 0.3,
        "line-blur": 2.5,
        ...dashPaint,
      },
    });
    map.addLayer({
      id: "flight-paths-line",
      type: "line",
      source: "flight-paths",
      layout: lineLayout,
      paint: {
        "line-color": "#06b6d4",
        "line-width": 3,
        ...dashPaint,
        "line-opacity": 0.88,
      },
    });
  };

  const startTrackPlaneAnimations = useCallback((map: mapboxgl.Map, paths: ReturnType<typeof getFlightPaths>) => {
    // Clean up any previous markers/raf
    if (trackRafRef.current) cancelAnimationFrame(trackRafRef.current);
    trackRafRef.current = undefined;
    trackPlaneMarkersRef.current.forEach((m) => m.remove());
    trackPlaneMarkersRef.current = [];

    const routes = paths
      .slice(0, 3)
      .map((p) => {
        const coords = flightPathToRouteLatLng(p);
        return coords.length >= 2 ? coords : [];
      })
      .filter((c) => c.length >= 2);

    if (!routes.length) return;

    const routeMetrics = routes
      .map((route) => {
        const cumulative: number[] = [0];
        for (let i = 1; i < route.length; i++) {
          const prev = route[i - 1];
          const cur = route[i];
          const meters = new mapboxgl.LngLat(prev.lng, prev.lat).distanceTo(
            new mapboxgl.LngLat(cur.lng, cur.lat)
          );
          cumulative.push(cumulative[i - 1] + meters);
        }
        const totalMeters = cumulative[cumulative.length - 1] ?? 0;
        return totalMeters > 0 ? { route, cumulative, totalMeters } : null;
      })
      .filter((m): m is { route: { lat: number; lng: number }[]; cumulative: number[]; totalMeters: number } => Boolean(m));

    if (!routeMetrics.length) return;

    trackProgressRef.current = routes.map(() => 0);
    trackLastTimeRef.current = 0;

    // Create a plane marker per route
    trackPlaneMarkersRef.current = routeMetrics.map(({ route }) => {
      const el = document.createElement("div");
      el.style.cssText =
        "font-size: 18px; line-height: 1; filter: drop-shadow(0 1px 2px rgba(21,21,21,0.45));";
      el.textContent = "✈️";
      return new mapboxgl.Marker({ element: el, anchor: "center" })
        .setLngLat([route[0].lng, route[0].lat])
        .addTo(map);
    });

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const step = (time: number) => {
      if (!trackLastTimeRef.current) trackLastTimeRef.current = time;
      const delta = Math.min(time - trackLastTimeRef.current, 100);
      trackLastTimeRef.current = time;

      const zoom = map.getZoom();
      // Keep it subtle; faster when zoomed out.
      const speedMultiplier = Math.pow(2, 14 - zoom);
      const baseSpeed = 1 / 90000; // progress per ms

      routeMetrics.forEach(({ route, cumulative, totalMeters }, idx) => {
        let p = trackProgressRef.current[idx] ?? 0;
        p += delta * baseSpeed * speedMultiplier;
        if (p > 1) p %= 1;
        trackProgressRef.current[idx] = p;

        const targetMeters = p * totalMeters;
        let i = 0;
        while (i < cumulative.length - 2 && cumulative[i + 1] < targetMeters) {
          i++;
        }

        const a = route[i];
        const b = route[i + 1];
        const segStart = cumulative[i];
        const segEnd = cumulative[i + 1];
        const f = (targetMeters - segStart) / Math.max(1, segEnd - segStart);
        const lat = a.lat + (b.lat - a.lat) * f;
        const lng = a.lng + (b.lng - a.lng) * f;
        trackPlaneMarkersRef.current[idx]?.setLngLat([lng, lat]);
      });

      trackRafRef.current = requestAnimationFrame(step);
    };

    trackRafRef.current = requestAnimationFrame(step);
  }, []);

  const shown = mapData.swarm.length;
  const total = mapData.swarm_location_total ?? shown;
  const totalText = `${formatCount(total)}${mapData.swarm_total_is_lower_bound ? "+" : ""}`;
  const locationsNote =
    total > shown || mapData.swarm_total_is_lower_bound
      ? `Showing ${formatCount(shown)} of ${totalText} real NYC locations within ${scanRadiusLabel}`
      : `${formatCount(shown)} real NYC ${plural(shown, "location")} within ${scanRadiusLabel}`;
  // A source that did not answer has no pins: say so, so an empty or thin map is not read as "no records".
  const missingPinSources = (dataSources ?? [])
    .filter((s) => PIN_SOURCE_KEYS.includes(s.key) && s.status === "unavailable")
    .map((s) => s.label);
  const presentTypes = new Set<string>(mapData.swarm.map((p) => p.type));
  const legend = SWARM_LEGEND.filter((row) => row.types.some((t) => presentTypes.has(t)));

  const flightPaths = getFlightPaths();

  return (
    <section aria-labelledby="map-heading" className="flex min-w-0 flex-col">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between sm:gap-6">
        <div className="min-w-0">
          <h2 id="map-heading" className="heading text-[1.875rem] sm:text-[2.125rem]">
            Map of real records
          </h2>
          <p className="mt-1 text-[15px] text-fg-2">{locationsNote}</p>
          {missingPinSources.length > 0 && (
            <p className="mt-1 text-[15px] font-semibold text-fg">
              No pins for {joinLabels(missingPinSources)}: unavailable during this scan.
            </p>
          )}
        </div>
        <p className="hidden shrink-0 pb-0.5 text-sm text-fg-3 md:block">Scroll to zoom. Hover a pin for details.</p>
      </div>

      <div className="mt-4 overflow-hidden rounded-lg border-2 border-fg bg-surface-2">
        <div ref={containerRef} className="h-[380px] w-full sm:h-[460px] lg:h-[600px]" />
      </div>

      <div className="mt-4">
        <ul className="flex flex-wrap gap-x-5 gap-y-2 text-sm text-fg-2" aria-label="Map legend">
          <li className="flex items-center gap-1.5">
            <span aria-hidden className="h-3.5 w-3.5 rounded-full border-[3px] border-brand bg-fg ring-1 ring-fg" /> This
            address
          </li>
          {legend.map((row) => (
            <li key={row.emoji} className="flex items-center gap-1.5">
              <span aria-hidden>{row.emoji}</span> {row.label(presentTypes)}
            </li>
          ))}
          <li className="flex items-center gap-1.5">
            <span aria-hidden>🚇</span> Transit
          </li>
          <li className="flex items-center gap-1.5">
            <span aria-hidden>✈️</span> Airport
          </li>
          {mapData.zones.length > 0 && (
            <li className="flex items-center gap-1.5">
              <span aria-hidden className="h-3.5 w-3.5 rounded-full border-2 border-fg-3 bg-fg-3/20" /> Shaded circles:
              newest records
            </li>
          )}
          {showFlightFeature && flightPaths.length > 0 && (
            <li className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-1 w-6 rounded-full bg-cyan-400" /> Recent flight track
            </li>
          )}
        </ul>
        {showFlightFeature && flightPaths.some((p) => (p.path?.length ?? 0) >= MIN_FLIGHT_PATH_POINTS) && (
          <p className="mt-2 text-sm text-fg-3">
            Cyan lines are recent real flight tracks near this address, not every flight.
          </p>
        )}
      </div>
    </section>
  );
}
