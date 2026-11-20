"use client";

import type { ReactNode } from "react";
import { Brand } from "@/components/AppShell";
import { ThemeToggle } from "@/components/ThemeToggle";

export function AuthCard({ eyebrow, title, subtitle, children }: { eyebrow: string; title: string; subtitle?: string; children: ReactNode }) {
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
        <div className="card space-y-4 p-8">
          <div>
            <p className="han-eyebrow">{eyebrow}</p>
            <h1 className="text-2xl font-bold">{title}</h1>
            {subtitle ? <p className="mt-1 text-sm text-ink-muted">{subtitle}</p> : null}
          </div>
          {children}
        </div>
        <p className="han-login-foot">AI TRANSLATES. HUMANS UNDERSTAND. TNI DECIDES.</p>
      </div>
    </div>
  );
}

export function CodeInput({ value, onChange, id = "code" }: { value: string; onChange: (v: string) => void; id?: string }) {
  return (
    <input id={id} className="input text-center text-2xl font-bold tracking-[0.5em]" inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}"
      maxLength={6} required placeholder="······" value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))} />
  );
}
