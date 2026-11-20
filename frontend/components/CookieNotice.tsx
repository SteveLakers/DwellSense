"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

const STORAGE_KEY = "zermap.cookie-notice";
// Bump when the cookie list on /privacy changes, so everyone sees the notice again.
const NOTICE_VERSION = "2026-10-04";

/** Remembered in local storage, not a cookie: /privacy promises signed-out visitors get no cookies. */
export default function CookieNotice() {
  const [open, setOpen] = useState(false);
  const barRef = useRef<HTMLElement>(null);

  useEffect(() => {
    try {
      setOpen(window.localStorage.getItem(STORAGE_KEY) !== NOTICE_VERSION);
    } catch {
      setOpen(true);
    }
  }, []);

  // The bar is fixed: pad the page by its height so the footer and focused controls never end up under it.
  useEffect(() => {
    const bar = barRef.current;
    if (!open || !bar) return;
    const { body, documentElement: root } = document;
    const observer = new ResizeObserver(() => {
      const height = `${bar.offsetHeight}px`;
      body.style.paddingBottom = height;
      root.style.scrollPaddingBottom = height;
    });
    observer.observe(bar);
    return () => {
      observer.disconnect();
      body.style.paddingBottom = "";
      root.style.scrollPaddingBottom = "";
    };
  }, [open]);

  if (!open) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(STORAGE_KEY, NOTICE_VERSION);
    } catch {
      // Storage blocked: the notice comes back on the next full page load.
    }
    setOpen(false);
  };

  return (
    <section
      ref={barRef}
      aria-label="Cookie notice"
      className="on-ink grain-ink fade-in fixed inset-x-0 bottom-0 z-40 border-t-[3px] border-brand bg-ink text-white print:hidden"
    >
      <div className="wrap flex items-center justify-between gap-4 py-3">
        <p className="text-[15px] leading-snug text-ink-muted">
          <span className="font-semibold text-white">ZerMap uses cookies only for signing&nbsp;in.</span> No ad or
          tracking cookies.{" "}
          <Link
            href="/privacy#cookies"
            className="whitespace-nowrap font-semibold text-white underline decoration-brand decoration-[3px] underline-offset-[3px] transition-colors hover:bg-brand hover:text-fg hover:decoration-fg"
          >
            Privacy policy
          </Link>
        </p>
        <button type="button" onClick={dismiss} className="btn-brand-on-ink min-h-[40px] shrink-0 px-6 text-[15px]">
          OK
        </button>
      </div>
    </section>
  );
}
