"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
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
  authSecondaryButtonClassName,
  GoogleMark,
} from "@/components/AuthShell";
import { useAuth } from "@/components/AuthProvider";
import { isValidEmail } from "@/lib/auth/email";
import { createClient } from "@/lib/supabase/client";

export default function SignUpPage() {
  const { isConfigured } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingConfirmEmail, setPendingConfirmEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);

  const onEmailSignUp = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setMessage(null);
    setPendingConfirmEmail(null);
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
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setLoading(true);
    const origin = window.location.origin;
    const { data, error: signError } = await supabase.auth.signUp({
      email: trimmedEmail,
      password,
      options: { emailRedirectTo: `${origin}/auth/callback` },
    });
    setLoading(false);
    if (signError) {
      setError(signError.message);
      return;
    }

    // Supabase may return a user with empty identities when the email is taken.
    const identities = data.user?.identities ?? null;
    if (data.user && identities && identities.length === 0) {
      setError("An account with this email already exists. Sign in instead, or reset your password.");
      return;
    }

    if (data.session) {
      window.location.assign("/");
      return;
    }

    setPendingConfirmEmail(trimmedEmail);
    setMessage(
      "We sent a confirmation link to your email. Confirm, then sign in. Check spam if you do not see it within a few minutes.",
    );
  };

  const onResendConfirm = async () => {
    if (!pendingConfirmEmail) return;
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    setResending(true);
    const origin = window.location.origin;
    const { error: resendError } = await supabase.auth.resend({
      type: "signup",
      email: pendingConfirmEmail,
      options: { emailRedirectTo: `${origin}/auth/callback` },
    });
    setResending(false);
    if (resendError) {
      setError(resendError.message);
      return;
    }
    setMessage("Confirmation email resent. Check your inbox and spam folder.");
  };

  const onGoogle = async () => {
    setError(null);
    const supabase = createClient();
    if (!supabase) {
      setError("Auth is not configured.");
      return;
    }
    const origin = window.location.origin;
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${origin}/auth/callback` },
    });
    if (oauthError) setError(oauthError.message);
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Saving reports to your account is coming next."
      footer={
        <p className={authFooterClassName}>
          Already have an account?{" "}
          <Link href="/sign-in" className={authLinkClassName}>
            Sign in
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
      {message && <AuthAlert tone="success">{message}</AuthAlert>}

      <button
        type="button"
        onClick={() => void onGoogle()}
        disabled={loading || !isConfigured}
        className={authGoogleButtonClassName}
      >
        <GoogleMark />
        Continue with Google
      </button>

      <AuthDivider label="or email" />

      <form onSubmit={onEmailSignUp} noValidate className="space-y-4">
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
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={authInputClassName}
          />
        </AuthField>
        <button
          type="submit"
          disabled={loading || !isConfigured}
          className={authPrimaryButtonClassName}
        >
          {loading ? "Creating account…" : "Sign up"}
        </button>
      </form>

      {pendingConfirmEmail && (
        <button
          type="button"
          onClick={() => void onResendConfirm()}
          disabled={resending || !isConfigured}
          className={authSecondaryButtonClassName}
        >
          {resending ? "Resending…" : "Resend confirmation email"}
        </button>
      )}
    </AuthShell>
  );
}
