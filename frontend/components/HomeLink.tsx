"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentProps, MouseEvent } from "react";

/** Window event HomeClient listens for to return to the search box. */
export const HOME_RESET_EVENT = "zermap:home";

type Props = Omit<ComponentProps<typeof Link>, "href">;

/**
 * Link to "/". The homepage keeps its loading / results view in client state, so a link to "/"
 * while already on it changes nothing by itself; this also asks the homepage to reset.
 */
export default function HomeLink({ onClick, ...props }: Props) {
  const pathname = usePathname();

  const handleClick = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    const plainClick = e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
    if (!e.defaultPrevented && plainClick && pathname === "/") {
      window.dispatchEvent(new Event(HOME_RESET_EVENT));
    }
  };

  return <Link {...props} href="/" onClick={handleClick} />;
}
