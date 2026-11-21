"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type Language, type RhapsodyAssignmentRow, type RhapsodyEdition } from "@/lib/api";
import { canSeeAdmin, useAuth } from "@/lib/auth";
import { Alert, EmptyState, Spinner } from "@/components/ui";
import { RhapsodyChat } from "./RhapsodyChat";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const STATUS: Record<string, string> = { draft: "bg-warn/15 text-warn-text", active: "bg-ok/15 text-ok-text" };

export function RhapsodyHome() {
  const { user } = useAuth();
  const admin = canSeeAdmin(user);
  const [editions, setEditions] = useState<RhapsodyEdition[] | null>(null);
  const [mine, setMine] = useState<RhapsodyAssignmentRow[]>([]);
  const [languages, setLanguages] = useState<Language[]>([]);
  const mine_lang = user?.role === "translator" ? user.expertise_language ?? "" : "";
  const [lang, setLang] = useState(mine_lang);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const now = new Date();
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [year, setYear] = useState(now.getFullYear());

  const load = useCallback(async () => {
    try {
      const [e, a, l] = await Promise.all([api.rhapsody.editions(), api.rhapsody.assignments(), api.languages()]);
      setEditions(e); setMine(a); setLanguages(l.filter((x) => x.code !== "en"));
    } catch (e) { setError(errText(e)); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (mine_lang) setLang(mine_lang); }, [mine_lang]);

  async function create(ev: FormEvent) {
    ev.preventDefault(); setBusy("create"); setError(null);
    try { const e = await api.rhapsody.createEdition(month, year); window.location.assign(`/rhapsody/editions/${e.id}`); } catch (x) { setError(errText(x)); setBusy(null); }
  }
  async function remove(e: RhapsodyEdition) {
    if (!window.confirm(`Delete “${e.title}”? Its source files, master versions and any translation drafts will be permanently removed.`)) return;
    setBusy(e.id); setError(null);
    try { await api.rhapsody.deleteEdition(e.id); await load(); } catch (x) { setError(errText(x)); } finally { setBusy(null); }
  }
  async function start(id: string) {
    if (!lang) { setError("Choose your target language first."); return; }
    setBusy(id); setError(null);
    try { const a = await api.rhapsody.start(id, lang); window.location.assign(`/rhapsody/translate/${a.id}`); } catch (x) { setError(errText(x)); setBusy(null); }
  }

  if (!editions) return error ? <Alert>{error}</Alert> : <Spinner label="Loading Rhapsody editions" />;
  const active = editions.filter((e) => e.status === "active").length;
  const submitted = mine.filter((a) => ["submitted", "approved"].includes(a.status)).length;
  return (
    <div className="space-y-6">
      {error ? <Alert>{error}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-3">
        {[["Editions", editions.length, "Monthly issues in the system"], ["Open for translation", active, "Activated English masters"], ["My translations", mine.length, `${submitted} submitted or approved`]].map(([l, v, h]) => (
          <div className="card" key={String(l)}><p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-ink-muted">{l}</p><p className="mt-1 text-3xl font-bold">{v}</p><p className="mt-1 text-xs text-ink-muted">{h}</p></div>))}
      </div>
      {admin ? <div className="flex justify-end"><Link className="btn btn-secondary text-xs" href="/rhapsody/publishing">Rhapsody publishing</Link></div> : null}
      <RhapsodyChat admin={admin} openEdition={editions.find((e) => e.status === "active")?.title} onChanged={() => void load()} />

      {admin ? (
        <form className="card flex flex-wrap items-end gap-3" onSubmit={create}>
          <div><label className="text-xs font-semibold" htmlFor="rm">Month</label>
            <select id="rm" className="input" value={month} onChange={(e) => setMonth(+e.target.value)}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</select></div>
          <div><label className="text-xs font-semibold" htmlFor="ry">Year</label><input id="ry" className="input" type="number" value={year} onChange={(e) => setYear(+e.target.value)} /></div>
          <button className="btn btn-primary" disabled={busy === "create"}>New edition</button>
        </form>
      ) : (
        <div className="card flex flex-wrap items-end gap-3">
          <div className="min-w-[220px]"><label className="text-xs font-semibold" htmlFor="tl">My target language</label>
            <select id="tl" className="input" value={lang} disabled={!!mine_lang} onChange={(e) => setLang(e.target.value)}><option value="">Select…</option>{languages.map((l) => <option key={l.code} value={l.code}>{l.display_name}</option>)}</select></div>
          <p className="basis-full text-sm text-ink-muted">{mine_lang ? "Rhapsody is always translated from English into your language of expertise." : "Choose your language of expertise first."} You can also just ask HAN in the chat above to start it.</p>
        </div>)}

      <section>
        <h2 className="mb-3 text-lg font-bold">Editions</h2>
        {editions.length === 0 ? <EmptyState title="No editions yet">{admin ? "Create the first monthly edition above." : "An administrator will activate the next edition soon."}</EmptyState> : (
          <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{editions.map((e) => (
            <li key={e.id} className="card">
              <div className="flex items-start justify-between gap-2"><h3 className="text-base font-bold">{e.title}</h3>
                <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS[e.status] ?? "bg-info/15 text-info-text"}`}>{e.status}</span></div>
              <p className="mt-2 text-xs text-ink-muted">{e.sources.length} source file(s) · {e.master_versions.length} master version(s)</p>
              <div className="mt-4 flex gap-2">
                {admin ? <Link className="btn btn-secondary text-xs" href={`/rhapsody/editions/${e.id}`}>Manage master</Link> : null}
                {admin ? <button className="btn btn-secondary text-xs text-danger" disabled={busy === e.id} onClick={() => void remove(e)}>Delete</button> : null}
                {e.status === "active" ? <button className="btn btn-primary text-xs" disabled={busy === e.id} onClick={() => void start(e.id)}>Start / resume translation</button> : null}
              </div>
            </li>))}</ul>)}
      </section>

      <section>
        <h2 className="mb-3 text-lg font-bold">{admin ? "All translations" : "My translations"}</h2>
        {mine.length === 0 ? <EmptyState title="Nothing started">Choose a language and start an active edition.</EmptyState> : (
          <div className="card overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Edition</th><th className="pr-4">Language</th><th className="pr-4">Status</th><th className="pr-4">HAN draft</th><th /></tr></thead>
            <tbody>{mine.map((a) => (
              <tr key={a.id} className="border-t border-line">
                <td className="py-2 pr-4 font-semibold">{a.edition_title}</td><td className="pr-4 uppercase">{a.target_language}</td><td className="pr-4">{a.status.replace("_", " ")}</td>
                <td className="pr-4">{a.draft_status === "running" ? `${a.draft_done}/${a.draft_total}` : a.draft_status}</td>
                <td className="text-right"><Link className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" href={`/rhapsody/translate/${a.id}`}>Open</Link></td>
              </tr>))}</tbody></table></div>)}
      </section>
    </div>
  );
}
