"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { api } from "@/lib/api";
import { Alert } from "@/components/ui";
import { AdminOnly, bytes, errText } from "./publishingShared";

const EXT = /\.(otf|ttf|woff2?)$/i;
const SAMPLE = "Die Here is my Herder — Éé Ôô ʼNŉ 0123456789";

function guess(name: string): { family: string; style: string } {
  const base = name.replace(EXT, "").replace(/[_]+/g, "-");
  const [fam, sty] = base.split("-");
  return { family: (fam ?? base).replace(/([a-z])([A-Z])/g, "$1 $2"), style: sty ? sty.replace(/([a-z])([A-Z])/g, "$1 $2") : "Regular" };
}

export function AddFont() {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [family, setFamily] = useState("");
  const [style, setStyle] = useState("Regular");
  const [license, setLicense] = useState("");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    const face = new FontFace("han-upload-preview", `url(${url})`);
    face.load().then((f) => document.fonts.add(f)).catch(() => undefined);
    return () => { URL.revokeObjectURL(url); };
  }, [file]);

  function pick(f: File | undefined) {
    if (!f) return;
    if (!EXT.test(f.name)) { setErr("Choose an OTF, TTF, WOFF or WOFF2 font file."); return; }
    setErr(null); setFile(f);
    const g = guess(f.name);
    if (!family) setFamily(g.family);
    if (style === "Regular") setStyle(g.style);
  }
  function drop(e: DragEvent) { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const body = new FormData();
    body.set("file", file); body.set("family", family); body.set("style", style); body.set("license_name", license);
    if (note.trim()) body.set("license_note", note);
    setBusy(true); setErr(null);
    try { await api.publishing.uploadFont(body); router.push("/rhapsody/publishing/fonts?added=1"); } catch (x) { setErr(errText(x)); setBusy(false); }
  }

  return (
    <AdminOnly>
      <form className="grid gap-5 lg:grid-cols-[1.1fr_1fr]" onSubmit={(e) => void submit(e)}>
        <div className="space-y-4">
          <div className="card space-y-4">
            <h2 className="text-lg font-bold">1 · Choose the font file</h2>
            <div role="button" tabIndex={0} aria-label="Choose or drop a font file"
              className="flex min-h-[170px] cursor-pointer flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed p-6 text-center"
              style={{ borderColor: drag ? "var(--han-violet)" : "var(--han-line-strong)", background: drag ? "rgb(var(--han-primary-rgb) / .08)" : undefined }}
              onClick={() => input.current?.click()} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.current?.click(); } }}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={drop}>
              <span aria-hidden className="text-3xl">Aa</span>
              {file ? <><strong>{file.name}</strong><span className="text-xs text-ink-muted">{bytes(file.size)} · click to replace</span></>
                : <><strong>Drag a font here, or click to browse</strong><span className="text-xs text-ink-muted">OTF, TTF, WOFF or WOFF2 · up to 15 MB</span></>}
              <input ref={input} type="file" accept=".otf,.ttf,.woff,.woff2" className="sr-only" aria-label="Font file" onChange={(e) => pick(e.target.files?.[0])} />
            </div>
          </div>
          <div className="card space-y-3">
            <h2 className="text-lg font-bold">2 · Describe it</h2>
            <div className="grid gap-3 md:grid-cols-2">
              <div><label className="label" htmlFor="af">Family</label><input id="af" className="input" required value={family} onChange={(e) => setFamily(e.target.value)} placeholder="Book Antiqua" maxLength={200} /></div>
              <div><label className="label" htmlFor="as">Style</label><input id="as" className="input" required value={style} onChange={(e) => setStyle(e.target.value)} placeholder="Regular, Bold, Italic…" maxLength={80} /></div>
            </div>
            <div><label className="label" htmlFor="al">Licence</label><input id="al" className="input" required value={license} onChange={(e) => setLicense(e.target.value)} placeholder="SIL Open Font Licence, Desktop licence…" maxLength={200} /></div>
            <div><label className="label" htmlFor="an">Licence notes (optional)</label><textarea id="an" className="input" rows={2} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} placeholder="Where it was obtained, licence reference, restrictions" /></div>
            <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
              <span>I confirm TNI is licensed to use this font and embed it in printed PDFs.</span></label>
          </div>
          {err ? <Alert kind="error">{err}</Alert> : null}
          <div className="flex gap-2"><button className="btn btn-primary" disabled={busy || !file || !confirm || !family.trim() || !license.trim()}>{busy ? "Uploading…" : "Add to font library"}</button>
            <Link className="btn btn-secondary" href="/rhapsody/publishing/fonts">Cancel</Link></div>
        </div>
        <aside className="card h-fit space-y-3 lg:sticky lg:top-4">
          <h2 className="text-lg font-bold">Live preview</h2>
          {file ? (<div className="space-y-3 rounded-xl border p-4" style={{ borderColor: "var(--han-line)", fontFamily: '"han-upload-preview", serif' }}>
            <p style={{ fontSize: 30, lineHeight: 1.2 }}>{family || "Family name"}</p><p style={{ fontSize: 16 }}>{SAMPLE}</p><p style={{ fontSize: 12 }}>ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz</p>
          </div>) : <p className="text-sm text-ink-muted">Choose a file to preview it here, including Afrikaans, French and German accents.</p>}
          <ul className="list-disc space-y-1 pl-5 text-xs text-ink-muted">
            <li>HAN checks the file signature and reads its glyph coverage when you upload.</li>
            <li>An identical file already in the library is rejected.</li>
            <li>After adding it, assign it to a language in <Link className="underline" href="/rhapsody/publishing/profiles">Typesetting profiles</Link>.</li>
          </ul>
        </aside>
      </form>
    </AdminOnly>
  );
}
