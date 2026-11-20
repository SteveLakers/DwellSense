import { Plane } from "lucide-react";
import { FlightExposure } from "@/lib/types";
import {
  flightAltitudeNote,
  flightElevationBadge,
  flightElevationBadgeClasses,
  flightFrequencyLabel,
  flightNoiseSummary,
  flightRateDisplay,
  formatObservationWindow,
} from "@/lib/flightExposureDisplay";

export default function FlightNoisePanel({ exposure }: { exposure: FlightExposure }) {
  const night = flightRateDisplay(exposure.night_overflights_per_hour);
  const day = flightRateDisplay(exposure.day_overflights_per_hour);
  const altitude = flightAltitudeNote(exposure);

  return (
    <section aria-labelledby="flight-heading" className="wrap mt-20 lg:mt-28">
      <div className="grid gap-10 border-t-[3px] border-fg pt-8 lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-5">
          <div className="flex flex-wrap items-center gap-3">
            <Plane className="h-5 w-5 text-fg-2" aria-hidden />
            <span
              className={`inline-flex rounded border px-2 py-0.5 text-sm font-semibold ${flightElevationBadgeClasses(exposure)}`}
              title="Compared to typical plane traffic within ~2 mi across NYC"
            >
              {flightElevationBadge(exposure)}
            </span>
          </div>
          <h2 id="flight-heading" className="heading mt-4 text-[1.875rem] sm:text-[2.125rem]">
            Flight noise
          </h2>
          <p className="mt-2 text-[17px] leading-relaxed text-fg">{flightNoiseSummary(exposure)}</p>
          {altitude ? <p className="mt-3 text-[15px] font-semibold text-fg">{altitude}</p> : null}
        </div>

        {exposure.data_quality !== "unavailable" ? (
          <dl className="grid grid-cols-2 gap-x-6 lg:col-span-7">
            {(
              [
                { label: "Overnight", hours: "10 PM–7 AM", rate: night, raw: exposure.night_overflights_per_hour },
                { label: "Daytime", hours: "7 AM–10 PM", rate: day, raw: exposure.day_overflights_per_hour },
              ] as const
            ).map((tile) => (
              <div key={tile.label} className="min-w-0 border-l-2 border-fg pl-4 sm:pl-6">
                <dt>
                  <span className="block text-[15px] font-semibold text-fg">{tile.label}</span>
                  <span className="block text-sm text-fg-3">{tile.hours}</span>
                </dt>
                <dd className="mt-4">
                  <span className="figure block text-[3.75rem] sm:text-[5rem]">{tile.rate.value}</span>
                  <span className="mt-1 block text-[15px] text-fg-2">{tile.rate.unit}</span>
                  {tile.raw >= 0.2 ? <span className="tag mt-3">{flightFrequencyLabel(tile.raw)}</span> : null}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
      <p className="mt-8 max-w-3xl text-sm leading-relaxed text-fg-3">{formatObservationWindow(exposure)}</p>
    </section>
  );
}
