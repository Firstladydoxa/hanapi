"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { Alert, PasswordInput } from "@/components/ui";
import { AuthCard, CodeInput } from "@/components/AuthCard";

export default function ForgotPasswordPage() {
  const [step, setStep] = useState<"request" | "confirm" | "done">("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function request(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api.requestPasswordReset(email.trim()); setStep("confirm"); }
    catch (err) { setError(err instanceof ApiError ? err.message : "I couldn't send the code. Please try again."); }
    finally { setBusy(false); }
  }
  async function confirm(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api.confirmPasswordReset(email.trim(), code, password); setStep("done"); }
    catch (err) { setError(err instanceof ApiError ? err.message : "I couldn't reset your password. Please try again."); }
    finally { setBusy(false); }
  }

  if (step === "done") return (
    <AuthCard eyebrow="All set" title="Password updated" subtitle="You have been signed out of all devices.">
      <Link className="btn btn-primary w-full" href="/login">Sign in</Link>
    </AuthCard>);

  if (step === "confirm") return (
    <AuthCard eyebrow="Reset password" title="Check your email" subtitle="If an account exists for that address, we sent a 6-digit code. It expires in 15 minutes.">
      <form onSubmit={confirm} className="space-y-4">
        <div><label className="label" htmlFor="code">Reset code</label><CodeInput value={code} onChange={setCode} /></div>
        <div><label className="label" htmlFor="password">New password</label>
          <PasswordInput id="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="mt-1 text-xs text-ink-muted">At least 12 characters.</p></div>
        {error ? <Alert>{error}</Alert> : null}
        <button className="btn btn-primary w-full" disabled={busy || code.length !== 6}>{busy ? "Updating…" : "Update password"}</button>
        <button type="button" className="text-sm underline" onClick={() => { setStep("request"); setCode(""); setError(null); }}>Send a new code</button>
      </form>
    </AuthCard>);

  return (
    <AuthCard eyebrow="Reset password" title="Forgot your password?" subtitle="Enter your email and we'll send you a 6-digit code.">
      <form onSubmit={request} className="space-y-4">
        <div><label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        {error ? <Alert>{error}</Alert> : null}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Sending…" : "Send code"}</button>
        <p className="text-center text-sm"><Link className="underline" href="/login">Back to sign in</Link></p>
      </form>
    </AuthCard>);
}
