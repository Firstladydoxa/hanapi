"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type RhapsodyEdition, type RhapsodyMasterPreview } from "@/lib/api";
import { formatDate } from "@/lib/labels";
import { Alert, Spinner } from "@/components/ui";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function EditionAdmin({ editionId }: { editionId: string }) {
  const [edition, setEdition] = useState<RhapsodyEdition | null>(null);
  const [preview, setPreview] = useState<RhapsodyMasterPreview | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [tpl, setTpl] = useState<File | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const e = await api.rhapsody.edition(editionId);
      setEdition(e);
      const latest = e.master_versions[0];
      setSelected((s) => s ?? latest?.id ?? null);
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, [editionId]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (selected) api.rhapsody.master(editionId, selected).then(setPreview).catch((x) => setNotice({ kind: "error", text: errText(x) })); }, [editionId, selected]);

  async function layout(ev: FormEvent) {
    ev.preventDefault();
    if (!file) return;
    setBusy(true); setNotice(null);
    try {
      const f = new FormData(); f.append("file", file);
      const src = await api.rhapsody.upload(editionId, f);
      const g = new FormData(); g.append("source_file_id", src.id);
      if (tpl) { const t = new FormData(); t.append("file", tpl); const ts = await api.rhapsody.upload(editionId, t); g.append("template_file_id", ts.id); }
      const r = await api.rhapsody.ingest(editionId, g);
      setFile(null); setTpl(null); setSelected(r.master_version_id ?? null);
      await load();
      setNotice({ kind: "success", text: "HAN laid out the master. Review it below, then activate it." });
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  async function activate() {
    if (!selected) return;
    setBusy(true);
    try { await api.rhapsody.activate(editionId, selected); await load(); setNotice({ kind: "success", text: "Master activated. Translators can now start translating." }); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }

  if (!edition) return notice ? <Alert>{notice.text}</Alert> : <Spinner label="Loading edition" />;
  const v = preview?.validation;
  const master = edition.master_versions.find((m) => m.id === selected);
  const active = edition.active_master_version_id === selected;
  return (
    <div className="space-y-6">
      <Link href="/rhapsody" className="text-sm text-ink-muted">← All editions</Link>
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <div className="card"><div className="flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-bold">{edition.title}</h2><p className="text-xs text-ink-muted">Status: {edition.status}</p></div>
        {selected ? <button className="btn btn-primary" disabled={busy || active || !!v?.blocking_errors?.length} onClick={() => void activate()}>{active ? "Active master" : "Review done — activate for translators"}</button> : null}
      </div></div>

      <form className="card grid gap-3 md:grid-cols-2" onSubmit={layout}>
        <div className="md:col-span-2"><h3 className="font-bold">Ask HAN to lay out this month</h3>
          <p className="text-xs text-ink-muted">Upload the English Word manuscript (30/31 articles). HAN extracts each article and places it into the master template. Cover and introduction are reused from the previous edition, with the month updated. You can also say it in chat.</p></div>
        <div><label className="text-xs font-semibold" htmlFor="m">Manuscript (.docx)</label><input id="m" className="input" type="file" accept=".docx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
        <div><label className="text-xs font-semibold" htmlFor="t">Template (.xliff, only if changed)</label><input id="t" className="input" type="file" accept=".xlf,.xliff" onChange={(e) => setTpl(e.target.files?.[0] ?? null)} /></div>
        <div className="md:col-span-2"><button className="btn btn-primary" disabled={busy || !file}>{busy ? "HAN is working…" : "Start layout"}</button></div>
      </form>

      {edition.master_versions.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
          <div className="card space-y-2"><h3 className="font-bold">Master versions</h3>
            {edition.master_versions.map((m) => (
              <button key={m.id} className={`btn w-full justify-between ${m.id === selected ? "btn-primary" : "btn-secondary"}`} onClick={() => setSelected(m.id)}>
                <span>v{m.version_number}{m.id === edition.active_master_version_id ? " · active" : ""}</span><span className="text-xs">{m.segment_count} paragraphs</span></button>))}
            {master ? <p className="text-xs text-ink-muted">{master.activated_at ? `Activated ${formatDate(master.activated_at)}` : "Not activated"}</p> : null}
          </div>
          <div className="space-y-4">
            {v ? (<div className="card"><h3 className="font-bold">Validation</h3>
              <p className="mt-1 text-sm">Articles found: <b>{v.articles ?? "—"}</b> / {v.expected_articles ?? "—"} · Locked (untranslated) items: <b>{v.locked_segments ?? 0}</b></p>
              {v.blocking_errors?.length ? <Alert>{v.blocking_errors.join(" ")}</Alert> : null}
              {v.warnings?.length ? <ul className="mt-2 list-disc pl-5 text-sm text-warn-text">{v.warnings.map((w) => <li key={w}>{w}</li>)}</ul> : <p className="mt-2 text-sm text-ok-text">No warnings.</p>}
            </div>) : null}
            {preview ? (<div className="card max-h-[640px] space-y-4 overflow-y-auto"><h3 className="font-bold">Master preview</h3>
              {preview.sections.map((s) => (
                <details key={s.id} open={s.type === "daily_article" && s.day_number === 1}>
                  <summary className="cursor-pointer text-sm font-semibold">{s.title} <span className="text-xs font-normal text-ink-muted">({s.type.replace("_", " ")})</span></summary>
                  <div className="mt-2 space-y-1 border-l border-line pl-3 text-sm">
                    {preview.segments.filter((g) => g.section_id === s.id).map((g) => <p key={g.id} className={g.metadata?.locked ? "text-ink-muted" : ""}>{g.source_text}</p>)}
                  </div></details>))}
            </div>) : null}
          </div>
        </div>) : null}
    </div>
  );
}
