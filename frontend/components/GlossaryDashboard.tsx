"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import {
  api, ApiError, type GlossaryEntry, type GlossaryKind, type GlossaryLanguage, type GlossaryLead, type GlossaryOverview,
} from "@/lib/api";
import { formatDate } from "@/lib/labels";
import { Alert, EmptyState, Spinner } from "./ui";

const PAGE = 25;
const KINDS: GlossaryKind[] = ["word", "expression", "sentence"];
const KIND_STYLE: Record<GlossaryKind, string> = { word: "bg-info/15 text-info-text", expression: "bg-ok/15 text-ok-text", sentence: "bg-warn/15 text-warn-text" };
const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
type Notice = { kind: "error" | "success"; text: string } | null;

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="card">
      <p className="text-[11px] font-extrabold uppercase tracking-[0.12em] text-ink-muted">{label}</p>
      <p className="mt-1 text-3xl font-bold">{value}</p>
      {hint ? <p className="mt-1 text-xs text-ink-muted">{hint}</p> : null}
    </div>
  );
}

export function GlossaryDashboard() {
  const [overview, setOverview] = useState<GlossaryOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<string | null>(null);
  const [langQ, setLangQ] = useState("");
  const [onlyMine, setOnlyMine] = useState(false);

  const reload = useCallback(() => api.glossary.overview().then(setOverview).catch((e) => setError(errText(e))), []);
  useEffect(() => { void reload(); }, [reload]);

  const shown = useMemo(() => {
    const t = langQ.trim().toLowerCase();
    return (overview?.languages ?? []).filter((l) => (!onlyMine || l.can_manage) && (!t || `${l.name} ${l.native_name ?? ""} ${l.code}`.toLowerCase().includes(t)));
  }, [overview, langQ, onlyMine]);
  const active = overview?.languages.find((l) => l.code === lang) ?? null;

  if (error) return <Alert>{error}</Alert>;
  if (!overview) return <Spinner label="Loading glossary" />;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Glossary entries" value={overview.total_entries} hint="Across every language" />
        <Stat label="Languages covered" value={`${overview.languages_with_entries} / ${overview.languages.length}`} hint="Languages with at least one entry" />
        <Stat label="Languages you manage" value={overview.is_admin ? "All" : overview.managed_languages} hint={overview.can_manage_any ? "You can add and edit entries" : "Read-only for you"} />
        <Stat label="Ask HAN" value="“How is Grace translated in Swahili?”" hint="HAN answers from these entries" />
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <section className="card space-y-3" aria-label="Languages">
          <h2 className="text-lg font-semibold">Languages</h2>
          <input className="input" type="search" placeholder="Search languages" aria-label="Search languages" value={langQ} onChange={(e) => setLangQ(e.target.value)} />
          {overview.can_manage_any && !overview.is_admin ? (
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />Show only my languages</label>
          ) : null}
          <ul className="max-h-[560px] space-y-1.5 overflow-y-auto pr-1">
            {shown.map((l) => (
              <li key={l.code}>
                <button type="button" onClick={() => setLang(l.code)} aria-pressed={l.code === lang}
                  className={`flex w-full items-center justify-between gap-2 rounded-xl border px-3 py-2 text-left text-sm transition ${l.code === lang ? "border-brand bg-brand/10" : "border-line hover:border-brand/50"}`}>
                  <span>
                    <span className="font-semibold">{l.name}</span>
                    {l.native_name && l.native_name !== l.name ? <span className="ml-1 text-xs text-ink-muted">{l.native_name}</span> : null}
                    {l.can_manage ? <span className="ml-2 rounded-full bg-ok/15 px-2 py-0.5 text-[10px] font-bold text-ok-text">{overview.is_admin ? "admin" : "yours"}</span> : null}
                  </span>
                  <span className="rounded-full bg-overlay/5 px-2 py-0.5 text-xs font-bold">{l.entries}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 ? <li className="text-sm text-ink-muted">No languages match.</li> : null}
          </ul>
        </section>

        <div className="space-y-6">
          {active ? <LanguagePanel key={active.code} language={active} onChanged={() => void reload()} />
            : <EmptyState title="Choose a language">Pick a language on the left to browse its glossary{overview.can_manage_any ? ", add entries or import a CSV" : ""}.</EmptyState>}
        </div>
      </div>

      {overview.is_admin ? <LeadsPanel languages={overview.languages} /> : null}

      <section className="card space-y-3" aria-label="Recent changes">
        <h2 className="text-lg font-semibold">Recently updated</h2>
        {overview.recent.length === 0 ? <p className="text-sm text-ink-muted">No entries yet. Team leaders can add the first ones from a language panel.</p> : (
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Language</th><th className="pr-4">English</th><th className="pr-4">Translation</th><th className="pr-4">By</th><th>When</th></tr></thead>
            <tbody>{overview.recent.map((e) => (
              <tr key={e.id} className="border-t border-line">
                <td className="py-2 pr-4 font-semibold">{overview.languages.find((l) => l.code === e.language)?.name ?? e.language}</td>
                <td className="pr-4">{e.source_text}</td><td className="pr-4">{e.target_text}</td><td className="pr-4">{e.updated_by ?? "—"}</td><td>{formatDate(e.updated_at)}</td>
              </tr>))}</tbody></table></div>)}
      </section>
    </div>
  );
}

function LanguagePanel({ language, onChanged }: { language: GlossaryLanguage; onChanged: () => void }) {
  const code = language.code;
  const [items, setItems] = useState<GlossaryEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState(0);
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ source: "", target: "", kind: "", notes: "" });
  const [editing, setEditing] = useState<{ id: string; source: string; target: string; notes: string } | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const load = useCallback(() => {
    api.glossary.entries(code, { q, kind, limit: PAGE, offset: page * PAGE }).then((r) => { setItems(r.items); setTotal(r.total); }).catch((e) => setNotice({ kind: "error", text: errText(e) }));
  }, [code, q, kind, page]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(true);
    try { await fn(); setNotice({ kind: "success", text: ok }); load(); onChanged(); return true; } catch (e) { setNotice({ kind: "error", text: errText(e) }); return false; } finally { setBusy(false); }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    const ok = await run(() => api.glossary.create(code, { source_text: form.source, target_text: form.target, kind: (form.kind || undefined) as GlossaryKind | undefined, notes: form.notes || undefined }), "Entry added. HAN can use it straight away.");
    if (ok) setForm({ source: "", target: "", kind: "", notes: "" });
  }

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.set("file", file);
    setBusy(true);
    try {
      const r = await api.glossary.import(code, fd);
      setNotice({ kind: r.errors.length ? "error" : "success", text: `Imported: ${r.added} added, ${r.updated} updated, ${r.skipped} skipped.${r.errors.length ? " " + r.errors.join(" ") : ""}` });
      setFile(null); load(); onChanged();
    } catch (err) { setNotice({ kind: "error", text: errText(err) }); } finally { setBusy(false); }
  }

  const pages = Math.max(1, Math.ceil(total / PAGE));
  return (
    <>
      <section className="card space-y-3" aria-label={`${language.name} glossary`}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold">{language.name} glossary</h2>
            <p className="text-xs text-ink-muted">
              {language.entries} {language.entries === 1 ? "entry" : "entries"} · Team leader{language.leaders.length === 1 ? "" : "s"}: {language.leaders.length ? language.leaders.join(", ") : "not assigned yet"}
            </p>
          </div>
          <a className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" href={api.glossary.exportUrl(code)} download>Export CSV</a>
        </div>
        {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
        {!language.can_manage ? <Alert kind="info">You can read and export this glossary. Only its team leader can change it.</Alert> : null}
      </section>

      {language.can_manage ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <section className="card space-y-3" aria-label="Add an entry">
            <h3 className="text-base font-semibold">Add an entry</h3>
            <form onSubmit={add} className="space-y-3">
              <div><label className="label" htmlFor="g-src">English word, expression or sentence</label>
                <textarea id="g-src" className="input min-h-[64px]" required maxLength={2000} value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} /></div>
              <div><label className="label" htmlFor="g-tgt">Approved {language.name} translation</label>
                <textarea id="g-tgt" className="input min-h-[64px]" required maxLength={4000} value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} /></div>
              <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
                <div><label className="label" htmlFor="g-kind">Type</label>
                  <select id="g-kind" className="input" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
                    <option value="">Detect automatically</option>{KINDS.map((k) => <option key={k} value={k}>{k}</option>)}</select></div>
                <div><label className="label" htmlFor="g-notes">Usage note (optional)</label>
                  <input id="g-notes" className="input" maxLength={2000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
              </div>
              <button className="btn btn-primary" type="submit" disabled={busy || !form.source.trim() || !form.target.trim()}>Add to glossary</button>
            </form>
          </section>

          <section className="card space-y-3" aria-label="Import entries">
            <h3 className="text-base font-semibold">Bulk import</h3>
            <p className="text-xs text-ink-muted">Upload a UTF-8 CSV with the columns <code>english, translation, type, notes</code> (the last two are optional). An English text that already exists is updated, not duplicated.</p>
            <form onSubmit={upload} className="space-y-3">
              <input type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              <div><button className="btn btn-secondary" type="submit" disabled={busy || !file}>Import CSV</button></div>
            </form>
          </section>
        </div>
      ) : null}

      <section className="card space-y-3" aria-label="Entries">
        <div className="flex flex-wrap items-center gap-2">
          <input className="input max-w-sm flex-1" type="search" placeholder={`Search English or ${language.name}`} aria-label="Search entries" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
          <select className="input w-auto" aria-label="Filter by type" value={kind} onChange={(e) => { setKind(e.target.value); setPage(0); }}>
            <option value="">All types</option>{KINDS.map((k) => <option key={k} value={k}>{k}s</option>)}</select>
          <span className="text-xs text-ink-muted">{total} result{total === 1 ? "" : "s"}</span>
        </div>
        {!items ? <Spinner /> : items.length === 0 ? (
          <EmptyState title={q || kind ? "No matching entries" : `The ${language.name} glossary is empty`}>
            {q || kind ? "Try a different search." : language.can_manage ? "Add the frequently translated words and expressions above, or import a CSV." : "Its team leader has not added entries yet. HAN will say so rather than guess."}
          </EmptyState>
        ) : (
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">English</th><th className="pr-4">{language.name}</th><th className="pr-4">Type</th><th className="pr-4">Updated</th>{language.can_manage ? <th className="text-right">Actions</th> : null}</tr></thead>
            <tbody>{items.map((e) => editing?.id === e.id ? (
              <tr key={e.id} className="border-t border-line align-top">
                <td className="py-2 pr-4"><textarea aria-label="English" className="input min-h-[60px]" value={editing.source} onChange={(x) => setEditing({ ...editing, source: x.target.value })} /></td>
                <td className="pr-4"><textarea aria-label="Translation" className="input min-h-[60px]" value={editing.target} onChange={(x) => setEditing({ ...editing, target: x.target.value })} />
                  <input aria-label="Usage note" className="input mt-2" placeholder="Usage note" value={editing.notes} onChange={(x) => setEditing({ ...editing, notes: x.target.value })} /></td>
                <td colSpan={2} />
                <td className="space-x-2 text-right"><button type="button" className="btn btn-primary min-h-[34px] px-3 py-1 text-xs" disabled={busy || !editing.source.trim() || !editing.target.trim()}
                  onClick={() => void run(() => api.glossary.update(code, e.id, { source_text: editing.source, target_text: editing.target, notes: editing.notes }), "Entry updated.").then((ok) => { if (ok) setEditing(null); })}>Save</button>
                  <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" onClick={() => setEditing(null)}>Cancel</button></td>
              </tr>
            ) : (
              <tr key={e.id} className="border-t border-line align-top">
                <td className="py-2 pr-4 font-semibold">{e.source_text}</td>
                <td className="pr-4">{e.target_text}{e.notes ? <p className="mt-0.5 text-xs text-ink-muted">{e.notes}</p> : null}</td>
                <td className="pr-4"><span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${KIND_STYLE[e.kind]}`}>{e.kind}</span></td>
                <td className="pr-4 text-xs text-ink-muted">{formatDate(e.updated_at)}{e.updated_by ? <><br />{e.updated_by}</> : null}</td>
                {language.can_manage ? (
                  <td className="space-x-2 whitespace-nowrap text-right">
                    <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" onClick={() => setEditing({ id: e.id, source: e.source_text, target: e.target_text, notes: e.notes ?? "" })}>Edit</button>
                    <button type="button" className="btn btn-danger min-h-[34px] px-3 py-1 text-xs" disabled={busy}
                      onClick={() => { if (window.confirm(`Delete “${e.source_text}” from the ${language.name} glossary? HAN will stop using it.`)) void run(() => api.glossary.remove(code, e.id), "Entry deleted."); }}>Delete</button>
                  </td>) : null}
              </tr>))}</tbody></table></div>)}
        {total > PAGE ? (
          <div className="flex items-center justify-between text-sm">
            <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span className="text-xs text-ink-muted">Page {page + 1} of {pages}</span>
            <button type="button" className="btn btn-secondary min-h-[34px] px-3 py-1 text-xs" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>Next</button>
          </div>) : null}
      </section>
    </>
  );
}

function LeadsPanel({ languages }: { languages: GlossaryLanguage[] }) {
  const [leads, setLeads] = useState<GlossaryLead[] | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [draft, setDraft] = useState<Record<string, string[]>>({});

  const load = useCallback(() => {
    api.glossary.leads().then((r) => { setLeads(r); setDraft(Object.fromEntries(r.map((l) => [l.user_id, l.languages]))); }).catch((e) => setNotice({ kind: "error", text: errText(e) }));
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(l: GlossaryLead) {
    try { await api.glossary.setLeads(l.user_id, draft[l.user_id] ?? []); setNotice({ kind: "success", text: `Languages saved for ${l.display_name}.` }); load(); } catch (e) { setNotice({ kind: "error", text: errText(e) }); }
  }

  return (
    <section className="card space-y-3" aria-label="Team leaders">
      <h2 className="text-lg font-semibold">Team leaders and their languages</h2>
      <p className="text-xs text-ink-muted">Create users with the Team leader role on the Users page, then choose which language glossaries each one maintains.</p>
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      {!leads ? <Spinner /> : leads.length === 0 ? <p className="text-sm text-ink-muted">No team leaders yet.</p> : (
        <ul className="space-y-3">{leads.map((l) => (
          <li key={l.user_id} className="rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div><p className="text-sm font-semibold">{l.display_name}</p><p className="text-xs text-ink-muted">{l.email}</p></div>
              <button type="button" className="btn btn-primary min-h-[34px] px-3 py-1 text-xs" onClick={() => void save(l)}>Save languages</button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {languages.map((g) => {
                const on = (draft[l.user_id] ?? []).includes(g.code);
                return (
                  <label key={g.code} className={`cursor-pointer rounded-full border px-2.5 py-1 text-xs ${on ? "border-brand bg-brand/10 font-bold" : "border-line"}`}>
                    <input type="checkbox" className="sr-only" checked={on} onChange={(e) => setDraft({ ...draft, [l.user_id]: e.target.checked ? [...(draft[l.user_id] ?? []), g.code] : (draft[l.user_id] ?? []).filter((c) => c !== g.code) })} />
                    {g.name}
                  </label>);
              })}
            </div>
          </li>))}</ul>)}
    </section>
  );
}
