import type { Metadata } from "next";
import InfoPage, { InfoSection } from "@/components/InfoPage";
import { CONTACT_EMAIL } from "@/lib/site";

export const metadata: Metadata = {
  title: "Privacy policy",
  description:
    "What ZerMap collects when you check an address or create an account, who receives it and how long it’s kept.",
  alternates: { canonical: "/privacy" },
};

const SERVICES: { name: string; policy?: string; role: string }[] = [
  { name: "Supabase", policy: "https://supabase.com/privacy", role: "accounts, account emails and ZerMap’s database" },
  { name: "Mapbox", policy: "https://www.mapbox.com/legal/privacy", role: "address lookup and maps" },
  {
    name: "Google",
    policy: "https://policies.google.com/privacy",
    role: "nearby places (Places), the short tips (Gemini) and Google sign-in",
  },
  { name: "Yelp", policy: "https://terms.yelp.com/privacy/en_us", role: "restaurant rankings, when they come from Yelp" },
  { name: "NYC Open Data", role: "city records" },
  { name: "Vercel", policy: "https://vercel.com/legal/privacy-notice", role: "website hosting" },
  { name: "Railway", policy: "https://railway.com/legal/privacy", role: "analysis server hosting" },
];

const STORED: { name: string; kind: string; purpose: string; kept: string }[] = [
  {
    name: "sb-…-auth-token",
    kind: "Cookie, sometimes split into .0,\u00A0.1,\u00A0…",
    purpose: "Keeps you signed in. Set when you sign in.",
    kept: "Until you sign out, or up to 400 days after your last signed-in visit",
  },
  {
    name: "sb-…-auth-token-code-verifier",
    kind: "Cookie",
    purpose:
      "Set when you continue with Google, sign up, resend a confirmation email or reset your password. It checks that the step is finished in the same browser that started it.",
    kept: "Deleted when that step finishes; otherwise up to 400 days",
  },
  {
    name: "zermap.cookie-notice",
    kind: "Local storage",
    purpose: "Remembers that you closed the cookie notice.",
    kept: "Until you clear your browser’s storage",
  },
  {
    name: "mapbox.eventData…",
    kind: "Local storage, three entries",
    purpose:
      "Mapbox’s map code saves these when a report’s map loads: a random ID it replaces after 24 hours, when that ID was made and when it last reported map use to Mapbox.",
    kept: "Until you clear your browser’s storage",
  },
  {
    name: "mapbox-tiles",
    kind: "Browser cache",
    purpose: "Copies of map pieces for the areas you’ve viewed, so maps load faster.",
    kept: "Mapbox keeps about 500 and removes the oldest first",
  },
];

export default function PrivacyPage() {
  const email = CONTACT_EMAIL ? <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> : null;

  return (
    <InfoPage
      title="Privacy policy"
      updated="November 20, 2026"
      intro="What ZerMap collects when you check an address or create an account, who receives it and how long it’s kept. You don’t need an account to check an address, and we don’t sell personal information."
    >
      <InfoSection id="addresses" title="Addresses you check">
        <ul>
          <li>
            Our website sends the address to our analysis server, which builds your report. Your IP address isn’t
            passed along.
          </li>
          <li>Mapbox receives the address to find its location.</li>
          <li>
            We look up city records (NYC Open Data), nearby transit, groceries and shops (Google Places) and aircraft
            positions (our own database) by that location, not by the street address. Restaurant rankings come from
            Google Places or Yelp, which also get only the location.
          </li>
          <li>
            Google Gemini receives the address and the area’s summary counts (totals, the most common types and how
            they compare with the rest of NYC) and writes the short tips on some cards. It doesn’t receive the
            individual records.
          </li>
          <li>
            When the report’s map loads, your browser gets it straight from Mapbox. Mapbox receives your IP address,
            the map area you’re viewing and details from its map code: map loads, your browser and operating system,
            screen and window size, graphics hardware, connection type and how quickly the map loaded.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="reports" title="Your report">
        <ul>
          <li>
            Reports are kept only in our server’s memory, never in a database, and aren’t linked to you or to an
            account.
          </li>
          <li>
            The PDF download works for up to 30 minutes after the check. Expired reports are cleared from memory as new
            reports come in, and a server restart clears them all.
          </li>
          <li>
            So repeat checks load faster, the score and tips stay cached in memory, without the address, until newer
            reports replace them or the server restarts.
          </li>
          <li>
            Your browser keeps the report only while the page is open. A PDF you download stays on your device and
            includes the address.
          </li>
          <li>
            Links in the PDF open the original records and listings on NYC Open Data, Google Maps, Yelp or adsb.lol.
            Some include the address or its location so the page opens filtered to it, and that site receives them
            when you open the link.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="accounts" title="Accounts">
        <ul>
          <li>You don’t need an account to use ZerMap. Accounts are run by Supabase, our sign-in provider.</li>
          <li>
            Supabase stores your email address and a hashed form of your password, not the password itself. Your
            password goes straight from your browser to Supabase and never passes through ZerMap’s servers.
          </li>
          <li>
            If you continue with Google, Google shares your name, email address, profile picture and Google account ID
            with Supabase to set up your account.
          </li>
          <li>Supabase sends account emails, such as confirming your email address or resetting your password.</li>
          <li>Supabase logs sign-ins and account changes with the time, IP address and browser, for security.</li>
          <li>Addresses you check aren’t saved to your account or linked to it. We keep your account until it’s deleted.</li>
        </ul>
      </InfoSection>

      <InfoSection id="cookies" title="Cookies and browser storage">
        <p>
          ZerMap uses cookies only for signing in. Checking an address without signing in sets no cookies, and there
          are no advertising or analytics cookies. This is everything the site stores in your browser:
        </p>
        <table className="w-full border-collapse border-t-2 border-fg text-left text-[15px] leading-normal md:border-t-0">
          <caption className="sr-only">Everything ZerMap stores in your browser</caption>
          <thead className="hidden md:table-header-group">
            <tr className="border-b-2 border-fg text-sm text-fg-3">
              <th scope="col" className="w-[32%] pb-3 pr-5 font-semibold">Name</th>
              <th scope="col" className="pb-3 pr-5 font-semibold">What it’s for</th>
              <th scope="col" className="w-[25%] pb-3 font-semibold">How long it’s kept</th>
            </tr>
          </thead>
          <tbody>
            {STORED.map((item) => (
              <tr key={item.name} className="block border-b border-line py-4 md:table-row md:py-0">
                <th scope="row" className="block font-normal md:table-cell md:py-4 md:pr-5 md:align-top">
                  <code className="text-[14px] font-semibold text-fg">{item.name}</code>
                  <span className="mt-1 block text-sm text-fg-3">{item.kind}</span>
                </th>
                <td className="mt-2 block md:mt-0 md:table-cell md:py-4 md:pr-5 md:align-top">{item.purpose}</td>
                <td className="mt-2 block md:mt-0 md:table-cell md:py-4 md:align-top">
                  <span className="font-semibold text-fg md:hidden">Kept: </span>
                  {item.kept}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <ul>
          <li>In the two cookie names, “…” stands for ZerMap’s Supabase project ID.</li>
          <li>
            You can delete all of these by clearing cookies and site data for zermap.com in your browser’s settings.
            Clearing the sign-in cookies signs you out, and clearing local storage brings the cookie notice back.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="logs" title="Logs">
        <ul>
          <li>
            Vercel, which hosts the website, keeps standard request logs, such as your IP address, browser, the page
            requested and the time, for security and troubleshooting.
          </li>
          <li>
            Our analysis server runs on Railway and receives requests only from our website, so it never sees your IP
            address.
          </li>
          <li>Our analysis server doesn’t write the addresses you check, or their locations, to its logs.</li>
          <li>
            Supabase, which hosts our database, keeps standard logs of our server’s database requests for a limited
            time. Requests that look up aircraft positions, or city records from our backup copy when NYC Open Data
            is down, include a map area centered on the location you check, so that location can be worked out from
            them. They don’t include the street address or your IP address.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="sharing" title="Who receives your information">
        <p>
          These services run parts of ZerMap and receive the information described above. Linked names go to each
          company’s privacy policy.
        </p>
        <ul>
          {SERVICES.map((s) => (
            <li key={s.name}>
              {s.policy ? (
                <a href={s.policy} target="_blank" rel="noopener noreferrer" aria-label={`${s.name} privacy policy`}>
                  {s.name}
                </a>
              ) : (
                <strong>{s.name}</strong>
              )}
              : {s.role}
            </li>
          ))}
        </ul>
        <p>
          We don’t sell or rent personal information, and we don’t share it for advertising. We may disclose
          information when the law requires it.
        </p>
      </InfoSection>

      <InfoSection id="children" title="Children">
        <p>
          ZerMap is meant for people looking for a place to live. It isn’t directed at children under 13, and we
          don’t knowingly collect their personal information.
          {email ? <> If you think a child has given us personal information, email {email} and we’ll delete it.</> : null}
        </p>
      </InfoSection>

      <InfoSection id="choices" title="Your choices">
        <ul>
          <li>You can check addresses without an account.</li>
          {email ? (
            <li>
              To delete your account, or to ask what personal information we hold about you or have it corrected,
              email {email} from the address on your account.
            </li>
          ) : (
            <li>A contact address for deleting your account and other privacy requests will be listed here.</li>
          )}
          <li>
            ZerMap doesn’t track you across other websites or sell personal information, so there’s nothing for Do Not
            Track or Global Privacy Control signals to turn off.
          </li>
        </ul>
      </InfoSection>

      <InfoSection id="changes" title="Changes to this policy">
        <p>
          If we change this policy, we’ll post the new version on this page and update the date at the top.
          {email ? <> Questions about this policy: {email}.</> : null}
        </p>
      </InfoSection>
    </InfoPage>
  );
}
