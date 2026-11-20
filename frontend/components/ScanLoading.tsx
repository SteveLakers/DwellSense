"use client";

import { useEffect, useRef } from "react";
import { FLIGHT_NOISE_PAUSED, SCAN_RADIUS_MILES } from "@/lib/site";

/** Queried in parallel by POST /scan; the list is what is being checked, not a progress report. */
const CHECKING = [
  "NYPD complaints",
  "Crime-in-progress calls",
  "311 service requests",
  "DOB construction permits",
  "Residential evictions",
  ...(FLIGHT_NOISE_PAUSED ? [] : ["Aircraft positions"]),
  "Transit and groceries",
  "Top-rated dining",
];

/** Sweep only, never blips: nothing has been found yet. The outer ring is the scan radius. */
function Radar({ className = "", labelled = false }: { className?: string; labelled?: boolean }) {
  return (
    <svg viewBox="0 0 200 200" className={className} aria-hidden="true">
      <circle cx="100" cy="100" r="96" className="fill-ink-2" />
      <g className="fill-none stroke-ink-line" strokeWidth={1}>
        <circle cx="100" cy="100" r="72" />
        <circle cx="100" cy="100" r="48" />
        <circle cx="100" cy="100" r="24" />
        <path d="M4 100h192M100 4v192" />
      </g>
      <g className="radar-sweep">
        <path d="M100 100L16.86 52A96 96 0 0 1 44.94 21.36Z" className="fill-brand" fillOpacity={0.07} />
        <path d="M100 100L44.94 21.36A96 96 0 0 1 75.15 7.27Z" className="fill-brand" fillOpacity={0.16} />
        <path d="M100 100L75.15 7.27A96 96 0 0 1 100 4Z" className="fill-brand" fillOpacity={0.3} />
        <path d="M100 100V4" className="stroke-brand" strokeWidth={2} strokeLinecap="round" />
      </g>
      <circle cx="100" cy="100" r="96" className="fill-none stroke-ink-muted" strokeWidth={1.5} />
      <circle cx="100" cy="100" r="5" className="fill-brand" />
      {labelled ? (
        <text x="104" y="16" className="fill-ink-muted text-[9px] font-semibold">
          {SCAN_RADIUS_MILES} mi
        </text>
      ) : null}
    </svg>
  );
}

interface Props {
  address: string;
  onComplete: () => void;
  isApiReady: boolean;
}

export default function ScanLoading({ address, onComplete, isApiReady }: Props) {
  const hasCompleted = useRef(false);

  useEffect(() => {
    if (!isApiReady || hasCompleted.current) return;
    hasCompleted.current = true;
    onComplete();
  }, [isApiReady, onComplete]);

  return (
    <section aria-labelledby="scan-loading-title" className="fade-in w-full">
      <div className="on-ink grain-ink bg-ink text-white">
        <div className="wrap pb-12 pt-7 sm:pt-9 lg:pb-16">
          <div aria-hidden className="h-[3px] bg-white" />
          <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-center lg:gap-16">
            <div className="min-w-0">
              <div className="mt-8 flex items-center justify-between gap-6">
                <p role="status" className="text-[15px] font-semibold text-brand">
                  Scanning address…
                </p>
                <Radar className="h-16 w-16 shrink-0 lg:hidden" />
              </div>
              <h1 id="scan-loading-title" className="display mt-3 break-words text-[clamp(2.6rem,6.6vw,5.4rem)]">
                {address}
              </h1>
              <p className="mt-4 max-w-xl text-lg leading-relaxed text-ink-muted">
                Pulling official records within {SCAN_RADIUS_MILES} miles and comparing them with the rest of NYC.
              </p>
              <div className="mt-10 h-1.5 overflow-hidden rounded-sm bg-ink-line" aria-hidden>
                <div className="progress-indeterminate h-full w-2/5 bg-brand" />
              </div>
            </div>
            <Radar labelled className="mt-8 hidden w-full lg:block" />
          </div>
        </div>
      </div>

      <div className="wrap mb-24 mt-12">
        <h2 className="text-[15px] font-semibold text-fg-2">Checking now</h2>
        <ul className="mt-4 grid border-t-[3px] border-fg sm:grid-cols-2 sm:gap-x-10">
          {CHECKING.map((name, i) => (
            <li key={name} className="flex items-center justify-between gap-4 border-b border-line py-3.5">
              <span className="heading text-[1.3125rem]">{name}</span>
              <span
                aria-hidden
                className="inline-flex shrink-0 items-center gap-2 rounded-sm bg-ink px-2.5 py-1 text-[13px] font-semibold text-brand"
              >
                <span
                  className="h-1.5 w-1.5 rounded-full bg-brand motion-safe:animate-pulse"
                  style={{ animationDelay: `${i * 0.18}s` }}
                />
                Checking
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
