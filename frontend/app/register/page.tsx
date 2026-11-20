"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type RegistrationLanguage } from "@/lib/api";
import { Alert, PasswordInput } from "@/components/ui";
import { AuthCard } from "@/components/AuthCard";

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [language, setLanguage] = useState("");
  const [languages, setLanguages] = useState<RegistrationLanguage[]>([]);
  useEffect(() => { api.registrationLanguages().then(setLanguages).catch(() => setError("The language list could not be loaded. Please refresh the page.")); }, []);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const r = await api.register(email.trim(), name.trim(), password, language);
      router.replace(`/verify-email?email=${encodeURIComponent(r.email)}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_delivery_unavailable") router.replace(`/verify-email?email=${encodeURIComponent(email.trim())}&notice=delivery`);
      else setError(err instanceof ApiError ? err.message : "I couldn't create your account. Please try again.");
    } finally { setBusy(false); }
  }

  return (
    <AuthCard eyebrow="Translation workspace" title="Create your HAN account" subtitle="We'll email you a 6-digit code to confirm your address.">
      <form onSubmit={submit} className="space-y-4">
        <div><label className="label" htmlFor="name">Full name</label>
          <input id="name" className="input" autoComplete="name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><label className="label" htmlFor="email">Email</label>
          <input id="email" className="input" type="email" autoComplete="email" required maxLength={320} value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div><label className="label" htmlFor="password">Password</label>
          <PasswordInput id="password" autoComplete="new-password" required minLength={12} maxLength={1024} value={password} onChange={(e) => setPassword(e.target.value)} />
          <p className="mt-1 text-xs text-ink-muted">At least 12 characters.</p></div>
        <div><label className="label" htmlFor="language">Language of expertise</label>
          <select id="language" className="input" required value={language} onChange={(e) => setLanguage(e.target.value)}>
            <option value="" disabled>Choose the language you translate into…</option>
            {languages.map((l) => <option key={l.code} value={l.code}>{l.display_name}{l.native_name && l.native_name !== l.display_name ? ` — ${l.native_name}` : ""}</option>)}
          </select>
          <p className="mt-1 text-xs text-ink-muted">HAN will set up English → your language and your language → English for you.</p></div>
        {error ? <Alert>{error}</Alert> : null}
        <button className="btn btn-primary w-full" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
        <p className="text-center text-sm">Already registered? <Link className="underline" href="/login">Sign in</Link></p>
      </form>
    </AuthCard>
  );
}
