"use client";

import { useState, type ReactNode } from "react";
import { CircleAlert } from "lucide-react";
import Ticker from "@/components/Ticker";
import { EXAMPLE_ADDRESS } from "@/lib/site";

interface Props {
  onScan: (address: string) => void;
  isLoading: boolean;
  error?: string | null;
  /** Server-rendered illustration shown beside the form. */
  aside?: ReactNode;
}

export default function HeroSection({ onScan, isLoading, error, aside }: Props) {
  const [address, setAddress] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onScan(address.trim() || EXAMPLE_ADDRESS);
  };

  return (
    <section className="on-ink grain-ink relative overflow-hidden bg-ink text-white">
      <div className="wrap pb-16 pt-7 sm:pt-9 lg:grid lg:grid-cols-[minmax(0,1fr)_min(36%,31rem)] lg:gap-x-10 xl:grid-cols-[minmax(0,1fr)_min(40%,31rem)]">
        <div aria-hidden className="h-[3px] bg-white lg:col-span-2" />

        <div className="mt-10 lg:mt-14">
          <h1 className="display-xl text-[clamp(3.9rem,10vw,9.5rem)]">
            <span className="-mb-[0.08em] block overflow-hidden pb-[0.14em]">
              <span className="rise">Don’t sign a</span>
            </span>{" "}
            <span className="-mb-[0.08em] block overflow-hidden pb-[0.14em]">
              <span className="rise rise-2">blind lease.</span>
            </span>
          </h1>
          <p className="fade-in mt-6 max-w-[30rem] text-lg leading-relaxed text-ink-muted sm:text-xl">
            Landlords sell the layout. We show you the block, using official NYC data.
          </p>

          <form onSubmit={handleSubmit} className="mt-10 max-w-[40rem] sm:mt-12">
            <label htmlFor="scan-address" className="block text-[15px] font-semibold text-white">
              NYC address you’re considering
            </label>
            <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:gap-0">
              <input
                id="scan-address"
                name="address"
                type="text"
                autoComplete="street-address"
                value={address}
                onChange={(e) => setAddress(e.target.value)}
                placeholder={EXAMPLE_ADDRESS}
                className="h-16 min-w-0 rounded border-2 border-white bg-white px-4 text-lg text-fg sm:flex-1 sm:rounded-r-none"
              />
              <button
                type="submit"
                disabled={isLoading}
                className="btn-brand-on-ink h-16 shrink-0 px-7 text-lg sm:rounded-l-none sm:border-l-0"
              >
                {isLoading ? "Checking…" : "Check this address"}
              </button>
            </div>

            {error && (
              <p
                role="alert"
                className="mt-4 flex items-start gap-2.5 rounded border-2 border-bad bg-bad-soft px-4 py-3 text-[15px] font-medium text-bad"
              >
                <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {error}
              </p>
            )}
          </form>
        </div>

        {aside ? <div className="mt-14 max-w-md lg:max-w-none">{aside}</div> : null}
      </div>
      <Ticker />
    </section>
  );
}
