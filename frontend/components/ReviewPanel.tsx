"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Term, type TMMatch, type Translation, type Version, type Warning } from "@/lib/api";
import { KIND_LABEL, KIND_STYLE, versionKind } from "@/lib/labels";
import { Alert, Spinner } from "./ui";
import { VersionHistory } from "./VersionHistory";
import { Warnings } from "./Warnings";

export interface ReviewContext {
  warnings?: Warning[];
  tm_matches?: TMMatch[];
  terminology?: Term[];
  review_note?: string | null;
}

interface Props {
  translationId: string;
  canApprove: boolean;
  context?: ReviewContext;
  onOpenWorkspace?: () => void;
  /** Shows "Ask HAN about this": hands this translation to the chat as its one piece of context. */
  onAskHan?: () => void;
  /** Called after a version is saved or a decision is recorded (lets a parent refresh progress). */
  onChanged?: () => void;
  /** Test seam / reuse: provide a loaded translation instead of fetching. */
  initial?: Translation;
}

/**
 * Review panel: shows the suggestion, lets the translator edit (each save = a NEW version) and, only when
 * permitted, approve or reject that exact version. Approval is always an explicit button click + confirmation.
 */
export function ReviewPanel({ translationId, canApprove, context, onOpenWorkspace, onAskHan, onChanged, initial }: Props) {
  const [translation, setTranslation] = useState<Translation | null>(initial ?? null);
  const [selectedId, setSelectedId] = useState<string | null>(initial?.current_version_id ?? null);
  const [text, setText] = useState("");
  const [warnings, setWarnings] = useState<Warning[]>(context?.warnings ?? []);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (focusId?: string) => {
    const t = await api.translation(translationId);
    setTranslation(t);
    const id = focusId ?? t.current_version_id;
    setSelectedId(id);
    setText(t.versions.find((v) => v.version_id === id)?.target_text ?? "");
  }, [translationId]);

  useEffect(() => {
    if (initial) { setText(initial.versions.find((v) => v.version_id === initial.current_version_id)?.target_text ?? ""); return; }
    load().catch((e: unknown) => setNotice({ kind: "error", text: e instanceof ApiError ? e.message : "Unable to load this translation." }));
  }, [initial, load]);

  if (!translation) return notice ? <Alert>{notice.text}</Alert> : <Spinner label="Loading draft" />;

  const selected: Version | undefined = translation.versions.find((v) => v.version_id === selectedId);
  const isLatest = selected?.version_id === translation.current_version_id;
  const dirty = !!selected && text !== selected.target_text;
  const decided = selected ? selected.approval_state !== "unapproved" : true;
  const kind = selected ? versionKind(selected) : "ai";

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setNotice(null);
    try { await action(); } catch (e) { setNotice({ kind: "error", text: e instanceof ApiError ? e.message : "Something went wrong. Please try again." }); } finally { setBusy(false); }
  }

  const save = () => run(async () => {
    if (!selected) return;
    const r = await api.saveVersion(translationId, { target_text: text, parent_version_id: selected.version_id });
    setWarnings(r.warnings);
    await load(r.version.version_id);
    onChanged?.();
    setNotice({ kind: "success", text: "Your edits were saved as a new version. It still needs approval." });
  });

  const decide = (decision: "approved" | "rejected") => run(async () => {
    if (!selected) return;
    const prompt = decision === "approved"
      ? "Approve this exact version and add it to this project's Translation Memory?"
      : "Reject this version? It will not be added to the Translation Memory.";
    if (!window.confirm(prompt)) return;
    const r = await api.decide(selected.version_id, decision);
    await load(selected.version_id);
    onChanged?.();
    setNotice({ kind: "success", text: r.message });
  });

  const checkNow = () => run(async () => {
    const r = await api.qaCheck({ project_id: translation.project_id, source_text: translation.source_text, target_text: text,
      source_language: translation.source_language, target_language: translation.target_language });
    setWarnings(r.warnings);
  });

  return (
    <section className="space-y-4" aria-label="Translation review">
      <div>
        <p className="label">Source ({translation.source_language.toUpperCase()})</p>
        <p className="whitespace-pre-wrap rounded-lg border border-line bg-wash px-3 py-2 text-sm">{translation.source_text}</p>
      </div>
      <div>
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
          <label className="label mb-0" htmlFor={`target-${translationId}`}>Suggested translation ({translation.target_language.toUpperCase()}) — editable</label>
          <span data-testid="version-kind" className={`rounded-full border px-2.5 py-0.5 text-[11px] font-bold ${KIND_STYLE[kind]}`}>
            {selected ? `Version ${selected.version_number} · ${KIND_LABEL[kind]}` : "No version"}
          </span>
        </div>
        <textarea id={`target-${translationId}`} className={`input min-h-[120px] leading-relaxed ${kind === "approved" ? "border-ok/40 bg-ok/15" : ""}`}
          value={text} onChange={(e) => setText(e.target.value)} maxLength={200000} />
      </div>
      {context?.review_note ? <Alert kind="info">{context.review_note}</Alert> : null}
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" className="btn btn-secondary" onClick={() => void save()} disabled={busy || !dirty}>Save as new version</button>
        <button type="button" className="btn btn-secondary" onClick={() => void checkNow()} disabled={busy}>Run checks</button>
        {canApprove ? (
          <>
            <button type="button" className="btn btn-primary" onClick={() => void decide("approved")} disabled={busy || dirty || decided || !isLatest}>Approve version</button>
            <button type="button" className="btn btn-danger" onClick={() => void decide("rejected")} disabled={busy || dirty || decided || !isLatest}>Reject</button>
          </>
        ) : null}
        {onOpenWorkspace ? <button type="button" className="btn btn-secondary" onClick={onOpenWorkspace}>Open in Workspace</button> : null}
        {onAskHan ? <button type="button" className="btn btn-secondary" onClick={onAskHan}>Ask HAN about this</button> : null}
      </div>
      {!canApprove ? <p className="text-xs text-ink-muted">Approval isn&apos;t available to your role in this project.</p> : null}
      {dirty ? <p className="text-xs text-ink-muted">Save your edits before approving, so the approval applies to exactly what you reviewed.</p> : null}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-lg border border-line bg-surface p-3">
          <h3 className="mb-2 text-sm font-semibold">Quality checks</h3>
          <Warnings warnings={warnings} />
        </div>
        <div className="rounded-lg border border-line bg-surface p-3">
          <h3 className="mb-2 text-sm font-semibold">Project references</h3>
          <References tm={context?.tm_matches ?? []} terms={context?.terminology ?? []} />
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Version history</h3>
        <VersionHistory versions={translation.versions} selectedId={selectedId}
          onSelect={(v) => { setSelectedId(v.version_id); setText(v.target_text); }} />
      </div>
    </section>
  );
}

export function References({ tm, terms }: { tm: TMMatch[]; terms: Term[] }) {
  if (tm.length === 0 && terms.length === 0) return <p className="text-xs text-ink-muted">No project references matched this text.</p>;
  return (
    <ul className="space-y-2 text-xs">
      {terms.map((t) => (
        <li key={`${t.source_term}-${t.target_term}`}>
          <span className="font-bold">Term:</span> {t.source_term} → {t.target_term}
          {t.usage_note ? <span className="text-ink-muted"> · {t.usage_note}</span> : null}
          {t.forbidden.length ? <span className="text-danger-text"> · avoid: {t.forbidden.join(", ")}</span> : null}
        </li>
      ))}
      {tm.map((m) => (
        <li key={m.tm_id}>
          <span className="font-bold">Translation Memory · {m.match_percent}%</span>
          <div>{m.source_text}</div>
          <div className="text-ink-muted">{m.target_text}</div>
        </li>
      ))}
    </ul>
  );
}
