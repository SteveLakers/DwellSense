"use client";

import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import HeroSection from "@/components/HeroSection";
import { HOME_RESET_EVENT } from "@/components/HomeLink";
import HomeSections from "@/components/HomeSections";
import ResultsDashboard from "@/components/ResultsDashboard";
import ScanLoading from "@/components/ScanLoading";
import { SAMPLE_ADDRESS } from "@/lib/site";
import { ScanResult } from "@/lib/types";

type View = "hero" | "loading" | "results";

export default function HomeClient({ heroAside }: { heroAside?: ReactNode }) {
  const [view, setView] = useState<View>("hero");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isApiReady, setIsApiReady] = useState(false);
  const [bulletsRefreshing, setBulletsRefreshing] = useState(false);
  const [scanAddress, setScanAddress] = useState("");

  const pendingResult = useRef<ScanResult | null>(null);
  // Bumped by every new scan and reset, so a response for a scan the user left is ignored.
  const scanGeneration = useRef(0);

  const handleScan = async (address: string) => {
    const generation = ++scanGeneration.current;
    setError(null);
    setIsApiReady(false);
    setScanAddress(address);
    pendingResult.current = null;
    setView("loading");
    window.scrollTo(0, 0);

    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, defer_gemini: true }),
        signal: AbortSignal.timeout(295_000),
      });

      const data = await res.json();
      if (generation !== scanGeneration.current) return;

      if (!res.ok) {
        throw new Error(data.error || "Scan failed. Please try again.");
      }

      pendingResult.current = data as ScanResult;
      setIsApiReady(true);
    } catch (err) {
      if (generation !== scanGeneration.current) return;
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setError(msg);
      setView("hero");
    }
  };

  const handleResultReady = () => {
    if (pendingResult.current) {
      setResult(pendingResult.current);
      setView("results");
      window.scrollTo(0, 0);
    }
  };

  const handleReset = useCallback(() => {
    scanGeneration.current += 1;
    setResult(null);
    setError(null);
    setIsApiReady(false);
    setBulletsRefreshing(false);
    pendingResult.current = null;
    setView("hero");
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    window.addEventListener(HOME_RESET_EVENT, handleReset);
    return () => window.removeEventListener(HOME_RESET_EVENT, handleReset);
  }, [handleReset]);

  useEffect(() => {
    if (view !== "results" || !result) return;
    if (result.gemini_status !== "pending" || !result.bullets_token) return;

    const token = result.bullets_token;
    let cancelled = false;
    setBulletsRefreshing(true);

    (async () => {
      try {
        const res = await fetch("/api/scan/bullets", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ bullets_token: token }),
          signal: AbortSignal.timeout(295_000),
        });
        const data = await res.json();
        if (cancelled || !res.ok) return;

        setResult((prev) =>
          prev
            ? {
                ...prev,
                threat_cards: data.threat_cards ?? prev.threat_cards,
                gemini_configured: data.gemini_configured ?? prev.gemini_configured,
                gemini_status: data.gemini_status ?? prev.gemini_status,
                gemini_latency_ms: data.gemini_latency_ms ?? prev.gemini_latency_ms,
                bullets_token: null,
              }
            : prev
        );
      } catch {
        // Keep fact-locked template bullets if the deferred Gemini call fails.
      } finally {
        if (!cancelled) setBulletsRefreshing(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, result?.bullets_token, result?.gemini_status]);

  return (
    <>
      <main className="relative z-10 flex w-full flex-1 flex-col">
        {view === "hero" && (
          <>
            <HeroSection onScan={handleScan} isLoading={false} error={error} aside={heroAside} />
            <HomeSections
              onSample={() => void handleScan(SAMPLE_ADDRESS)}
              sampleLabel="Union Square in Manhattan"
            />
          </>
        )}

        {view === "loading" && (
          <ScanLoading address={scanAddress} onComplete={handleResultReady} isApiReady={isApiReady} />
        )}

        {view === "results" && result && (
          <ResultsDashboard
            result={result}
            onReset={handleReset}
            bulletsRefreshing={bulletsRefreshing}
          />
        )}
      </main>
    </>
  );
}
