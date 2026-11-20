"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type RhapsodyAssignmentDetail, type RhapsodySegmentOut } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Spinner } from "@/components/ui";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const ORIGIN: Record<string, string> = { ai: "bg-warn/15 text-warn-text", human: "bg-ok/15 text-ok-text", tm: "bg-info/15 text-info-text" };

function Row({ seg, a, onSaved, onError }: { seg: RhapsodySegmentOut; a: RhapsodyAssignmentDetail; onSaved: (s: RhapsodySegmentOut) => void; onError: (t: string) => void }) {
  const [text, setText] = useState(seg.target_text);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setText(seg.target_text); }, [seg.target_text, seg.current_version_id]);
  const locked = !!seg.metadata?.locked;
  const dirty = text !== seg.target_text;
  const needsReview = seg.origin === "ai";

  async function run(kind: "save" | "redraft") {
    setBusy(true);
    try {
      const fn = kind === "save" ? api.rhapsody.save : api.rhapsody.redraft;
      const r = await fn(a.id, seg.id, kind === "save" ? text : seg.source_text, seg.current_version_id);
      onSaved({ ...seg, target_text: r.target_text, current_version_id: r.version_id, version_number: r.version_number, translation_status: r.status, origin: r.origin ?? (kind === "save" ? "human" : "ai"), warnings: r.warnings ?? [] });
    } catch (e) { onError(errText(e)); } finally { setBusy(false); }
  }
  return (
    <div className="grid gap-3 border-t border-line py-3 md:grid-cols-2">
      <p className="whitespace-pre-wrap text-sm">{seg.source_text}</p>
      <div className="space-y-2">
        <textarea className="input min-h-[84px]" value={text} disabled={!a.can_edit || locked} onChange={(e) => setText(e.target.value)} aria-label="Translation" />
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {seg.origin ? <span className={`rounded-full px-2 py-0.5 font-semibold ${ORIGIN[seg.origin] ?? ""}`}>{locked ? "locked" : seg.origin === "ai" ? "HAN draft · review" : seg.origin}{seg.draft_source ? ` · ${seg.draft_source}` : ""}</span> : null}
          {a.can_edit && !locked ? <>
            <button className="btn btn-primary min-h-[32px] px-3 py-1 text-xs" disabled={busy || !text.trim() || (!dirty && !needsReview)} onClick={() => void run("save")}>{dirty ? "Save" : "Confirm"}</button>
            <button className="btn btn-secondary min-h-[32px] px-3 py-1 text-xs" disabled={busy} onClick={() => void run("redraft")}>Redraft with HAN</button></> : null}
        </div>
        {seg.glossary.length ? <p className="text-xs text-ink-muted">Glossary: {seg.glossary.map((g) => `${g.source} → ${g.target}`).join("; ")}</p> : null}
        {seg.warnings.map((w) => <p key={w} className="text-xs text-warn-text">⚠ {w}</p>)}
      </div>
    </div>
  );
}

export function TranslationEditor({ assignmentId }: { assignmentId: string }) {
  const { user } = useAuth();
  const [a, setA] = useState<RhapsodyAssignmentDetail | null>(null);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [comment, setComment] = useState("");
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => api.rhapsody.assignment(assignmentId).then(setA).catch((e) => setMsg({ kind: "error", text: errText(e) })), [assignmentId]);
  useEffect(() => { void load(); }, [load]);

  const running = a?.draft.status === "running";
  useEffect(() => {
    if (!running) return;
    timer.current = setInterval(() => { void load(); }, 3000);
    return () => { if (timer.current) clearInterval(timer.current); };
  }, [running, load]);

  const groups = useMemo(() => (a?.sections ?? []).map((s) => ({ s, segs: (a?.segments ?? []).filter((g) => g.section_id === s.id) })).filter((g) => g.segs.length), [a]);
  if (!a) return msg ? <Alert>{msg.text}</Alert> : <Spinner label="Loading translation" />;

  const editable = a.segments.filter((g) => !g.metadata?.locked);
  const done = editable.filter((g) => g.origin && g.origin !== "ai").length;
  const pct = editable.length ? Math.round((done / editable.length) * 100) : 0;
  const isReviewer = user?.role === "reviewer" || user?.role === "tni_admin" || user?.role === "technical_admin";
  const update = (s: RhapsodySegmentOut) => setA((cur) => cur && { ...cur, segments: cur.segments.map((g) => (g.id === s.id ? s : g)) });
  const act = (fn: () => Promise<unknown>, ok: string) => async () => { try { await fn(); setMsg({ kind: "success", text: ok }); await load(); } catch (e) { setMsg({ kind: "error", text: errText(e) }); } };

  return (
    <div className="space-y-5">
      <Link href="/rhapsody" className="text-sm text-ink-muted">← Rhapsody</Link>
      <div className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h1 className="text-xl font-bold">{a.edition.title} → {a.target_language.toUpperCase()}</h1>
            <p className="text-xs text-ink-muted">Translator: {a.translator ?? "—"} · Status: {a.status.replace("_", " ")}</p></div>
          <div className="flex flex-wrap gap-2">
            {a.can_edit ? <button className="btn btn-secondary" disabled={running} onClick={act(() => api.rhapsody.draftAll(a.id), "HAN is drafting the remaining paragraphs.")}>{running ? `Drafting ${a.draft.done}/${a.draft.total}…` : "Draft all with HAN"}</button> : null}
            {a.can_edit ? <button className="btn btn-primary" onClick={act(() => api.rhapsody.submit(a.id), "Submitted for proofreading.")}>Submit for review</button> : null}
            <a className="btn btn-secondary" href={api.rhapsody.exportUrl(a.id)}>Export DOCX</a>
            <a className="btn btn-secondary" href={api.rhapsody.layoutUrl(a.id)} target="_blank" rel="noreferrer">Preview book layout (PDF)</a>
          </div>
        </div>
        <div><div className="h-2 overflow-hidden rounded-full bg-line"><div className="h-full bg-ok" style={{ width: `${pct}%` }} /></div>
          <p className="mt-1 text-xs text-ink-muted">{done} of {editable.length} paragraphs reviewed ({pct}%). HAN drafts must be confirmed or edited before submission.</p></div>
        {a.draft.note ? <p className="text-xs text-ink-muted">{a.draft.note}</p> : null}
        {msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : null}
      </div>

      {a.status === "submitted" && isReviewer ? (
        <div className="card flex flex-wrap items-center gap-2"><b className="text-sm">Proofreading</b>
          <button className="btn btn-primary" onClick={act(() => api.rhapsody.review(a.id, "approved"), "Approved.")}>Approve</button>
          <button className="btn btn-danger" onClick={act(() => api.rhapsody.review(a.id, "changes_requested", comment || undefined), "Changes requested.")}>Request changes</button></div>) : null}

      <div className="card">
        <div className="hidden grid-cols-2 gap-3 text-xs font-extrabold uppercase tracking-[0.12em] text-ink-muted md:grid"><span>English master</span><span>{a.target_language.toUpperCase()}</span></div>
        {groups.map(({ s, segs }) => (
          <details key={s.id} className="mt-3">
            <summary className="cursor-pointer text-base font-bold">{s.title}</summary>
            {segs.map((g) => <Row key={g.id} seg={g} a={a} onSaved={update} onError={(t) => setMsg({ kind: "error", text: t })} />)}
          </details>))}
      </div>

      <div className="card space-y-2"><h2 className="font-bold">Comments</h2>
        {a.comments.length === 0 ? <p className="text-sm text-ink-muted">No comments yet.</p> : a.comments.map((c) => <p key={c.id} className="text-sm"><b>{c.author}:</b> {c.body}</p>)}
        <div className="flex gap-2"><input className="input" value={comment} placeholder="Add a note for the proofreader…" onChange={(e) => setComment(e.target.value)} />
          <button className="btn btn-secondary" disabled={!comment.trim()} onClick={act(async () => { await api.rhapsody.comment(a.id, comment); setComment(""); }, "Comment added.")}>Send</button></div></div>
    </div>
  );
}
