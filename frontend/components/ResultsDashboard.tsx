"use client";

import { useState, useCallback, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { CircleAlert, Download, LoaderCircle } from "lucide-react";
import { ScanResult } from "@/lib/types";
import { buildProximityCards } from "@/lib/proximityCards";
import { formatCoordinates, splitAddress } from "@/lib/format";
import DangerBanner from "./DangerBanner";
import DataSourcesPanel from "./DataSourcesPanel";
import FlightNoisePanel from "./FlightNoisePanel";
import NearbyPlaces from "./NearbyPlaces";
import ThreatCards, { scrollToThreatCard } from "./ThreatCards";
import SideAds, { ScanSummaryProps } from "./SideAds";

// Mapbox must only render on the client side (no SSR)
const MapComponent = dynamic(() => import("./MapComponent"), {
  ssr: false,
  loading: () => <div className="h-[520px] animate-pulse rounded-lg border-2 border-fg/20 bg-surface-2 sm:h-[600px] lg:h-[740px]" />,
});

interface ActionsProps {
  onDownload: () => void;
  onReset: () => void;
  pdfLoading: boolean;
  bulletsRefreshing: boolean;
  pdfError: string | null;
  /** "ink" sits on the black address band, "brand" on the yellow closing band. */
  tone: "ink" | "brand";
}

function ReportActions({ onDownload, onReset, pdfLoading, bulletsRefreshing, pdfError, tone }: ActionsProps) {
  const onInk = tone === "ink";
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          onClick={onDownload}
          disabled={pdfLoading || bulletsRefreshing}
          className={`${onInk ? "btn-brand-on-ink" : "btn-ink"} h-12`}
        >
          {pdfLoading || bulletsRefreshing ? (
            <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Download className="h-4 w-4" aria-hidden />
          )}
          {pdfLoading ? "Generating PDF…" : bulletsRefreshing ? "Refining summaries…" : "Download full report"}
        </button>
        <button type="button" onClick={onReset} className={`${onInk ? "btn-outline-on-ink" : "btn-outline"} h-12`}>
          Check another address
        </button>
      </div>
      {pdfError ? (
        <p
          role="alert"
          className={`flex items-start gap-2 text-sm font-medium ${onInk ? "text-[#FFB4A3]" : "text-bad"}`}
        >
          <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {pdfError}
        </p>
      ) : null}
    </div>
  );
}

interface Props {
  result: ScanResult;
  onReset: () => void;
  bulletsRefreshing?: boolean;
}

export default function ResultsDashboard({ result, onReset, bulletsRefreshing = false }: Props) {
  const [hoverRoute, setHoverRoute] = useState<string | null>(null);
  const [pinnedRoute, setPinnedRoute] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [checkedOn] = useState(() =>
    new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
  );
  const mapAnchorRef = useRef<HTMLDivElement>(null);

  const activeRoute = hoverRoute ?? pinnedRoute;
  const address = splitAddress(result.formatted_address);
  const radiusMi = result.map_data.scan_radius_miles ?? 2;
  const showFlight = Boolean(result.flight_exposure?.show_flight_feature);

  const proximityCards = useMemo(
    () => buildProximityCards(result.logistics, result.dining),
    [result.logistics, result.dining],
  );

  const sideSummary = useMemo((): ScanSummaryProps => {
    const paths = showFlight
      ? result.map_data.flight_paths?.length
        ? result.map_data.flight_paths
        : result.map_data.flight_path
          ? [result.map_data.flight_path]
          : []
      : [];
    return {
      score: result.danger_score,
      scoreAvailable: result.score_available !== false,
      riskLabel: result.risk_label,
      swarmTotalIsLowerBound: Boolean(result.map_data.swarm_total_is_lower_bound),
      address: result.formatted_address,
      swarmShown: result.map_data.swarm.length,
      swarmTotal: result.map_data.swarm_location_total ?? null,
      scanRadiusMi: radiusMi,
      flightPathCount: paths.length,
      showFlightFeature: showFlight,
      flightElevation: result.flight_exposure?.elevation_level ?? null,
      threatCardCount: result.threat_cards.length,
    };
  }, [result, radiusMi, showFlight]);

  const handleScrollToCard = useCallback((cardId: string) => {
    scrollToThreatCard(cardId);
  }, []);

  const handleTogglePin = useCallback((type: string) => {
    setPinnedRoute((prev) => (prev === type ? null : type));
    const map = mapAnchorRef.current;
    if (map) {
      const rect = map.getBoundingClientRect();
      if (rect.bottom < 120 || rect.top > window.innerHeight - 120) {
        map.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }, []);

  const handleDownloadPdf = async () => {
    setPdfError(null);
    if (!result.dossier_token) {
      setPdfError("PDF report unavailable. Check the address again to generate a fresh report.");
      return;
    }
    setPdfLoading(true);
    try {
      const res = await fetch("/api/pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dossier_token: result.dossier_token,
          danger_score: result.danger_score,
          risk_level: result.risk_level,
          risk_label: result.risk_label,
          risk_description: result.risk_description,
          banner_driver: result.banner_driver ?? null,
          threat_cards: result.threat_cards,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || err.detail || "PDF generation failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `ZerMap-Full-Data-Report-${result.formatted_address.replace(/[^a-z0-9]/gi, "_")}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setPdfError(err instanceof Error ? err.message : "PDF download failed. Please try again.");
    } finally {
      setPdfLoading(false);
    }
  };

  const actionProps = {
    onDownload: () => void handleDownloadPdf(),
    onReset,
    pdfLoading,
    bulletsRefreshing,
    pdfError,
  };

  return (
    <>
      <SideAds summary={sideSummary} />
      <div className="fade-in relative z-20 w-full">
        <header className="on-ink grain-ink bg-ink text-white">
          <div className="wrap pb-10 pt-7 sm:pb-12 sm:pt-9">
            <div aria-hidden className="h-[3px] bg-white" />
            <div className="mt-8 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between lg:gap-12">
              <div className="min-w-0">
                <h1 className="display break-words text-[clamp(2.6rem,6.6vw,5.4rem)]">{address.line1}</h1>
                {address.line2 ? <p className="mt-3 text-lg text-ink-muted sm:text-xl">{address.line2}</p> : null}
                <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-2 text-[15px]">
                  <div className="flex gap-2">
                    <dt className="text-ink-muted">Checked</dt>
                    <dd className="font-semibold">{checkedOn}</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink-muted">Records within</dt>
                    <dd className="font-semibold">{radiusMi} mi</dd>
                  </div>
                  <div className="flex gap-2">
                    <dt className="text-ink-muted">Centered on</dt>
                    <dd className="font-semibold tnum">{formatCoordinates(result.coordinates)}</dd>
                  </div>
                </dl>
              </div>
              <div className="shrink-0">
                <ReportActions {...actionProps} tone="ink" />
              </div>
            </div>
          </div>
        </header>

        <DangerBanner result={result} onScrollToCard={handleScrollToCard} />

        <div
          ref={mapAnchorRef}
          className="wrap mt-16 grid scroll-mt-20 grid-cols-1 gap-8 lg:mt-20 lg:grid-cols-[minmax(0,1fr)_360px] lg:gap-6"
        >
          <MapComponent
            key={`${result.coordinates.lat},${result.coordinates.lng}`}
            mapData={result.map_data}
            logistics={proximityCards}
            activeRoute={activeRoute}
            flightExposure={result.flight_exposure}
            dataSources={result.data_sources ?? []}
          />
          <NearbyPlaces
            cards={proximityCards}
            activeType={activeRoute}
            pinnedType={pinnedRoute}
            onHover={setHoverRoute}
            onTogglePin={handleTogglePin}
          />
        </div>

        {showFlight && result.flight_exposure ? <FlightNoisePanel exposure={result.flight_exposure} /> : null}

        <ThreatCards cards={result.threat_cards} bulletsRefreshing={bulletsRefreshing} />

        <DataSourcesPanel dataSources={result.data_sources ?? []} comparisonAsOf={result.nyc_comparison_as_of} />

        <section aria-labelledby="take-report" className="grain-paper mt-20 bg-brand lg:mt-28">
          <div className="wrap flex flex-col gap-8 py-12 md:py-16 lg:flex-row lg:items-end lg:justify-between">
            <div className="max-w-2xl">
              <h2 id="take-report" className="display-xl text-[3.25rem] sm:text-[4.75rem]">
                Take the full report with you
              </h2>
              <p className="mt-4 text-lg leading-relaxed">
                Each card’s supporting records, plus {showFlight ? "dining and flight details" : "dining details"},
                with links that open every source already filtered to this area.
              </p>
            </div>
            <div className="shrink-0">
              <ReportActions {...actionProps} tone="brand" />
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
