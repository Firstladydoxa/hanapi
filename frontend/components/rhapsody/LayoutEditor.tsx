"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type RhapsodyAssignmentDetail, type RhapsodySegmentOut } from "@/lib/api";
import { Alert, Spinner } from "@/components/ui";
import { AdminOnly } from "./publishingShared";
import { RichText } from "./RichText";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const plain = (t: string) => t.replace(/<[^>]*>/g, "");

function Paragraph({ seg, assignmentId, dir, onSaved, onError }: { seg: RhapsodySegmentOut; assignmentId: string; dir: "ltr" | "rtl"; onSaved: (s: RhapsodySegmentOut) => void; onError: (t: string) => void }) {
  const [text, setText] = useState(seg.target_text);
  const [busy, setBusy] = useState(false);
  const dirty = text !== seg.target_text;
  async function save() {
    setBusy(true);
    try {
      const r = await api.rhapsody.adminEdit(assignmentId, seg.id, text);
      onSaved({ ...seg, target_text: r.target_text, current_version_id: r.version_id, version_number: r.version_number });
    } catch (x) { onError(errText(x)); } finally { setBusy(false); }
  }
  return (
    <div className="card p-3 space-y-2">
      <div className="flex items-center justify-between gap-2 text-xs text-ink-muted">
        <span className="font-mono">{seg.stable_key}</span>
        {dirty ? <span className="font-semibold text-red-700">Unsaved changes</span> : <span>Saved · v{seg.version_number ?? 0}</span>}
      </div>
      <p className="text-xs text-ink-muted" lang="en">{plain(seg.source_text)}</p>
      <RichText label={`Paragraph ${seg.stable_key}`} dir={dir} value={text} onChange={setText} minHeight={60} />
      <div className="flex gap-2">
        <button className="btn btn-primary min-h-[32px] px-3 py-1 text-xs" disabled={!dirty || busy || !text.trim()} onClick={() => void save()}>{busy ? "Saving…" : "Save"}</button>
        <button className="btn btn-secondary min-h-[32px] px-3 py-1 text-xs" disabled={!dirty || busy} onClick={() => setText(seg.target_text)}>Discard</button>
      </div>
    </div>);
}

export function LayoutEditor({ assignmentId }: { assignmentId: string }) {
  const [a, setA] = useState<RhapsodyAssignmentDetail | null>(null);
  const [rtl, setRtl] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const load = useCallback(async () => {
    try {
      const d = await api.rhapsody.assignment(assignmentId);
      setA(d); setSel((s) => s ?? d.sections.find((x) => d.segments.some((g) => g.section_id === x.id))?.id ?? null);
      const p = (await api.publishing.profiles()).find((x) => x.language_code === d.target_language);
      setRtl(p?.direction === "rtl");
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, [assignmentId]);
  useEffect(() => { void load(); }, [load]);
  const sections = useMemo(() => (a?.sections ?? []).filter((s) => a?.segments.some((g) => g.section_id === s.id)), [a]);
  const segs = useMemo(() => (a?.segments ?? []).filter((g) => g.section_id === sel).sort((x, y) => x.sequence - y.sequence), [a, sel]);

  if (!a) return notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : <Spinner />;
  const replace = (s: RhapsodySegmentOut) => { setA({ ...a, segments: a.segments.map((g) => (g.id === s.id ? s : g)) }); setNotice({ kind: "success", text: "Saved. Preview the layout to see it; any existing proof must be regenerated." }); };
  return (
    <AdminOnly>
      <div className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Link className="text-xs underline" href="/rhapsody/publishing/production">← Edition production</Link>
            <h1 className="text-xl font-bold">Layout editor · {a.edition.title} · {a.target_language.toUpperCase()}</h1>
            <p className="text-sm text-ink-muted">Light corrections before layout. Use bold, italic, underline and font size; changes are saved under the same paragraph and HAN uses them in the final layout.</p>
          </div>
          <a className="btn btn-secondary" href={api.rhapsody.layoutUrl(a.id)} target="_blank" rel="noreferrer">Preview layout</a>
        </div>
        {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
        <div className="grid gap-4 md:grid-cols-[240px_1fr]">
          <nav aria-label="Articles" className="card p-2 max-h-[70vh] overflow-auto space-y-1">
            {sections.map((s) => (
              <button key={s.id} className={`block w-full rounded-md px-2 py-1.5 text-left text-xs ${sel === s.id ? "bg-ink text-white" : "hover:bg-gray-100"}`} onClick={() => { setSel(s.id); setNotice(null); }}>
                {s.day_number ? <b>Day {s.day_number} · </b> : null}{plain(s.title || s.stable_key).slice(0, 40)}
              </button>))}
          </nav>
          <div className="space-y-3">
            {segs.map((g) => <Paragraph key={`${g.id}-${g.current_version_id}`} seg={g} assignmentId={a.id} dir={rtl ? "rtl" : "ltr"} onSaved={replace} onError={(t) => setNotice({ kind: "error", text: t })} />)}
          </div>
        </div>
      </div>
    </AdminOnly>);
}
