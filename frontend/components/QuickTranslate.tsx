"use client";

import { useMemo, useState, type FormEvent } from "react";
import { api, ApiError, type Direction, type ProjectDetail, type TranslateResponse } from "@/lib/api";
import { TIER_LABEL } from "@/lib/labels";
import { Alert } from "./ui";
import { ReviewPanel } from "./ReviewPanel";

export const usableDirections = (project: ProjectDetail): Direction[] => project.language_directions.filter((d) => d.readiness_tier !== "unsupported");
export const pairKey = (d: Pick<Direction, "source_code" | "target_code">) => `${d.source_code}>${d.target_code}`;

export function QuickTranslate({ project, names, onOpenWorkspace }: { project: ProjectDetail; names: Record<string, string>; onOpenWorkspace: (translationId: string) => void }) {
  const directions = useMemo(() => usableDirections(project), [project]);
  const sources = useMemo(() => Array.from(new Set(directions.map((d) => d.source_code))), [directions]);
  const [from, setFrom] = useState(directions[0]?.source_code ?? "");
  const targets = useMemo(() => directions.filter((d) => d.source_code === from), [directions, from]);
  const [to, setTo] = useState(directions[0]?.target_code ?? "");
  const pair = `${from}>${to}`;
  const chosen = targets.find((d) => d.target_code === to);
  const [text, setText] = useState("");
  const [context, setContext] = useState("");
  const [result, setResult] = useState<TranslateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const label = (c: string) => names[c] ?? c.toUpperCase();

  async function submit(e: FormEvent) {
    e.preventDefault();
    const [source, target] = pair.split(">");
    if (!source || !target || !text.trim()) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.translate({ project_id: project.id, source_language: source, target_language: target, text, context: context.trim() || undefined }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "I'm sorry, I couldn't complete the translation at the moment. Please try again shortly.");
    } finally {
      setBusy(false);
    }
  }

  if (directions.length === 0) {
    return <Alert kind="info">No language pairs are available for this project yet. Please contact your TNI administrator.</Alert>;
  }

  return (
    <div className="card space-y-4">
      <h2 className="text-lg font-semibold">Quick translation</h2>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="qt-from">From</label>
            <select id="qt-from" className="input" value={from} onChange={(e) => { setFrom(e.target.value); setTo(directions.find((d) => d.source_code === e.target.value)?.target_code ?? ""); }}>
              {sources.map((c) => <option key={c} value={c}>{label(c)}</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="qt-to">To</label>
            <select id="qt-to" className="input" value={to} onChange={(e) => setTo(e.target.value)}>
              {targets.map((d) => <option key={d.target_code} value={d.target_code}>{label(d.target_code)} ({TIER_LABEL[d.readiness_tier]})</option>)}
            </select>
          </div>
          {chosen?.readiness_tier === "experimental" ? <p className="text-xs text-ink-muted sm:col-span-2">This language is in controlled testing. Drafts are experimental and need careful human review.</p> : null}
        </div>
        <div>
          <label className="label" htmlFor="qt-text">Text to translate</label>
          <textarea id="qt-text" className="input min-h-[120px]" maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste or type the text…" />
          <p className="mt-1 text-right text-xs text-ink-muted">{text.length.toLocaleString()} / 4,000</p>
        </div>
        <div>
          <label className="label" htmlFor="qt-context">Context (optional)</label>
          <input id="qt-context" className="input" maxLength={5000} value={context} onChange={(e) => setContext(e.target.value)} placeholder="Audience, purpose or preferred tone" />
        </div>
        <button className="btn btn-primary" type="submit" disabled={busy || !text.trim()}>{busy ? "Preparing draft…" : "Prepare draft"}</button>
      </form>
      {error ? <Alert>{error}</Alert> : null}
      {result ? (
        <div className="space-y-3 border-t border-line pt-4">
          <Alert kind="success">{result.message}</Alert>
          <ReviewPanel key={result.translation_id} translationId={result.translation_id} canApprove={project.can_approve} onOpenWorkspace={() => onOpenWorkspace(result.translation_id)} onAskHan={() => window.location.assign(`/projects/${project.id}/chat?about=${encodeURIComponent(result.translation_id)}`)}
            context={{ warnings: result.warnings, tm_matches: result.tm_matches, terminology: result.terminology, review_note: result.review_note }} />
        </div>
      ) : null}
    </div>
  );
}
