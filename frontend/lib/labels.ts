import type { SegmentStatus, Tier, Version } from "./api";

export const STATUS_LABEL: Record<SegmentStatus, string> = {
  not_started: "Not started",
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  rejected: "Rejected",
  needs_attention: "Needs attention",
};

export const STATUS_STYLE: Record<SegmentStatus, string> = {
  not_started: "bg-white/10 text-slate-300",
  draft: "bg-sky-400/15 text-sky-200",
  in_review: "bg-amber-400/15 text-amber-200",
  approved: "bg-emerald-400/15 text-emerald-200",
  rejected: "bg-red-400/15 text-red-200",
  needs_attention: "bg-orange-400/15 text-orange-200",
};

export const TIER_LABEL: Record<Tier, string> = { production: "Production", assisted: "Assisted", experimental: "Experimental", unsupported: "Unsupported" };

export const TIER_MEANING: Record<Tier, string> = {
  production: "Evaluated on TNI content. Normal AI-assisted workflow, always with human review.",
  assisted: "Useful drafts with known limitations. Please review with extra care.",
  experimental: "Controlled pilot only. Treat drafts as early suggestions.",
  unsupported: "No automated translation. Contact TNI for a human translator.",
};

export const TIER_STYLE: Record<Tier, string> = {
  production: "bg-emerald-400/15 text-emerald-200",
  assisted: "bg-sky-400/15 text-sky-200",
  experimental: "bg-amber-400/15 text-amber-200",
  unsupported: "bg-white/10 text-slate-300",
};

/** The three visually distinct kinds of target text (spec §4.2). */
export type VersionKind = "approved" | "rejected" | "ai" | "edited";

export function versionKind(v: Pick<Version, "origin" | "approval_state">): VersionKind {
  if (v.approval_state === "approved") return "approved";
  if (v.approval_state === "rejected") return "rejected";
  return v.origin === "ai" ? "ai" : "edited";
}

export const KIND_LABEL: Record<VersionKind, string> = {
  approved: "Approved translation",
  rejected: "Rejected",
  ai: "Suggested draft",
  edited: "Translator-edited",
};

export const KIND_STYLE: Record<VersionKind, string> = {
  approved: "border-emerald-400/40 bg-emerald-400/10 text-emerald-100",
  rejected: "border-red-400/40 bg-red-400/10 text-red-100",
  ai: "border-sky-400/35 bg-sky-400/10 text-sky-100",
  edited: "border-violet-400/40 bg-violet-400/10 text-violet-100",
};

export const ROLE_LABEL: Record<string, string> = {
  translator: "Translator", reviewer: "Reviewer", project_manager: "Project manager", team_leader: "Team leader", tni_admin: "TNI administrator",
  technical_admin: "Technical administrator", auditor: "Auditor",
};

export const formatDate = (iso: string): string => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
