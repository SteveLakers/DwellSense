import type { Metadata } from "next";
import Link from "next/link";
import Footer from "@/components/Footer";

export const metadata: Metadata = {
  title: "Page not found",
};

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col pt-16">
      <main className="on-ink grain-ink flex flex-1 flex-col bg-ink text-white">
        <div className="wrap flex flex-1 flex-col justify-center py-20 sm:py-28">
          <div aria-hidden className="h-[3px] bg-white" />
          <p aria-hidden className="display-xl mt-10 overflow-hidden text-[clamp(8rem,30vw,20rem)] leading-[0.8] text-brand">
            <span className="rise">404</span>
          </p>
          <h1 className="display mt-8 max-w-3xl text-[clamp(2.6rem,6vw,4.75rem)]">This block isn’t on the map.</h1>
          <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-muted">
            The page you’re looking for doesn’t exist or has moved.
          </p>
          <div className="mt-10">
            <Link href="/" className="btn-brand-on-ink h-14 px-7 text-lg">
              Back to the search
            </Link>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
}
