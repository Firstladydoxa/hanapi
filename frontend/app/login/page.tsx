"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { Alert, PasswordInput } from "@/components/ui";
import { Brand } from "@/components/AppShell";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(email.trim(), password);
      try { window.sessionStorage.removeItem("han.chat.seen"); } catch { /* storage unavailable */ }
      router.replace("/chat");
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_not_verified") {
        router.replace(`/verify-email?email=${encodeURIComponent(email.trim())}&notice=incomplete`);
        return;
      }
      setError(err instanceof ApiError ? err.message : "I couldn't sign you in. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="han-login">
      <div className="han-atmosphere" aria-hidden>
        <span className="han-orb han-orb-one" />
        <span className="han-orb han-orb-two" />
        <span className="han-grid" />
      </div>
      <div className="han-login-theme"><ThemeToggle /></div>
      <div className="han-login-card">
        <div className="mb-7 flex justify-center"><Brand /></div>
        <form onSubmit={submit} className="card space-y-4 p-8" aria-labelledby="login-title">
          <div>
            <p className="han-eyebrow">Translation workspace</p>
            <h1 id="login-title" className="text-2xl font-bold">Welcome to HAN</h1>
            <p className="mt-1 text-sm text-ink-muted">Sign in to continue to your projects.</p>
          </div>
          <div>
            <label className="label" htmlFor="email">Email</label>
            <input id="email" className="input" type="email" autoComplete="username" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="password">Password</label>
            <PasswordInput id="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>
          {error ? <Alert>{error}</Alert> : null}
          <button className="btn btn-primary w-full" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          <div className="flex justify-between text-sm"><Link className="underline" href="/forgot-password">Forgot password?</Link><Link className="underline" href="/register">Create account</Link></div>
        </form>
        <p className="han-login-foot">AI TRANSLATES. HUMANS UNDERSTAND. TNI DECIDES.</p>
      </div>
    </div>
  );
}
