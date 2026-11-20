"use client";

import { useState, type InputHTMLAttributes, type ReactNode } from "react";
import { STATUS_LABEL, STATUS_STYLE, TIER_LABEL, TIER_MEANING, TIER_STYLE } from "@/lib/labels";
import type { SegmentStatus, Tier } from "@/lib/api";

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm text-ink-muted">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-brand" />
      {label}…
    </span>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "success" | "info"; children: ReactNode }) {
  const style = { error: "border-danger/40 bg-danger/15 text-danger-text", success: "border-ok/40 bg-ok/15 text-ok-text", info: "border-info/40 bg-info/15 text-info-text" }[kind];
  return <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border px-3 py-2 text-sm ${style}`}>{children}</div>;
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-surface p-10 text-center">
      <h3 className="text-base font-semibold">{title}</h3>
      {children ? <p className="mt-1 text-sm text-ink-muted">{children}</p> : null}
    </div>
  );
}

export function StatusChip({ status }: { status: SegmentStatus }) {
  return <span className={`inline-flex whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-bold ${STATUS_STYLE[status]}`}>{STATUS_LABEL[status]}</span>;
}

export function TierBadge({ tier, withMeaning = false }: { tier: Tier; withMeaning?: boolean }) {
  return (
    <span title={TIER_MEANING[tier]} className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${TIER_STYLE[tier]}`}>
      {TIER_LABEL[tier]}
      {withMeaning ? <span className="sr-only">: {TIER_MEANING[tier]}</span> : null}
    </span>
  );
}

export function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div>
      <label className="label" htmlFor={htmlFor}>{label}</label>
      {children}
    </div>
  );
}

export function PageTitle({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: ReactNode }) {
  return (
    <div className="page-title mb-6">
      {eyebrow ? <p className="mb-1 text-[11px] font-extrabold uppercase tracking-[0.14em] text-brand">{eyebrow}</p> : null}
      <h1 className="text-2xl font-bold sm:text-3xl">{title}</h1>
      {children ? <p className="mt-1 text-sm text-ink-muted">{children}</p> : null}
    </div>
  );
}

export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input {...props} type={shown ? "text" : "password"} className={`input pr-11 ${props.className ?? ""}`} />
      <button type="button" className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-ink-muted hover:text-ink" aria-label={shown ? "Hide password" : "Show password"} aria-pressed={shown} onClick={() => setShown((v) => !v)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
          {shown ? <path d="M3 3l18 18" /> : null}
        </svg>
      </button>
    </div>
  );
}
