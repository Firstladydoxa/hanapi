"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, type PublishingFont } from "@/lib/api";
import { Alert, EmptyState, Spinner } from "@/components/ui";
import { AdminOnly, bytes, errText } from "./publishingShared";

const SAMPLE = "Die Here is my Herder — Éé Ôô ʼNŉ 0123456789";
const faceName = (id: string) => `han-font-${id}`;

/** Registers each library font in the browser (authenticated, same-origin) so specimens render in the real typeface. */
function useFontFaces(fonts: PublishingFont[] | null) {
  const [ready, setReady] = useState<Set<string>>(new Set());
  const requested = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const f of fonts ?? []) {
      if (requested.current.has(f.id)) continue;
      requested.current.add(f.id);
      const face = new FontFace(faceName(f.id), `url(${api.publishing.fontFileUrl(f.id)})`);
      face.load().then((loaded) => { document.fonts.add(loaded); setReady((r) => new Set(r).add(f.id)); }).catch(() => undefined);
    }
  }, [fonts]);
  return ready;
}

function EditDialog({ font, onClose, onSaved }: { font: PublishingFont; onClose: () => void; onSaved: (msg: string) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const d = new FormData(e.currentTarget);
    setBusy(true); setErr(null);
    try {
      await api.publishing.updateFont(font.id, { family: String(d.get("family")), style: String(d.get("style")), license_name: String(d.get("license_name")), license_note: String(d.get("license_note") ?? "") });
      onSaved(`${font.family} updated.`);
    } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  }
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label={`Edit ${font.family}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <form className="card modal space-y-3" onSubmit={(e) => void submit(e)}>
        <h3 className="text-lg font-bold">Edit font details</h3>
        <p className="text-xs text-ink-muted">The font file itself cannot be changed. To replace it, add the new file and reassign it in the profiles.</p>
        {err ? <Alert kind="error">{err}</Alert> : null}
        <div><label className="label" htmlFor="ef">Family</label><input id="ef" name="family" className="input" defaultValue={font.family} required maxLength={200} /></div>
        <div><label className="label" htmlFor="es">Style</label><input id="es" name="style" className="input" defaultValue={font.style} required maxLength={80} /></div>
        <div><label className="label" htmlFor="el">Licence</label><input id="el" name="license_name" className="input" defaultValue={font.license_name} required maxLength={200} /></div>
        <div><label className="label" htmlFor="en">Licence notes</label><textarea id="en" name="license_note" className="input" rows={3} defaultValue={font.license_note ?? ""} maxLength={1000} /></div>
        <div className="flex justify-end gap-2"><button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
      </form>
    </div>
  );
}

function DeleteDialog({ font, onClose, onDeleted }: { font: PublishingFont; onClose: () => void; onDeleted: (msg: string) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const used = font.used_by ?? [];
  async function go() {
    setBusy(true); setErr(null);
    try { await api.publishing.deleteFont(font.id); onDeleted(`${font.family} ${font.style} deleted.`); } catch (x) { setErr(errText(x)); } finally { setBusy(false); }
  }
  return (
    <div className="modal-back" role="alertdialog" aria-modal="true" aria-label={`Delete ${font.family}`} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="card modal space-y-3">
        <h3 className="text-lg font-bold">Delete {font.family} {font.style}?</h3>
        {used.length ? <Alert kind="error">This font is used by {used.map((u) => `${u.language.toUpperCase()} (${u.role})`).join(", ")}. Reassign those roles before deleting it.</Alert>
          : <p className="text-sm">The file is permanently removed from the server. This cannot be undone.</p>}
        {err ? <Alert kind="error">{err}</Alert> : null}
        <div className="flex justify-end gap-2"><button className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-danger" disabled={busy || used.length > 0} onClick={() => void go()}>{busy ? "Deleting…" : "Delete font"}</button></div>
      </div>
    </div>
  );
}

function Library() {
  const params = useSearchParams();
  const [fonts, setFonts] = useState<PublishingFont[] | null>(null);
  const [q, setQ] = useState("");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [sample, setSample] = useState(SAMPLE);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(params.get("added") ? { kind: "success", text: "Font added to the library." } : null);
  const [editing, setEditing] = useState<PublishingFont | null>(null);
  const [deleting, setDeleting] = useState<PublishingFont | null>(null);

  const load = useCallback(async () => { try { setFonts(await api.publishing.fonts()); } catch (x) { setNotice({ kind: "error", text: errText(x) }); } }, []);
  useEffect(() => { void load(); }, [load]);
  const ready = useFontFaces(fonts);
  const shown = useMemo(() => (fonts ?? []).filter((f) => `${f.family} ${f.style} ${f.license_name}`.toLowerCase().includes(q.trim().toLowerCase())), [fonts, q]);
  const done = (msg: string) => { setEditing(null); setDeleting(null); setNotice({ kind: "success", text: msg }); void load(); };

  const actions = (f: PublishingFont) => (
    <span className="flex gap-2"><button className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" onClick={() => setEditing(f)}>Edit</button>
      <button className="btn btn-danger min-h-[34px] px-3 py-1 text-xs" onClick={() => setDeleting(f)}>Delete</button></span>);
  const specimen = (f: PublishingFont, size: number) => (
    <p className="truncate" style={{ fontFamily: ready.has(f.id) ? `"${faceName(f.id)}", serif` : undefined, fontSize: size, lineHeight: 1.3, opacity: ready.has(f.id) ? 1 : .35 }} title={sample}>{sample}</p>);
  const scripts = (f: PublishingFont) => Object.entries(f.coverage?.scripts ?? {}).filter(([, on]) => on).map(([k]) => k);

  return (
    <div className="space-y-5">
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <div className="card flex flex-wrap items-center gap-3">
        <input className="input max-w-xs" type="search" placeholder="Search family, style or licence" aria-label="Search fonts" value={q} onChange={(e) => setQ(e.target.value)} />
        <input className="input max-w-sm" aria-label="Specimen text" value={sample} onChange={(e) => setSample(e.target.value)} />
        <div className="ml-auto flex items-center gap-2">
          <div role="group" aria-label="View" className="flex overflow-hidden rounded-xl border" style={{ borderColor: "var(--han-line-strong)" }}>
            {(["cards", "table"] as const).map((v) => <button key={v} className={`px-3 py-2 text-xs font-semibold ${view === v ? "bg-brand-light" : ""}`} aria-pressed={view === v} onClick={() => setView(v)}>{v === "cards" ? "Cards" : "Table"}</button>)}
          </div>
          <Link className="btn btn-primary" href="/rhapsody/publishing/fonts/new">＋ Add a font</Link>
        </div>
      </div>

      {!fonts ? <Spinner /> : fonts.length === 0 ? <EmptyState title="No fonts yet">English uses built-in fonts until you add some. <Link className="underline" href="/rhapsody/publishing/fonts/new">Add the first font</Link>.</EmptyState>
        : shown.length === 0 ? <EmptyState title="No fonts match your search" /> : view === "cards" ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((f) => (
              <article key={f.id} className="card flex flex-col gap-3">
                <div className="min-h-[64px] rounded-xl border p-3" style={{ borderColor: "var(--han-line)", background: "rgb(var(--han-sunken-rgb) / .5)" }}>{specimen(f, 22)}</div>
                <div className="flex items-start justify-between gap-2">
                  <div><h3 className="font-bold">{f.family}</h3><p className="text-xs text-ink-muted">{f.style} · {f.format.toUpperCase()} · {bytes(f.byte_size)}</p></div>
                  {actions(f)}
                </div>
                <p className="text-xs text-ink-muted">Licence: {f.license_name}</p>
                <div className="flex flex-wrap gap-1.5">
                  {scripts(f).map((s) => <span key={s} className="pill pill-grey">{s}</span>)}
                  {f.coverage?.glyph_count ? <span className="pill pill-grey">{f.coverage.glyph_count.toLocaleString()} glyphs</span> : null}
                  {f.coverage?.embedding_restricted ? <span className="pill pill-red">Embedding restricted</span> : null}
                </div>
                <div className="mt-auto border-t pt-2 text-xs" style={{ borderColor: "var(--han-line)" }}>
                  {f.used_by?.length ? <span className="flex flex-wrap items-center gap-1.5">Used by {f.used_by.map((u) => <span key={u.language + u.role} className="pill pill-violet">{u.language.toUpperCase()} · {u.role}</span>)}</span> : <span className="text-ink-muted">Not assigned to any language yet</span>}
                </div>
              </article>))}
          </div>) : (
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead><tr className="text-xs text-ink-muted"><th className="p-3">Family</th><th>Style</th><th>Specimen</th><th>Format</th><th>Size</th><th>Licence</th><th>Used by</th><th /></tr></thead>
              <tbody>{shown.map((f) => (
                <tr key={f.id} className="border-t align-middle">
                  <td className="p-3 font-semibold">{f.family}</td><td>{f.style}</td><td className="max-w-[260px]">{specimen(f, 16)}</td><td>{f.format.toUpperCase()}</td><td>{bytes(f.byte_size)}</td><td>{f.license_name}</td>
                  <td>{f.used_by?.length ? f.used_by.map((u) => `${u.language.toUpperCase()}·${u.role}`).join(", ") : <span className="text-ink-muted">—</span>}</td>
                  <td className="p-3">{actions(f)}</td>
                </tr>))}</tbody>
            </table>
          </div>)}
      {editing ? <EditDialog font={editing} onClose={() => setEditing(null)} onSaved={done} /> : null}
      {deleting ? <DeleteDialog font={deleting} onClose={() => setDeleting(null)} onDeleted={done} /> : null}
    </div>
  );
}

export function FontLibrary() {
  return <AdminOnly><Suspense fallback={<Spinner />}><Library /></Suspense></AdminOnly>;
}
