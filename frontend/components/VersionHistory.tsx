"use client";

import type { Version } from "@/lib/api";
import { formatDate, KIND_LABEL, KIND_STYLE, versionKind } from "@/lib/labels";

interface Props { versions: Version[]; selectedId?: string | null; onSelect?: (v: Version) => void }

/** Newest first. Versions are immutable: this list only ever grows. */
export function VersionHistory({ versions, selectedId, onSelect }: Props) {
  if (versions.length === 0) return <p className="text-xs text-ink-muted">Saved versions appear here.</p>;
  return (
    <ol className="space-y-2" aria-label="Version history">
      {[...versions].sort((a, b) => b.version_number - a.version_number).map((v) => {
        const kind = versionKind(v);
        return (
          <li key={v.version_id} className={`rounded-lg border px-3 py-2 text-xs ${KIND_STYLE[kind]} ${selectedId === v.version_id ? "ring-2 ring-brand" : ""}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-bold">Version {v.version_number} · {KIND_LABEL[kind]}</span>
              {onSelect ? <button type="button" className="font-bold underline" onClick={() => onSelect(v)}>View</button> : null}
            </div>
            <div className="mt-0.5 opacity-80">
              {v.origin === "ai" ? "Prepared by HAN" : v.created_by.display_name} · {formatDate(v.created_at)}
              {v.approval ? ` · ${v.approval.decision === "approved" ? "Approved" : "Rejected"} by ${v.approval.approver.display_name}` : ""}
            </div>
            {v.change_note ? <div className="mt-0.5 italic">{v.change_note}</div> : null}
            {v.approval?.comment ? <div className="mt-0.5 italic">“{v.approval.comment}”</div> : null}
          </li>
        );
      })}
    </ol>
  );
}
