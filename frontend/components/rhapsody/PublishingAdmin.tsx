"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type PublishingFont, type PublishingProduction, type PublishingProfile } from "@/lib/api";
import { canSeeAdmin, useAuth } from "@/lib/auth";
import { Alert, Spinner } from "@/components/ui";
import { PublicationPanel } from "./PublicationPanel";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");

export function PublishingAdmin() {
  const { user } = useAuth();
  const [fonts, setFonts] = useState<PublishingFont[] | null>(null);
  const [profiles, setProfiles] = useState<PublishingProfile[]>([]);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [production, setProduction] = useState<PublishingProduction[]>([]);

  const load = useCallback(async () => {
    try { const [f, p, pr] = await Promise.all([api.publishing.fonts(), api.publishing.profiles(), api.publishing.production()]); setFonts(f); setProfiles(p); setProduction(pr); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, []);
  useEffect(() => { if (canSeeAdmin(user)) void load(); }, [user, load]);

  if (!canSeeAdmin(user)) return <Alert kind="error">Only administrators can manage publishing fonts.</Alert>;
  if (!fonts) return notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : <Spinner />;

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setNotice(null);
    try { await fn(); await load(); setNotice({ kind: "success", text: ok }); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); }
    finally { setBusy(false); }
  }
  function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    void run(() => api.publishing.uploadFont(new FormData(form)), "Font added.").then(() => form.reset());
  }
  async function setFont(p: PublishingProfile, role: "body" | "heading", id: string) {
    const current = Object.fromEntries(Object.entries(p.fonts).map(([r, f]) => [r, f.id]));
    const next = { ...current, [role]: id };
    if (!id) delete next[role];
    await run(() => api.publishing.saveProfile(p.language_code, { direction: p.direction, locale: p.locale, fonts: next, typography: p.typography, localization: p.localization, layout: p.layout }), `${p.language_name} profile saved. Validate it to activate.`);
  }
  async function validateAndActivate(p: PublishingProfile) {
    await run(async () => {
      const r = await api.publishing.validate(p.language_code);
      const errors = r.checks.filter((c) => c.severity === "error");
      if (errors.length) throw new ApiError(422, "validation", errors.map((c) => c.message).join(" "));
      await api.publishing.activate(p.language_code);
    }, `${p.language_name} is ready for typesetting.`);
  }

  return (
    <div className="space-y-6">
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <form className="card grid gap-3 md:grid-cols-4" onSubmit={upload}>
        <div className="md:col-span-4"><h3 className="font-bold">Add a font</h3><p className="text-xs text-ink-muted">OTF or TTF. Only upload fonts TNI is licensed to embed in PDFs.</p></div>
        <div><label className="text-xs font-semibold" htmlFor="ff">Font file</label><input id="ff" name="file" className="input" type="file" accept=".otf,.ttf" required /></div>
        <div><label className="text-xs font-semibold" htmlFor="fam">Family</label><input id="fam" name="family" className="input" required placeholder="Myriad Pro" /></div>
        <div><label className="text-xs font-semibold" htmlFor="sty">Style</label><input id="sty" name="style" className="input" defaultValue="Regular" /></div>
        <div><label className="text-xs font-semibold" htmlFor="lic">Licence</label><input id="lic" name="license_name" className="input" required placeholder="Desktop licence" /></div>
        <div className="md:col-span-4"><button className="btn btn-primary" disabled={busy}>Upload font</button></div>
      </form>

      <div className="card">
        <h3 className="mb-2 font-bold">Font library</h3>
        {fonts.length === 0 ? <p className="text-sm text-ink-muted">No fonts yet. English uses built-in fonts until you add some.</p> : (
          <ul className="divide-y text-sm">{fonts.map((f) => (
            <li key={f.id} className="flex items-center justify-between py-2"><span>{f.family} <span className="text-ink-muted">{f.style} · {f.format.toUpperCase()} · {f.license_name}</span></span>
              <button className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" disabled={busy} onClick={() => void run(() => api.publishing.deleteFont(f.id), "Font removed.")}>Delete</button></li>
          ))}</ul>)}
      </div>

      <div className="card space-y-3">
        <h3 className="font-bold">Edition production</h3>
        <p className="text-xs text-ink-muted">Each active edition with the languages being translated, and whether the language&apos;s publishing profile is ready to typeset it.</p>
        {production.length === 0 ? <p className="text-sm text-ink-muted">No editions yet.</p> : production.map((e) => (
          <div key={e.edition_id}><p className="text-sm font-semibold">{e.title}{e.master_active ? "" : " (master not activated)"}</p>
            {e.languages.length ? (<ul className="divide-y text-sm">{e.languages.map((l) => (
              <li key={l.assignment_id} className="flex flex-wrap items-center justify-between gap-2 py-1.5"><span>{l.language.toUpperCase()} · {l.translator} · {l.status.replace("_", " ")}</span>
                <span className="flex items-center gap-3 text-xs"><span className={l.profile_status === "active" ? "text-green-700" : "text-amber-700"}>Profile: {l.profile_status.replace("_", " ")}</span>
                  <a className="underline" href={api.rhapsody.layoutUrl(l.assignment_id)} target="_blank" rel="noreferrer">Book layout PDF</a></span><div className="w-full"><PublicationPanel assignmentId={l.assignment_id} status={l.status} /></div></li>))}</ul>) : <p className="text-xs text-ink-muted">No translations started.</p>}
          </div>))}
      </div>

      <div className="card overflow-x-auto">
        <h3 className="mb-2 font-bold">Language typesetting profiles</h3>
        <table className="w-full text-left text-sm">
          <thead><tr className="text-xs text-ink-muted"><th className="py-1">Language</th><th>Body font</th><th>Heading font</th><th>Status</th><th>Rev.</th><th /></tr></thead>
          <tbody>{profiles.map((p) => (
            <tr key={p.language_code} className="border-t">
              <td className="py-2">{p.language_name}</td>
              {(["body", "heading"] as const).map((role) => (
                <td key={role}><select className="input" aria-label={`${p.language_name} ${role} font`} value={p.fonts[role]?.id ?? ""} disabled={busy} onChange={(e) => void setFont(p, role, e.target.value)}>
                  <option value="">Default</option>{fonts.map((f) => <option key={f.id} value={f.id}>{f.family} {f.style}</option>)}</select></td>
              ))}
              <td>{p.status.replace("_", " ")}</td><td>{p.version || "—"}</td>
              <td className="space-x-2 whitespace-nowrap"><Link className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" href={`/rhapsody/publishing/${p.language_code}`}>Edit profile</Link><button className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" disabled={busy || !p.id || p.status === "active"} onClick={() => void validateAndActivate(p)}>Validate &amp; activate</button></td>
            </tr>))}</tbody>
        </table>
      </div>
    </div>
  );
}
