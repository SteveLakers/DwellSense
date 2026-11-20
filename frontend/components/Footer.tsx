import Link from "next/link";
import HomeLink from "@/components/HomeLink";
import { LogoMark, Wordmark } from "@/components/Logo";
import { CONTACT_EMAIL } from "@/lib/site";

const linkClass = "text-ink-muted transition-colors hover:text-white";
const headClass = "text-sm font-semibold text-white";

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="on-ink grain-ink relative z-20 mt-auto w-full bg-ink text-white">
      <div aria-hidden className="checker" />
      <div className="wrap grid gap-10 py-14 md:grid-cols-[minmax(0,1.6fr)_repeat(3,minmax(0,1fr))]">
        <div className="max-w-sm">
          <HomeLink className="inline-flex items-center gap-2.5 rounded" aria-label="ZerMap home">
            <LogoMark className="h-8 w-8" />
            <Wordmark className="text-[26px] text-white" />
          </HomeLink>
          <p className="mt-4 text-[15px] leading-relaxed text-ink-muted">
            Official NYC data about the block, before you sign a lease.
          </p>
        </div>

        <nav aria-label="Product" className="text-[15px]">
          <p className={headClass}>Product</p>
          <ul className="mt-3 space-y-2.5">
            <li>
              <HomeLink className={linkClass}>Check an address</HomeLink>
            </li>
            <li>
              <Link href="/about" className={linkClass}>
                About
              </Link>
            </li>
            {CONTACT_EMAIL ? (
              <li>
                <a href={`mailto:${CONTACT_EMAIL}`} className={linkClass}>
                  Contact
                </a>
              </li>
            ) : null}
          </ul>
        </nav>

        <nav aria-label="Data" className="text-[15px]">
          <p className={headClass}>Data</p>
          <ul className="mt-3 space-y-2.5">
            <li>
              <a href="https://opendata.cityofnewyork.us/" target="_blank" rel="noopener noreferrer" className={linkClass}>
                NYC Open Data
              </a>
            </li>
            <li>
              <Link href="/about#data" className={linkClass}>
                Data sources
              </Link>
            </li>
          </ul>
        </nav>

        <nav aria-label="Legal" className="text-[15px]">
          <p className={headClass}>Legal</p>
          <ul className="mt-3 space-y-2.5">
            <li>
              <Link href="/privacy" className={linkClass}>
                Privacy
              </Link>
            </li>
            <li>
              <Link href="/terms" className={linkClass}>
                Terms
              </Link>
            </li>
          </ul>
        </nav>
      </div>

      <div aria-hidden className="wrap select-none">
        <div className="footer-sign-box">
          <p className="footer-sign display-xl text-ink-2">ZerMap</p>
        </div>
      </div>

      <div className="border-t border-ink-line">
        <p className="wrap py-5 text-sm text-ink-muted">
          &copy; {year} ZerMap. Independent; not affiliated with the City of New York.
        </p>
      </div>
    </footer>
  );
}
