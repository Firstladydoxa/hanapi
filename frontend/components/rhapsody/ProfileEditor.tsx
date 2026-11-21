"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type PublishingFont, type PublishingProfile } from "@/lib/api";
import { canSeeAdmin, useAuth } from "@/lib/auth";
import { formatDate } from "@/lib/labels";
import { Alert, Spinner } from "@/components/ui";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const TABS = ["General", "Typography", "Localization", "Bible", "Layout", "Font test", "History"] as const;
const ROLES: [string, string][] = [["body", "Body text"], ["heading", "Headings"], ["subheading", "Sub-headings"], ["scripture", "Bible text (scripture panel)"], ["caption", "Captions"], ["notes", "Notes"]];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const LABELS: [string, string][] = [["prayer", "Prayer"], ["confession", "Confession"], ["further-study", "Further study"], ["plan-1", "1-year Bible reading plan"], ["plan-2", "2-year Bible reading plan"], ["notes", "Notes"], ["image", "Article image"]];

export function ProfileEditor({ code }: { code: string }) {
  const { user } = useAuth();
  const [profile, setProfile] = useState<PublishingProfile | null>(null);
  const [fonts, setFonts] = useState<PublishingFont[]>([]);
  const [versions, setVersions] = useState<{ version: number; created_at: string; created_by: string }[]>([]);
  const [tab, setTab] = useState<(typeof TABS)[number]>("General");
  const [direction, setDirection] = useState<"ltr" | "rtl">("ltr");
  const [locale, setLocale] = useState("");
  const [fontIds, setFontIds] = useState<Record<string, string>>({});
  const [typo, setTypo] = useState<Record<string, string>>({});
  const [layout, setLayout] = useState<Record<string, string>>({});
  const [weekdays, setWeekdays] = useState<string[]>(Array(7).fill(""));
  const [months, setMonths] = useState<string[]>(Array(12).fill(""));
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [bible, setBible] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = useCallback((p: PublishingProfile) => {
    setProfile(p); setDirection(p.direction); setLocale(p.locale || p.language_code);
    setFontIds(Object.fromEntries(Object.entries(p.fonts).map(([r, f]) => [r, f.id])));
    setTypo(Object.fromEntries(Object.entries(p.typography ?? {}).map(([k, v]) => [k, String(v)])));
    setLayout(Object.fromEntries(Object.entries(p.layout ?? {}).map(([k, v]) => [k, String(v)])));
    const l = (p.localization ?? {}) as { weekdays?: string[]; months?: string[]; labels?: Record<string, string>; bible_version?: Record<string, string> };
    setWeekdays(WEEKDAYS.map((_, i) => l.weekdays?.[i] ?? "")); setMonths(MONTHS.map((_, i) => l.months?.[i] ?? ""));
    setLabels(l.labels ?? {}); setBible(l.bible_version ?? {});
  }, []);
  const load = useCallback(async () => {
    try {
      const [ps, fs] = await Promise.all([api.publishing.profiles(), api.publishing.fonts()]);
      const p = ps.find((x) => x.language_code === code);
      if (!p) throw new ApiError(404, "not_found", "That language is not available.");
      apply(p); setFonts(fs);
      if (p.id) setVersions(await api.publishing.profileVersions(code));
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, [code, apply]);
  useEffect(() => { if (canSeeAdmin(user)) void load(); }, [user, load]);

  if (!canSeeAdmin(user)) return <Alert kind="error">Only administrators can manage publishing profiles.</Alert>;
  if (!profile) return notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : <Spinner />;

  const num = (m: Record<string, string>) => Object.fromEntries(Object.entries(m).filter(([, v]) => v !== "" && !Number.isNaN(Number(v))).map(([k, v]) => [k, Number(v)]));
  async function save() {
    setBusy(true); setNotice(null);
    try {
      const filled = (a: string[]) => (a.some((x) => x.trim()) ? a.map((x) => x.trim()) : []);
      const saved = await api.publishing.saveProfile(code, {
        direction, locale: locale.trim() || code, fonts: Object.fromEntries(Object.entries(fontIds).filter(([, v]) => v)),
        typography: num(typo), layout: num(layout),
        localization: { weekdays: filled(weekdays), months: filled(months), labels: Object.fromEntries(Object.entries(labels).filter(([, v]) => v.trim())), bible_version: Object.fromEntries(Object.entries(bible).filter(([, v]) => v.trim())) },
      });
      apply(saved); setVersions(await api.publishing.profileVersions(code));
      setNotice({ kind: "success", text: `Saved as revision ${saved.version}. Validate and activate it on the languages page before it is used for final output.` });
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  async function activate() {
    setBusy(true); setNotice(null);
    try {
      const r = await api.publishing.validate(code);
      const errors = r.checks.filter((c) => c.severity === "error");
      if (errors.length) throw new ApiError(422, "validation", errors.map((c) => c.message).join(" "));
      await api.publishing.activate(code); await load();
      setNotice({ kind: "success", text: "Profile validated and activated." });
    } catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  async function restore(v: number) {
    setBusy(true); setNotice(null);
    try { apply(await api.publishing.restoreVersion(code, v)); setVersions(await api.publishing.profileVersions(code)); setNotice({ kind: "success", text: `Revision ${v} restored as a new draft.` }); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }
  const input = (value: string, set: (v: string) => void, label: string, ph = "") => (
    <label className="block text-xs font-semibold">{label}<input className="input mt-1 font-normal" value={value} placeholder={ph} onChange={(e) => set(e.target.value)} dir={direction} /></label>);

  return (
    <div className="space-y-4">
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <div className="card flex flex-wrap items-center justify-between gap-3">
        <div><h2 className="text-xl font-bold">{profile.language_name}</h2><p className="text-xs text-ink-muted">Status: {profile.status.replace("_", " ")} · revision {profile.version || "—"}</p></div>
        <div className="flex gap-2">
          <button className="btn btn-primary" disabled={busy} onClick={() => void save()}>Save revision</button>
          <button className="btn btn-secondary" disabled={busy || !profile.id || profile.status === "active"} onClick={() => void activate()}>Validate &amp; activate</button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2" role="tablist">{TABS.map((t) => (
        <button key={t} role="tab" aria-selected={tab === t} className={`btn min-h-[36px] px-3 py-1 text-sm ${tab === t ? "btn-primary" : "btn-secondary"}`} onClick={() => setTab(t)}>{t}</button>))}</div>

      <div className="card space-y-3">
        {tab === "General" ? (<div className="grid gap-3 md:grid-cols-2">
          {input(locale, setLocale, "Locale (BCP-47)", "af-ZA")}
          <label className="block text-xs font-semibold">Writing direction<select className="input mt-1 font-normal" value={direction} onChange={(e) => setDirection(e.target.value as "ltr" | "rtl")}><option value="ltr">Left to right</option><option value="rtl">Right to left</option></select></label>
        </div>) : null}

        {tab === "Typography" ? (<>
          <p className="text-xs text-ink-muted">Choose a font for each text role (upload fonts on the languages page first). Roles left on Default use HAN&apos;s built-in fonts. Font sizes are in points; HAN never shrinks text silently to fit.</p>
          <div className="grid gap-3 md:grid-cols-2">{ROLES.map(([role, label]) => (
            <label key={role} className="block text-xs font-semibold">{label}<select className="input mt-1 font-normal" value={fontIds[role] ?? ""} onChange={(e) => setFontIds({ ...fontIds, [role]: e.target.value })}>
              <option value="">Default</option>{fonts.map((f) => <option key={f.id} value={f.id}>{f.family} {f.style}</option>)}</select></label>))}</div>
          <div className="grid gap-3 md:grid-cols-3">
            {input(typo.body_size_pt ?? "", (v) => setTypo({ ...typo, body_size_pt: v }), "Body size (pt)", "9.6")}
            {input(typo.heading_size_pt ?? "", (v) => setTypo({ ...typo, heading_size_pt: v }), "Article title size (pt)", "13")}
            {input(typo.scripture_size_pt ?? "", (v) => setTypo({ ...typo, scripture_size_pt: v }), "Scripture size (pt)", "9")}
          </div></>) : null}

        {tab === "Localization" ? (<>
          <p className="text-xs text-ink-muted">Used on every page of this language&apos;s edition (weekday tab, cover month, section headings). Leave blank to use the translated Rhapsody labels.</p>
          <h3 className="font-bold">Weekdays</h3>
          <div className="grid gap-3 md:grid-cols-4">{WEEKDAYS.map((d, i) => input(weekdays[i] ?? "", (v) => setWeekdays(weekdays.map((w, j) => (j === i ? v : w))), d))}</div>
          <h3 className="font-bold">Months</h3>
          <div className="grid gap-3 md:grid-cols-4">{MONTHS.map((m, i) => input(months[i] ?? "", (v) => setMonths(months.map((w, j) => (j === i ? v : w))), m))}</div>
          <h3 className="font-bold">Recurring labels</h3>
          <div className="grid gap-3 md:grid-cols-3">{LABELS.map(([k, l]) => input(labels[k] ?? "", (v) => setLabels({ ...labels, [k]: v }), l))}</div></>) : null}

        {tab === "Bible" ? (<>
          <p className="text-xs text-ink-muted">The Bible version this language&apos;s edition quotes. It is stored with the profile and recorded in each revision.</p>
          <div className="grid gap-3 md:grid-cols-3">
            {input(bible.name ?? "", (v) => setBible({ ...bible, name: v }), "Version name")}
            {input(bible.abbreviation ?? "", (v) => setBible({ ...bible, abbreviation: v }), "Abbreviation")}
            {input(bible.copyright ?? "", (v) => setBible({ ...bible, copyright: v }), "Copyright notice")}
          </div></>) : null}

        {tab === "Layout" ? (<div className="grid gap-3 md:grid-cols-3">
          {input(layout.page_width_mm ?? "", (v) => setLayout({ ...layout, page_width_mm: v }), "Page width (mm)", "140")}
          {input(layout.page_height_mm ?? "", (v) => setLayout({ ...layout, page_height_mm: v }), "Page height (mm)", "220")}
          {input(layout.margin_mm ?? "", (v) => setLayout({ ...layout, margin_mm: v }), "Margin (mm)", "12")}
        </div>) : null}

        {tab === "Font test" ? (<>
          <p className="text-xs text-ink-muted">Save first, then open a test sheet in this profile&apos;s fonts and localized labels to check accents and script shaping.</p>
          <a className="btn btn-secondary" href={api.publishing.specimenUrl(code)} target="_blank" rel="noreferrer">Open test sheet (PDF)</a></>) : null}

        {tab === "History" ? (versions.length === 0 ? <p className="text-sm text-ink-muted">No revisions yet.</p> : (
          <ul className="divide-y text-sm">{versions.map((v) => (
            <li key={v.version} className="flex items-center justify-between py-2"><span>Revision {v.version} <span className="text-ink-muted">· {v.created_by} · {formatDate(v.created_at)}</span></span>
              <button className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" disabled={busy} onClick={() => void restore(v.version)}>Restore as draft</button></li>))}</ul>)) : null}
      </div>
    </div>
  );
}
