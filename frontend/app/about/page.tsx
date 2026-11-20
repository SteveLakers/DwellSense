import type { Metadata } from "next";
import InfoPage, { InfoSection } from "@/components/InfoPage";
import { CONTACT_EMAIL, FLIGHT_NOISE_PAUSED } from "@/lib/site";

export const metadata: Metadata = {
  title: "About",
  description:
    "How ZerMap builds its NYC address reports: which official datasets it uses, the date ranges, and how the Wellness Score compares each address with the rest of NYC.",
  alternates: { canonical: "/about" },
};

const DATASETS: { name: string; id: string; use: string }[] = [
  { name: "NYPD Complaint Data (Current Year to Date)", id: "5uac-w243", use: "NYPD complaints and major felonies" },
  { name: "NYPD Calls for Service (Year to Date)", id: "n2zq-pubd", use: "Crime-in-progress calls dispatched to NYPD" },
  { name: "311 Service Requests from 2020 to Present", id: "erm2-nwe9", use: "311 requests, noise and construction complaints" },
  { name: "DOB NOW: Build – Approved Permits", id: "rbx6-tga4", use: "Active construction permits" },
  { name: "DOB Permit Issuance", id: "ipu4-2q9a", use: "Active construction permits (older DOB system)" },
  { name: "Evictions", id: "6z8x-wfk4", use: "Residential evictions carried out by NYC Marshals" },
  { name: "Primary Land Use Tax Lot Output (PLUTO)", id: "64uk-42ks", use: "Apartment locations used for the NYC comparison" },
];

export default function AboutPage() {
  return (
    <InfoPage
      title="About ZerMap"
      intro="ZerMap is a free report on the area around any New York City address, built from official city records, so you can check the block before you sign a lease."
    >
      <InfoSection title="What the report checks">
        <p>
          ZerMap counts records within 2 miles of the address: NYPD complaints, crime-in-progress calls to NYPD,
          311 requests (including noise and construction complaints), active construction permits and residential
          evictions.{" "}
          {FLIGHT_NOISE_PAUSED
            ? "It also finds the nearest transit, groceries and top-rated restaurants."
            : "It also measures how often aircraft pass overhead, and finds the nearest transit, groceries and top-rated restaurants."}
        </p>
        <p>
          Each count is compared with the same count measured at apartment locations sampled across NYC (residential
          lots with three or more units in NYC’s PLUTO data, weighted by number of units). That’s where labels
          like &ldquo;Higher than most of NYC&rdquo; come from.
        </p>
      </InfoSection>

      <InfoSection title="The Wellness Score">
        <p>
          The score runs from 0 (worst) to 100 (best). It weighs NYPD complaints (40%), 311 requests (26%), residential
          evictions (20%) and active construction permits (14%), each by how it compares with the rest of NYC.
        </p>
        <p>
          Crime, eviction and construction levels also cap the score. For example, a score above 38 needs NYPD
          complaints in the lowest 57% of NYC apartment locations, and a score above 58 needs them in the lowest 11%.
          When a cap sets the score, the report says which one.
        </p>
        <p>
          If NYPD data, or too many other sources, can’t be reached during a scan, the report says
          &ldquo;Not scored&rdquo; instead of guessing. A source that didn’t answer is shown as unavailable, never as zero.
        </p>
      </InfoSection>

      <InfoSection title="Dates and freshness">
        <ul>
          <li>NYPD publishes its data quarterly, so NYPD counts cover the newest 30 days NYPD has released.</li>
          <li>311 requests cover the last 30 days.</li>
          <li>Construction permits are those issued in the last 90 days and still active.</li>
          <li>Evictions cover the last 180 days.</li>
          <li>
            {FLIGHT_NOISE_PAUSED
              ? "Flight noise is paused for now: our aircraft-position source is limiting how much we can record, so reports leave it out until that’s fixed."
              : "Flight noise uses aircraft positions (ADS-B) from the last 7 days. Each aircraft counts once per pass, even if it circles."}
          </li>
        </ul>
        <p>Every report lists the exact date range and the newest record behind each count.</p>
      </InfoSection>

      <InfoSection title="What ZerMap doesn’t do">
        <ul>
          <li>It doesn’t inspect a specific apartment, building or landlord.</li>
          <li>
            It doesn’t check HPD building violations yet. For a street address, the PDF report links to that
            building’s HPD violations on NYC Open Data so you can look them up.
          </li>
          <li>
            City data can be delayed, incomplete or imprecise, and records without a location can’t be counted.
            Visit the block yourself and check official sources before you sign.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="data" title="Data sources">
        <p>City records come from NYC Open Data:</p>
        <ul>
          {DATASETS.map((d) => (
            <li key={d.id}>
              <a href={`https://data.cityofnewyork.us/d/${d.id}`} target="_blank" rel="noopener noreferrer">
                {d.name}
              </a>
              <span className="block text-[15px] text-fg-3">{d.use}</span>
            </li>
          ))}
        </ul>
        <p>
          Aircraft positions are collected from{" "}
          <a href="https://adsb.lol" target="_blank" rel="noopener noreferrer">
            adsb.lol
          </a>
          {FLIGHT_NOISE_PAUSED ? " (flight noise is paused for now)" : ""}. Places, transit and dining come from Google
          Places. Address lookup and maps come from Mapbox. Google Gemini
          writes the short takeaway line on some cards; the counts and NYC comparisons are computed directly from the
          data.
        </p>
      </InfoSection>

      {CONTACT_EMAIL ? (
        <InfoSection title="Contact">
          <p>
            Questions or corrections: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>
          </p>
        </InfoSection>
      ) : null}
    </InfoPage>
  );
}
