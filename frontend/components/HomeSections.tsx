import Link from "next/link";
import SectionHeading from "@/components/SectionHeading";
import { FLIGHT_NOISE_PAUSED } from "@/lib/site";

const REPORT_PARTS: { title: string; body: string }[] = [
  {
    title: "Wellness Score",
    body:
      "0 to 100, from NYPD complaints, 311 requests, active construction permits and residential evictions " +
      "within 2 miles, compared with apartment locations sampled across NYC.",
  },
  {
    title: "Threat cards",
    body:
      "Evictions, crime-in-progress calls, NYPD complaints, construction, noise and 311 requests, each with " +
      "its exact count, date range and how it compares with the rest of NYC.",
  },
  {
    title: "Map of real records",
    body: "Pins for the newest NYPD complaints, 311 requests and DOB permits around the address.",
  },
  {
    title: "Getting around",
    body: "Nearest subway, train and bus stops, groceries, airport, shopping and top-rated restaurants.",
  },
  {
    title: "Flight noise",
    body: FLIGHT_NOISE_PAUSED
      ? "Paused for now: our aircraft-position source is limiting how much we can record, so reports leave " +
        "it out until that’s fixed."
      : "Flags blocks where planes pass overhead more often than at most NYC apartment locations, from the last " +
        "7 days of aircraft positions.",
  },
  {
    title: "Full PDF report",
    body: "Every count with its source and dates, plus links that open each source already filtered to the area.",
  },
];

const STEPS: { title: string; body: string }[] = [
  { title: "Enter an address", body: "Any street address or place in New York City." },
  {
    title: "We pull official records",
    body:
      "NYPD complaints and crime-in-progress calls, 311 requests, DOB permits and evictions within 2 miles" +
      (FLIGHT_NOISE_PAUSED ? "." : ", plus planes passing overhead."),
  },
  {
    title: "See how it compares",
    body:
      "Each count is compared with apartment locations sampled across NYC, so “higher” means higher for " +
      "New York.",
  },
];

// Same weights as _SCORE_FACTORS in backend/services/threat_card_layout.py. Swatches sit on the ink panel.
const WEIGHTS: { label: string; pct: number; swatch: string; edge: string }[] = [
  { label: "NYPD complaints", pct: 40, swatch: "bg-brand", edge: "border-brand" },
  { label: "311 requests", pct: 26, swatch: "bg-white", edge: "border-white" },
  { label: "Residential evictions", pct: 20, swatch: "bg-[#A3A29A]", edge: "border-[#A3A29A]" },
  { label: "Construction permits", pct: 14, swatch: "bg-[#6B6A62]", edge: "border-[#6B6A62]" },
];

const SOURCES: { name: string; from: string; covers: string }[] = [
  { name: "NYPD Complaint Data", from: "NYC Open Data", covers: "NYPD’s newest 30 days (published quarterly)" },
  { name: "NYPD Calls for Service", from: "NYC Open Data", covers: "Crime-in-progress calls, NYPD’s newest 30 days" },
  { name: "311 Service Requests", from: "NYC Open Data", covers: "Last 30 days, updated daily" },
  { name: "DOB NOW and DOB Permit Issuance", from: "NYC Open Data", covers: "Active permits issued in the last 90 days" },
  { name: "Evictions", from: "NYC Open Data", covers: "Carried out by NYC Marshals, last 180 days" },
  {
    name: "Aircraft positions (ADS-B)",
    from: "adsb.lol",
    covers: FLIGHT_NOISE_PAUSED ? "Flight noise is paused for now" : "Last 7 days",
  },
  {
    name: "Places, transit and dining",
    from: "Google Places",
    covers: "Nearest stops, groceries, airport, shopping and top-rated restaurants",
  },
  { name: "Address lookup and maps", from: "Mapbox", covers: "Finds the address and draws the map" },
  { name: "Takeaway lines on cards", from: "Google Gemini", covers: "Counts and comparisons come straight from the data" },
];

interface Props {
  onSample: () => void;
  sampleLabel: string;
}

export default function HomeSections({ onSample, sampleLabel }: Props) {
  return (
    <div className="w-full">
      <section aria-labelledby="what-you-get" className="wrap mt-20 lg:mt-28">
        <div className="grid gap-10 border-t-[3px] border-fg pt-10 lg:grid-cols-12 lg:gap-12 lg:pt-14">
          <SectionHeading
            id="what-you-get"
            title="What’s in a report"
            description="One free report per address, built only from official records and named sources."
            className="reveal lg:col-span-4 lg:items-start"
          />
          <dl className="grid gap-x-10 sm:grid-cols-2 lg:col-span-8">
            {REPORT_PARTS.map(({ title, body }) => (
              <div
                key={title}
                className="reveal border-t border-line py-6 first:border-t-0 first:pt-0 sm:[&:nth-child(2)]:border-t-0 sm:[&:nth-child(2)]:pt-0"
              >
                <dt className="heading text-[1.75rem]">{title}</dt>
                <dd className="mt-2 text-base leading-relaxed text-fg-2">{body}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section aria-labelledby="how-it-works" className="wrap mt-20 lg:mt-28">
        <div className="border-t-[3px] border-fg pt-10 lg:pt-14">
          <SectionHeading id="how-it-works" title="How it works" className="reveal" />
          {/* Drawn as a subway line: yellow route bullets joined by an ink track. */}
          <ol className="mt-12 grid gap-12 md:grid-cols-3 md:gap-8">
            {STEPS.map(({ title, body }, i) => (
              <li key={title} className="reveal relative pl-[4.75rem] md:pl-0">
                {i < STEPS.length - 1 ? (
                  <span
                    aria-hidden
                    className="absolute -bottom-12 left-[25px] top-14 w-1.5 bg-fg md:-right-8 md:bottom-auto md:left-14 md:top-[25px] md:h-1.5 md:w-auto"
                  />
                ) : null}
                <span
                  aria-hidden
                  className="figure absolute left-0 top-0 flex h-14 w-14 items-center justify-center rounded-full border-[3px] border-fg bg-brand text-[1.875rem] md:relative"
                >
                  {i + 1}
                </span>
                <h3 className="heading pt-2.5 text-[1.75rem] md:pt-0 md:mt-6">{title}</h3>
                <p className="mt-2 max-w-sm text-base leading-relaxed text-fg-2">{body}</p>
              </li>
            ))}
          </ol>

          <div className="reveal on-ink grain-ink mt-16 rounded-lg bg-ink p-6 text-white sm:p-10">
            <h3 className="heading text-[1.875rem] sm:text-[2.375rem]">What goes into the Wellness Score</h3>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-ink-muted">
              0 is worst, 100 is best. Each source is weighed by how the address compares with the rest of NYC.
              Crime, eviction and construction levels can also cap the score, and the report says when one does.
            </p>
            <div className="mt-8 flex h-5 w-full gap-1" aria-hidden>
              {WEIGHTS.map((w) => (
                <span key={w.label} className={`${w.swatch} h-full basis-0 rounded-[2px]`} style={{ flexGrow: w.pct }} />
              ))}
            </div>
            <ul className="mt-8 grid grid-cols-2 gap-x-6 gap-y-7 md:grid-cols-4">
              {WEIGHTS.map((w) => (
                <li key={w.label} className={`border-l-[3px] pl-4 ${w.edge}`}>
                  <span className="figure block text-[3rem] sm:text-[3.75rem]">{w.pct}%</span>
                  <span className="mt-1.5 block text-[15px] leading-snug text-ink-muted">{w.label}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section aria-labelledby="data-sources" className="wrap mt-20 lg:mt-28">
        <div className="border-t-[3px] border-fg pt-10 lg:pt-14">
          <SectionHeading
            id="data-sources"
            title="Where the data comes from"
            description="Official records only. If a source doesn’t answer, the report says so instead of guessing."
            className="reveal"
            action={
              <Link href="/about" className="text-link text-base">
                How ZerMap works
              </Link>
            }
          />
          <table className="reveal mt-10 w-full border-collapse text-left">
            <thead className="hidden md:table-header-group">
              <tr className="border-b-2 border-fg text-sm text-fg-3">
                <th scope="col" className="w-[34%] pb-3 pr-6 font-semibold">Source</th>
                <th scope="col" className="w-[18%] pb-3 pr-6 font-semibold">From</th>
                <th scope="col" className="pb-3 font-semibold">What it covers</th>
              </tr>
            </thead>
            <tbody>
              {SOURCES.map((s) => (
                <tr key={s.name} className="block border-b border-line py-4 md:table-row md:py-0">
                  <th scope="row" className="block text-base font-semibold text-fg md:table-cell md:py-4 md:pr-6">
                    {s.name}
                  </th>
                  <td className="block text-[15px] text-fg-2 md:table-cell md:py-4 md:pr-6">{s.from}</td>
                  <td className="block text-[15px] text-fg-2 md:table-cell md:py-4">{s.covers}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="sample-report" className="grain-paper mt-20 bg-brand lg:mt-28">
        <div className="wrap flex flex-col gap-8 py-14 md:flex-row md:items-end md:justify-between md:py-20">
          <div className="max-w-2xl">
            <h2 id="sample-report" className="display-xl text-[3.75rem] sm:text-[5.75rem]">
              See a sample report
            </h2>
            <p className="mt-4 text-lg leading-relaxed text-fg">
              Runs a real, current report for {sampleLabel}, a public place, so it isn’t anyone’s home.
            </p>
          </div>
          <button type="button" onClick={onSample} className="btn-ink h-16 shrink-0 px-8 text-lg">
            Run sample report
          </button>
        </div>
      </section>
    </div>
  );
}
