"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { Alert } from "@/components/ui";
import { AuthCard, CodeInput } from "@/components/AuthCard";

const NOTICES: Record<string, string> = {
  incomplete: "Your registration was not completed. We've sent a new 6-digit code to your email — enter it below to finish.",
  delivery: "Your account was saved, but we couldn't send the email. Use “Resend code” to try again.",
};

function VerifyForm() {
  const params = useSearchParams();
  const recovery = params.get("recovery");
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [info, setInfo] = useState<string | null>(NOTICES[params.get("notice") ?? ""] ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const recovered = useRef(false);

  useEffect(() => {
    if (!recovery || recovered.current) return;
    recovered.current = true;
    api.recoverRegistration(recovery)
      .then((r) => { setEmail(r.email); setInfo("Welcome back! We've sent a fresh 6-digit code to your email."); setCooldown(60); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "This registration link is no longer valid."));
  }, [recovery]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api.verifyEmail(email.trim(), code); setDone(true); }
    catch (err) { setError(err instanceof ApiError ? err.message : "Verification failed. Please try again."); }
    finally { setBusy(false); }
  }
  async function resend() {
    setError(null); setInfo(null);
    try { await api.resendVerification(email.trim()); setInfo("A new code has been sent. Previous codes no longer work."); setCooldown(60); }
    catch (err) { setError(err instanceof ApiError ? err.message : "I couldn't resend the code."); if (err instanceof ApiError && err.status === 429) setCooldown(60); }
  }

  if (done) return (
    <AuthCard eyebrow="All set" title="Email verified" subtitle="Your account is ready.">
      <Link className="btn btn-primary w-full" href="/login">Continue to sign in</Link>
    </AuthCard>);

  return (
    <AuthCard eyebrow="Verify your email" title="Enter your 6-digit code" subtitle="The code expires after 15 minutes and works only once.">
      <form onSubmit={submit} className="space-y-4">
        {info ? <Alert kind="info">{info}</Alert> : null}
        <div><label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label className="label" htmlFor="code">Verification code</label><CodeInput value={code} onChange={setCode} /></div>
        {error ? <Alert>{error}</Alert> : null}
        <button className="btn btn-primary w-full" disabled={busy || code.length !== 6 || !email}>{busy ? "Verifying…" : "Verify email"}</button>
        <div className="flex justify-between text-sm">
          <button type="button" className="underline disabled:no-underline disabled:opacity-60" disabled={!email || cooldown > 0} onClick={() => void resend()}>{cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}</button>
          <Link className="underline" href="/login">Back to sign in</Link>
        </div>
      </form>
    </AuthCard>);
}

export default function VerifyEmailPage() {
  return <Suspense fallback={null}><VerifyForm /></Suspense>;
}
