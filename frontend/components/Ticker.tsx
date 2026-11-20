"use client";

import { useState } from "react";
import { Pause, Play } from "lucide-react";
import { FLIGHT_NOISE_PAUSED } from "@/lib/site";

/** What every report checks (no counts: the zipper only names the sources). */
const ITEMS = [
  "NYPD complaints",
  "Crime-in-progress calls",
  "311 service requests",
  "Noise complaints",
  "DOB construction permits",
  "Marshal evictions",
  ...(FLIGHT_NOISE_PAUSED ? [] : ["Planes overhead"]),
  "Subway, train and bus",
  "Groceries",
  "Top-rated dining",
];

function Row() {
  return (
    <ul className="flex shrink-0 items-center">
      {ITEMS.map((item) => (
        <li key={item} className="flex items-center gap-7 pr-7">
          <span className="heading whitespace-nowrap text-[1.375rem] uppercase leading-none tracking-[0.01em]">{item}</span>
          <span className="h-2.5 w-2.5 rotate-45 bg-fg" />
        </li>
      ))}
    </ul>
  );
}

/** Times Square-style zipper under the homepage hero. Decorative: the same list is in the sections below. */
export default function Ticker() {
  const [paused, setPaused] = useState(false);

  return (
    <div
      className="ticker grain-paper relative flex h-14 items-center overflow-hidden border-y-2 border-fg bg-brand text-fg"
      data-paused={paused}
    >
      <div className="ticker-track" aria-hidden>
        <Row />
        <Row />
      </div>
      <button
        type="button"
        onClick={() => setPaused((p) => !p)}
        aria-label={paused ? "Play the moving ticker" : "Pause the moving ticker"}
        className="absolute inset-y-0 right-0 flex w-14 items-center justify-center border-l-2 border-fg bg-fg text-brand transition-colors hover:bg-ink-2 focus-visible:shadow-none focus-visible:outline-brand focus-visible:outline-offset-[-6px] motion-reduce:hidden"
      >
        {paused ? <Play className="h-4 w-4 fill-current" aria-hidden /> : <Pause className="h-4 w-4 fill-current" aria-hidden />}
      </button>
    </div>
  );
}
