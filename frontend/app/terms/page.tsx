import type { Metadata } from "next";
import Link from "next/link";
import InfoPage, { InfoSection } from "@/components/InfoPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Terms",
  description: "The terms for using ZerMap's NYC address reports.",
  alternates: { canonical: "/terms" },
};

export default function TermsPage() {
  return (
    <InfoPage
      title="Terms of use"
      updated="October 2, 2026"
      intro="By using ZerMap you agree to these terms. They’re short, so please read them."
    >
      <InfoSection title="What ZerMap is">
        <p>
          ZerMap is a free, informational tool that summarizes public records about the area around an NYC address. It
          isn’t legal, financial or safety advice, and it isn’t a rating of any specific building, landlord or
          person.
        </p>
      </InfoSection>

      <InfoSection title="About the data">
        <p>
          Reports are built from NYC Open Data and other third-party sources (see{" "}
          <Link href="/about#data">data sources</Link>). Those sources can be delayed, incomplete or wrong, and counts
          describe the area within 2 miles, not a single building. Check official sources and visit in person before you
          make a decision.
        </p>
      </InfoSection>

      <InfoSection title="Using ZerMap fairly">
        <ul>
          <li>Don’t overload, scrape or try to break the service.</li>
          <li>Don’t use ZerMap to harass anyone or to break the law, including fair housing laws.</li>
          <li>Keep your account details safe. We may suspend accounts that misuse the service.</li>
        </ul>
      </InfoSection>

      <InfoSection title="No guarantees">
        <p>
          ZerMap is provided as is, without warranties of any kind. To the extent the law allows, ZerMap isn’t
          responsible for decisions made using its reports. Map, place and listing information belongs to its providers
          (including Mapbox and Google) and is subject to their terms.
        </p>
      </InfoSection>

      <InfoSection title="Changes">
        <p>
          We may update these terms; the date at the top shows the latest version.
          {CONTACT_EMAIL ? (
            <>
              {" "}
              Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
            </>
          ) : null}
        </p>
      </InfoSection>
    </InfoPage>
  );
}
