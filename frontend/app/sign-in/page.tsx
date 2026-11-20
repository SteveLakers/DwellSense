"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import {
  AuthAlert,
  AuthDivider,
  AuthField,
  AuthShell,
  authFooterClassName,
  authGoogleButtonClassName,
  authInputClassName,
  authLinkClassName,
  authPrimaryButtonClassName,
  GoogleMark,
} from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { isValidEmail } from "@/lib/auth/email";
import { createClient } from "@/lib/supabase/client";

export default function SignInPage() {
  const { isConfigured } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const fromQuery = params.get("error");
    if (fromQuery) {
      setError(fromQuery);
      return;
    }
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const fromHash = hash.get("error_description") || hash.get("error");
    if (fromHash) {
      setError(decodeURIComponent(fromHash.replace(/\+/g, " ")));
    }
  }, []);

  const onEmailSignIn = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    const trimmedEmail = email.trim();
    if (!isValidEmail(trimmedEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    setLoading(true);
    const { error: signError } = await supabase.auth.signInWithPassword({
      email: trimmedEmail,
      password,
    });
    setLoading(false);
    if (signError) {
      setError(signError.message);
      return;
    }
    window.location.assign("/");
  };

  const onGoogle = async () => {
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    setLoading(true);
    const origin = window.location.origin;
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${origin}/auth/callback` },
    });
    if (oauthError) {
      setLoading(false);
      setError(oauthError.message);
    }
  };

  return (
    <AuthShell
      title="Sign in"
      subtitle="Saving reports to your account is coming next."
      footer={
        <p className={authFooterClassName}>
          No account?{" "}
          <Link href="/sign-up" className={authLinkClassName}>
            Sign up
          </Link>
        </p>
      }
    >
      {!isConfigured && (
        <AuthAlert tone="warn">
          Supabase Auth keys are not set. Add{" "}
          <code className="font-mono text-[13px]">NEXT_PUBLIC_SUPABASE_URL</code> and{" "}
          <code className="font-mono text-[13px]">NEXT_PUBLIC_SUPABASE_ANON_KEY</code> on Vercel and
          locally.
        </AuthAlert>
      )}
      {error && <AuthAlert tone="error">{error}</AuthAlert>}

      <button
        type="button"
        onClick={() => void onGoogle()}
        disabled={loading || !isConfigured}
        className={authGoogleButtonClassName}
      >
        <GoogleMark />
        {loading ? "Redirecting…" : "Continue with Google"}
      </button>

      <AuthDivider label="or email" />

      <form onSubmit={onEmailSignIn} noValidate className="space-y-4">
        <AuthField label="Email">
          <input
            type="text"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={authInputClassName}
          />
        </AuthField>
        <AuthField label="Password">
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={authInputClassName}
          />
        </AuthField>
        <div className="-mt-1 flex justify-end">
          <Link
            href="/forgot-password"
            className="rounded-sm py-1 text-sm font-medium text-fg-2 underline-offset-[3px] transition-colors hover:text-fg hover:underline"
          >
            Forgot password?
          </Link>
        </div>
        <button
          type="submit"
          disabled={loading || !isConfigured}
          className={authPrimaryButtonClassName}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthShell>
  );
}
