"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type EvidenceDetail, type EvidenceItem } from "@/lib/api";
import { Alert, Spinner, TierBadge } from "./ui";

const fmt = (v: number | null) => (v === null || v === undefined ? "–" : String(v));

export function EvidencePanel() {
  const [items, setItems] = useState<EvidenceItem[] | null>(null);
  const [open, setOpen] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => { api.admin.evidence.list().then(setItems).catch((e) => setError(e instanceof ApiError ? e.message : "Unable to load evidence.")); }, []);
  useEffect(load, [load]);

  async function show(i: EvidenceItem) {
    setError(null); setNotice(null);
    try { setOpen(await api.admin.evidence.get(i.source_code, i.target_code)); } catch (e) { setError(e instanceof ApiError ? e.message : "Unable to load this language."); }
  }
  async function promote(d: EvidenceDetail) {
    setBusy(true); setError(null);
    try {
      const r = await api.admin.evidence.promote(d.source_code, d.target_code);
      setNotice(`${d.source_name} → ${d.target_name} is now ${r.tier}.`);
      setOpen(await api.admin.evidence.get(d.source_code, d.target_code)); load();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not promote."); }
    finally { setBusy(false); }
  }

  if (!items) return error ? <Alert>{error}</Alert> : <Spinner label="Loading evidence" />;
  return (
    <div className="space-y-5">
      <Alert kind="info">Reviewer scores per language pair. A pair is flagged &quot;ready&quot; when every threshold for the next tier is met. Only you decide: nothing changes until you press Promote.</Alert>
      {error ? <Alert>{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}

      {!items.length ? <Alert kind="info">No reviewer scores yet. Ask translators to use Review languages.</Alert> : (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-left text-sm">
            <thead><tr className="text-xs uppercase"><th className="p-3">Language pair</th><th className="p-3">Tier</th><th className="p-3">Drafts</th><th className="p-3">Reviewers</th><th className="p-3">Adequacy</th><th className="p-3">Fluency</th><th className="p-3">Status</th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={`${i.source_code}-${i.target_code}`} className="cursor-pointer border-t border-line hover:bg-overlay/5" onClick={() => void show(i)}>
                  <td className="p-3 font-semibold"><button type="button" className="text-left underline-offset-2 hover:underline" onClick={(e) => { e.stopPropagation(); void show(i); }}>{i.source_name} → {i.target_name}</button></td>
                  <td className="p-3"><TierBadge tier={i.tier} /></td>
                  <td className="p-3">{i.summary.segments}</td><td className="p-3">{i.summary.reviewers}</td>
                  <td className="p-3">{fmt(i.summary.mean_adequacy)}</td><td className="p-3">{fmt(i.summary.mean_fluency)}</td>
                  <td className="p-3">{i.readiness.ready_for ? <span className="rounded-full bg-ok/15 px-2 py-0.5 text-xs font-bold text-ok-text">Ready for {i.readiness.ready_for}</span> : <span className="text-xs text-ink-muted">Collecting evidence</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {open ? (
        <section className="card space-y-4" aria-label="Evidence detail">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">{open.source_name} → {open.target_name}</h2>
              <p className="text-xs text-ink-muted">Current tier: {open.tier} · technical check: {open.technical_status}</p>
            </div>
            {open.readiness.ready_for ? <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void promote(open)}>{busy ? "Promoting…" : `Promote to ${open.readiness.ready_for}`}</button> : null}
          </div>
          {open.readiness.next_tier ? (
            <>
              <p className="label">Requirements for {open.readiness.next_tier}</p>
              <ul className="grid gap-2 sm:grid-cols-2">
                {open.readiness.criteria.map((c) => (
                  <li key={c.key} className={`flex items-center justify-between gap-3 rounded-lg border p-2 text-sm ${c.met ? "border-ok/40 bg-ok/10" : "border-line"}`}>
                    <span>{c.met ? "✓" : "○"} {c.label}</span><span className="text-xs text-ink-muted">{fmt(c.value)} (need {c.required})</span>
                  </li>
                ))}
              </ul>
            </>
          ) : <p className="text-sm text-ink-muted">This pair is already at the highest tier.</p>}
          <div>
            <p className="label">Scored drafts ({open.reviews.length})</p>
            <div className="max-h-[60vh] space-y-2 overflow-y-auto">
              {open.reviews.map((r) => (
                <div key={r.id} className="rounded-lg border border-line bg-wash p-3 text-sm">
                  <div className="mb-1 flex flex-wrap gap-x-3 text-xs text-ink-muted"><span>{r.reviewer}</span><span>{r.content_type}</span><span>Adequacy {r.adequacy}</span><span>Fluency {r.fluency}</span><span>Errors: {r.severity}</span></div>
                  <p>{r.source_text}</p><p className="text-ink-soft">{r.draft_text}</p>
                  {r.comment ? <p className="mt-1 text-xs italic text-ink-muted">“{r.comment}”</p> : null}
                </div>
              ))}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
