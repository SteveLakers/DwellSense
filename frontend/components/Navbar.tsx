"use client";

import Link from "next/link";
import { useAuth } from "@/components/AuthProvider";
import HomeLink from "@/components/HomeLink";
import { LogoMark, Wordmark } from "@/components/Logo";

const navLink = "rounded px-1 py-2 text-[15px] font-medium text-ink-muted transition-colors hover:text-white";

export default function Navbar() {
  const { user, isLoaded, signOut } = useAuth();

  return (
    <header className="on-ink grain-ink fixed inset-x-0 top-0 z-50 h-16 bg-ink text-white">
      <nav className="wrap flex h-full items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3 md:gap-7">
          <HomeLink className="flex shrink-0 items-center gap-2.5 rounded" aria-label="ZerMap home">
            <LogoMark className="h-8 w-8" />
            <Wordmark className="text-[26px] text-white" />
          </HomeLink>
          <span className="hidden rounded border border-ink-line px-1.5 py-px text-xs font-semibold text-ink-muted sm:inline">
            Beta
          </span>
          <div className="hidden items-center gap-5 md:flex">
            <Link href="/about" className={navLink}>
              About
            </Link>
            <Link href="/about#data" className={navLink}>
              Data sources
            </Link>
          </div>
        </div>

        <div className="flex min-w-0 items-center justify-end gap-2 sm:gap-4">
          {!isLoaded && <span className="h-10 w-24 animate-pulse rounded bg-ink-2" aria-hidden />}

          {isLoaded && !user && (
            <>
              <Link href="/sign-in" className={`${navLink} whitespace-nowrap px-2`}>
                Sign in
              </Link>
              <Link href="/sign-up" className="btn-brand-on-ink min-h-[40px] whitespace-nowrap px-4 text-[15px]">
                Sign up
              </Link>
            </>
          )}

          {isLoaded && user && (
            <div className="flex min-w-0 items-center gap-2 sm:gap-4">
              <span className="hidden max-w-[200px] truncate text-sm text-ink-muted sm:inline" title={user.email ?? user.id}>
                {user.email ?? "Signed in"}
              </span>
              <button
                type="button"
                onClick={() => void signOut()}
                className="btn-outline-on-ink min-h-[40px] whitespace-nowrap px-4 text-[15px]"
              >
                Sign out
              </button>
            </div>
          )}
        </div>
      </nav>
    </header>
  );
}
