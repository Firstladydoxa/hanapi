"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type KnowledgeDetail, type KnowledgeDoc } from "@/lib/api";
import { formatDate } from "@/lib/labels";
import { Alert, Spinner } from "./ui";

const CATEGORIES = ["institutional", "guidelines", "terminology", "language_resources", "platform", "faq", "doctrine"];
const ROLES = ["translator", "reviewer", "project_manager", "team_leader", "tni_admin", "technical_admin", "auditor"];
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function KnowledgePanel() {
  const [docs, setDocs] = useState<KnowledgeDoc[] | null>(null);
  const [open, setOpen] = useState<KnowledgeDetail | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [form, setForm] = useState({ title: "", category: "guidelines", languages: "", roles: [] as string[], text: "" });
  const [file, setFile] = useState<File | null>(null);
  const [newText, setNewText] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => { api.admin.knowledge.list().then(setDocs).catch((e) => setNotice({ kind: "error", text: errText(e) })); }, []);
  useEffect(() => { load(); }, [load]);

  async function run(fn: () => Promise<KnowledgeDetail | unknown>, ok: string) {
    setBusy(true);
    try { const r = await fn(); if (r && typeof r === "object" && "versions" in r) setOpen(r as KnowledgeDetail); setNotice({ kind: "success", text: ok }); load(); } catch (e) { setNotice({ kind: "error", text: errText(e) }); } finally { setBusy(false); }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    const langs = form.languages.split(",").map((x) => x.trim()).filter(Boolean);
    if (file) {
      const fd = new FormData();
      fd.set("file", file); fd.set("title", form.title); fd.set("category", form.category); fd.set("languages", langs.join(",")); fd.set("audience_roles", form.roles.join(","));
      await run(() => api.admin.knowledge.upload(fd), "Uploaded as a draft. Review it, then approve a version to make it available.");
    } else {
      await run(() => api.admin.knowledge.create({ title: form.title, category: form.category, text: form.text, languages: langs, audience_roles: form.roles }), "Saved as a draft. Approve a version to make it available.");
    }
    setForm({ title: "", category: "guidelines", languages: "", roles: [], text: "" });
    setFile(null);
  }

  return (
    <div className="space-y-6">
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <section className="card space-y-3">
        <h2 className="text-lg font-semibold">Add knowledge</h2>
        <form onSubmit={create} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div><label className="label" htmlFor="k-title">Title</label><input id="k-title" className="input" required maxLength={300} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></div>
            <div><label className="label" htmlFor="k-cat">Category</label>
              <select id="k-cat" className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c} value={c}>{c.replace("_", " ")}</option>)}</select></div>
            <div><label className="label" htmlFor="k-lang">Languages (optional, comma separated codes)</label><input id="k-lang" className="input" placeholder="e.g. sw, fr — empty means all" value={form.languages} onChange={(e) => setForm({ ...form, languages: e.target.value })} /></div>
            <fieldset><legend className="label">Visible to (empty means everyone)</legend>
              <div className="flex flex-wrap gap-2 text-xs">{ROLES.map((r) => (
                <label key={r} className="flex items-center gap-1"><input type="checkbox" checked={form.roles.includes(r)} onChange={(e) => setForm({ ...form, roles: e.target.checked ? [...form.roles, r] : form.roles.filter((x) => x !== r) })} />{r.replace("_", " ")}</label>))}</div></fieldset>
          </div>
          <div><label className="label" htmlFor="k-file">Upload a file (.txt, .md, .docx or .pdf, up to 5 MB)</label><input id="k-file" type="file" accept=".txt,.md,.markdown,.docx,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></div>
          {!file ? <div><label className="label" htmlFor="k-text">…or paste the text</label><textarea id="k-text" className="input min-h-[140px]" required value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} /></div> : null}
          <button className="btn btn-primary" type="submit" disabled={busy || !form.title.trim()}>Save as draft</button>
        </form>
      </section>

      <section className="card space-y-3">
        <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Documents</h2>
          <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" disabled={busy} onClick={() => void run(() => api.admin.knowledge.reindex(), "Search index refreshed.")}>Refresh search index</button></div>
        {!docs ? <Spinner /> : docs.length === 0 ? <p className="text-sm text-ink-muted">No documents yet. HAN will say it has no approved TNI information until you add and approve some.</p> : (
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Title</th><th className="pr-4">Category</th><th className="pr-4">Status</th><th className="pr-4">Live version</th><th>Updated</th></tr></thead>
            <tbody>{docs.map((d) => (
              <tr key={d.id} className="border-t border-line">
                <td className="py-2 pr-4"><button type="button" className="font-semibold underline" onClick={() => void api.admin.knowledge.get(d.id).then(setOpen)}>{d.title}</button>{d.system_managed ? <span className="ml-2 text-[11px] text-ink-muted">built in</span> : null}</td>
                <td className="pr-4">{d.category.replace("_", " ")}</td><td className="pr-4">{d.status}</td><td className="pr-4">{d.approved_version ? `v${d.approved_version}` : "—"}</td><td>{formatDate(d.updated_at)}</td>
              </tr>))}</tbody></table></div>)}
      </section>

      {open ? (
        <section className="card space-y-3" aria-label="Document details">
          <div className="flex items-start justify-between gap-2"><h2 className="text-lg font-semibold">{open.title}</h2><button type="button" className="text-xs underline" onClick={() => setOpen(null)}>Close</button></div>
          <p className="text-xs text-ink-muted">Status: {open.status}. {open.chunk_count} searchable passages. {open.system_managed ? "Managed by HAN; cannot be edited here." : ""}</p>
          <ul className="space-y-2">{open.versions.map((v) => (
            <li key={v.id} className="rounded-xl border border-line p-3 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2"><strong>Version {v.version_number}{v.is_active ? " (live)" : ""}</strong>
                <span className="text-xs text-ink-muted">{formatDate(v.created_at)}{v.filename ? ` · ${v.filename}` : ""}</span></div>
              <p className="mt-1 whitespace-pre-wrap text-xs text-ink-muted">{(v.text ?? v.preview ?? "").slice(0, 600)}</p>
              {!open.system_managed && !v.is_active ? <button type="button" className="btn btn-primary mt-2 min-h-[34px] px-3 py-1 text-xs" disabled={busy}
                onClick={() => { if (window.confirm("Approve this version? Translators will be able to receive answers based on it.")) void run(() => api.admin.knowledge.approve(open.id, v.id), "Version approved and indexed."); }}>Approve this version</button> : null}
            </li>))}</ul>
          {!open.system_managed ? (
            <div className="space-y-2">
              <label className="label" htmlFor="k-newv">Add a new version (it stays a draft until approved)</label>
              <textarea id="k-newv" className="input min-h-[100px]" value={newText} onChange={(e) => setNewText(e.target.value)} />
              <div className="flex gap-2">
                <button type="button" className="btn btn-secondary" disabled={busy || !newText.trim()} onClick={() => void run(() => api.admin.knowledge.addVersion(open.id, newText), "New version saved as a draft.").then(() => setNewText(""))}>Save new version</button>
                {open.status === "approved" ? <button type="button" className="btn btn-danger" disabled={busy} onClick={() => { if (window.confirm("Deactivate this document? HAN will stop using it.")) void run(() => api.admin.knowledge.deactivate(open.id), "Document deactivated."); }}>Deactivate</button> : null}
              </div>
            </div>) : null}
        </section>) : null}
    </div>
  );
}
