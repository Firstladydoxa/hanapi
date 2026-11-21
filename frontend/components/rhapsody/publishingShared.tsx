"use client";

import type { ReactNode } from "react";
import { ApiError, type ProductionLanguage } from "@/lib/api";
import { canSeeAdmin, useAuth } from "@/lib/auth";
import { Alert } from "@/components/ui";

export const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export type Pill = "orange" | "green" | "blue" | "red" | "grey" | "violet";
export interface Stage { key: string; label: string; pill: Pill; accent: string; hint: string }

const ACCENT: Record<Pill, string> = { orange: "#f59e0b", green: "#22c55e", blue: "#38bdf8", red: "#f87171", grey: "#64748b", violet: "#a78bfa" };

/** One visible stage per translation, so admins can read the whole production at a glance. */
export function stageOf(l: Pick<ProductionLanguage, "status" | "translated" | "draft_status" | "has_proof">): Stage {
  const mk = (key: string, label: string, pill: Pill, hint: string): Stage => ({ key, label, pill, accent: ACCENT[pill], hint });
  switch (l.status) {
    case "published": return mk("published", "Published", "blue", "Approved for publication.");
    case "approved": return l.has_proof
      ? mk("proofing", "Proof ready for review", "violet", "A proof PDF exists. Review it, then approve or return it.")
      : mk("ready", "Ready for layout", "green", "The translation is approved. Generate the proof PDF.");
    case "submitted": case "in_review": return mk("submitted", "Submitted · ready for review", "green", "The translator has submitted. Approve it to release it for layout.");
    case "changes_requested": return mk("changes", "Changes requested", "red", "Returned to the translator.");
    default:
      if (l.status === "in_progress" || l.translated > 0 || l.draft_status === "running") return mk("progress", l.draft_status === "running" ? "HAN is drafting" : "Translation in progress", "orange", "The translator is still working.");
      return mk("new", "Not started", "grey", "Assigned, no work yet.");
  }
}

export const STAGE_ORDER = ["submitted", "ready", "proofing", "progress", "changes", "published", "new"];

export function StagePill({ stage }: { stage: Stage }) {
  return <span className={`pill pill-${stage.pill}`} title={stage.hint}>{stage.label}</span>;
}

export function AdminOnly({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (!canSeeAdmin(user)) return <Alert kind="error">Only administrators can manage Rhapsody publishing.</Alert>;
  return <>{children}</>;
}

export const bytes = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
