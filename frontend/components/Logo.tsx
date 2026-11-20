/** ZerMap mark, the same "Z" as app/icon.svg. */
export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <rect width="64" height="64" rx="9" fill="#FFCC00" />
      <path d="M18 18h28v6L27 40h19v6H18v-6l19-16H18z" fill="#151515" />
    </svg>
  );
}

/** Takes its colour from the parent, so it works on light pages and on dark bands. */
export function Wordmark({ className = "" }: { className?: string }) {
  return <span className={`heading tracking-[-0.01em] ${className}`}>ZerMap</span>;
}
