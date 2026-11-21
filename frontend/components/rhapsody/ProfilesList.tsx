"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type PublishingFont, type PublishingProfile } from "@/lib/api";
import { Alert, Spinner } from "@/components/ui";
import { AdminOnly, errText, type Pill } from "./publishingShared";

const STATUS: Record<string, { label: string; pill: Pill }> = {
  active: { label: "Active", pill: "green" }, validated: { label: "Validated", pill: "blue" }, draft: { label: "Draft", pill: "orange" }, not_configured: { label: "Not configured", pill: "grey" },
};

export function ProfilesList() {
  const [fonts, setFonts] = useState<PublishingFont[] | null>(null);
  const [profiles, setProfiles] = useState<PublishingProfile[]>([]);
  const [q, setQ] = useState("");
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { const [f, p] = await Promise.all([api.publishing.fonts(), api.publishing.profiles()]); setFonts(f); setProfiles(p); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const shown = useMemo(() => profiles.filter((p) => `${p.language_name} ${p.language_code}`.toLowerCase().includes(q.trim().toLowerCase()))
    .sort((a, b) => Number(b.status === "active") - Number(a.status === "active") || Number(b.version > 0) - Number(a.version > 0) || a.language_name.localeCompare(b.language_name)), [profiles, q]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setNotice(null);
    try { await fn(); await load(); setNotice({ kind: "success", text: ok }); } catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  function setFont(p: PublishingProfile, role: "body" | "heading", id: string) {
    const next = { ...Object.fromEntries(Object.entries(p.fonts).map(([r, f]) => [r, f.id])), [role]: id };
    if (!id) delete (next as Record<string, string>)[role];
    return run(() => api.publishing.saveProfile(p.language_code, { direction: p.direction, locale: p.locale, fonts: next, typography: p.typography, localization: p.localization, layout: p.layout }), `${p.language_name} saved. Validate it to activate.`);
  }
  function validateAndActivate(p: PublishingProfile) {
    return run(async () => {
      const r = await api.publishing.validate(p.language_code);
      const errors = r.checks.filter((c) => c.severity === "error");
      if (errors.length) throw new ApiError(422, "validation", errors.map((c) => c.message).join(" "));
      await api.publishing.activate(p.language_code);
    }, `${p.language_name} is ready for typesetting.`);
  }

  return (
    <AdminOnly>
      <div className="space-y-5">
        {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
        <div className="card flex flex-wrap items-center gap-3">
          <input className="input max-w-xs" type="search" placeholder="Search languages" aria-label="Search languages" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="text-xs text-ink-muted">{profiles.filter((p) => p.status === "active").length} active · {profiles.filter((p) => p.version > 0).length} configured · {profiles.length} languages</span>
          <Link className="btn btn-secondary ml-auto" href="/rhapsody/publishing/fonts/new">＋ Add a font</Link>
        </div>
        {!fonts ? <Spinner /> : (
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-left text-sm">
              <thead><tr className="text-xs text-ink-muted"><th className="p-3">Language</th><th>Body font</th><th>Heading font</th><th>Status</th><th>Rev.</th><th /></tr></thead>
              <tbody>{shown.map((p) => {
                const st = STATUS[p.status] ?? { label: p.status.replace("_", " "), pill: "grey" as Pill };
                return (
                  <tr key={p.language_code} className="border-t align-middle">
                    <td className="p-3"><p className="font-semibold">{p.language_name}</p><p className="text-xs text-ink-muted">{p.language_code} · {p.direction.toUpperCase()}</p></td>
                    {(["body", "heading"] as const).map((role) => (
                      <td key={role} className="pr-3"><select className="input" aria-label={`${p.language_name} ${role} font`} value={p.fonts[role]?.id ?? ""} disabled={busy} onChange={(e) => void setFont(p, role, e.target.value)}>
                        <option value="">Default</option>{fonts.map((f) => <option key={f.id} value={f.id}>{f.family} {f.style}</option>)}</select></td>))}
                    <td><span className={`pill pill-${st.pill}`}>{st.label}</span></td><td>{p.version || "—"}</td>
                    <td className="space-x-2 whitespace-nowrap p-3 text-right">
                      <Link className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" href={`/rhapsody/publishing/profiles/${p.language_code}`}>Edit profile</Link>
                      <button className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" disabled={busy || !p.id || p.status === "active"} onClick={() => void validateAndActivate(p)}>Validate &amp; activate</button></td>
                  </tr>);
              })}</tbody>
            </table>
          </div>)}
      </div>
    </AdminOnly>
  );
}
