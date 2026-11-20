import type { CSSProperties, ReactNode } from "react";

type AuthShellProps = {
  title: string;
  subtitle: string;
  children: ReactNode;
  footer?: ReactNode;
};

/** Shared chrome for sign-in / sign-up / password pages. */
export function AuthShell({ title, subtitle, children, footer }: AuthShellProps) {
  return (
    <main className="flex min-h-screen flex-col pt-16">
      <div className="wrap grid flex-1 content-center gap-10 py-14 sm:py-20 lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-6">
          <h1 className="display-xl text-[clamp(3.25rem,7.5vw,6.25rem)]">{title}</h1>
          <p className="mt-5 max-w-md text-lg leading-relaxed text-fg-2">{subtitle}</p>
        </div>
        <div className="w-full max-w-md rounded-lg border-2 border-fg bg-surface p-6 sm:p-8 lg:col-span-5 lg:col-start-8 lg:max-w-none">
          <div
            aria-hidden
            className="checker -mx-6 -mt-6 mb-6 rounded-t-md sm:-mx-8 sm:-mt-8 sm:mb-8"
            style={{ "--check": "8px" } as CSSProperties}
          />
          {children}
          {footer}
        </div>
      </div>
    </main>
  );
}

export function AuthAlert({
  tone,
  children,
}: {
  tone: "error" | "success" | "warn";
  children: ReactNode;
}) {
  const styles =
    tone === "error"
      ? "border-bad/40 bg-bad-soft text-bad"
      : tone === "success"
        ? "border-good/40 bg-good-soft text-good"
        : "border-fg/25 bg-brand-soft text-fg";
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      className={`mb-5 break-words rounded border px-3.5 py-2.5 text-[15px] font-medium leading-snug ${styles}`}
    >
      {children}
    </p>
  );
}

export function AuthField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="block text-[15px] font-semibold text-fg">
      {label}
      {children}
    </label>
  );
}

export function AuthDivider({ label }: { label: string }) {
  return (
    <div className="my-6 flex items-center gap-3 text-sm text-fg-3">
      <span aria-hidden className="h-px flex-1 bg-line" />
      {label}
      <span aria-hidden className="h-px flex-1 bg-line" />
    </div>
  );
}

export const authInputClassName =
  "mt-1.5 h-12 w-full rounded border-2 border-fg bg-surface px-3.5 text-base font-normal text-fg placeholder:text-fg-3 disabled:cursor-not-allowed disabled:opacity-60";

export const authPrimaryButtonClassName = "btn-primary h-12 w-full";

export const authGoogleButtonClassName = "btn mb-1 h-12 w-full border-fg bg-surface text-fg hover:bg-surface-2";

/** Google's standard "G" mark, required on Google sign-in buttons by Google's branding guidelines. */
export function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="h-[18px] w-[18px] shrink-0" aria-hidden>
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

export const authSecondaryButtonClassName = "btn-outline mt-3 h-12 w-full";

export const authFooterClassName = "mt-6 border-t border-line pt-5 text-[15px] text-fg-2";

export const authLinkClassName = "text-link";
