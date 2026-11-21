"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type ProductionLanguage, type PublishingProduction } from "@/lib/api";
import { Alert, EmptyState, Spinner } from "@/components/ui";
import { PublicationPanel } from "./PublicationPanel";
import { AdminOnly, errText, STAGE_ORDER, StagePill, stageOf } from "./publishingShared";

const REFRESH_MS = 20_000;
const FILTERS: { key: string; label: string; pill: string }[] = [
  { key: "submitted", label: "Submitted", pill: "green" }, { key: "ready", label: "Ready for layout", pill: "green" },
  { key: "proofing", label: "Proofing", pill: "violet" }, { key: "progress", label: "In progress", pill: "orange" },
  { key: "changes", label: "Changes requested", pill: "red" }, { key: "published", label: "Published", pill: "blue" }, { key: "new", label: "Not started", pill: "grey" },
];

function Row({ l, busy, onApprove }: { l: ProductionLanguage; busy: boolean; onApprove: (id: string) => void }) {
  const stage = stageOf(l);
  const pct = l.total ? Math.round((l.translated / l.total) * 100) : 0;
  const profileOk = l.profile_status === "active";
  return (
    <div className="row-accent rounded-xl border p-4" style={{ ["--accent" as string]: stage.accent, borderColor: "var(--han-line)" }}>
      <div className="grid gap-3 md:grid-cols-[1.3fr_1.2fr_1fr_auto] md:items-center">
        <div>
          <p className="text-base font-bold">{l.language_name}</p>
          <p className="text-xs text-ink-muted">{l.translator}</p>
        </div>
        <div style={{ color: stage.accent }}>
          <div className="mb-1 flex items-center justify-between text-xs text-ink-muted"><span>{l.translated} / {l.total} paragraphs</span><span>{pct}%</span></div>
          <div className="bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={`${l.language_name} progress`}><i style={{ width: `${pct}%` }} /></div>
          {l.unreviewed ? <p className="mt-1 text-[11px] text-amber-600">{l.unreviewed} HAN draft(s) not yet confirmed</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2"><StagePill stage={stage} />
          <span className={`pill ${profileOk ? "pill-green" : "pill-orange"}`} title="Language typesetting profile">{profileOk ? `Profile r${l.profile_version}` : `Profile ${l.profile_status.replace("_", " ")}`}</span></div>
        <div className="flex flex-wrap justify-end gap-2">
          {l.status === "submitted" ? <button className="btn btn-primary min-h-[36px] px-3 py-1 text-xs" disabled={busy} onClick={() => onApprove(l.assignment_id)}>Approve translation</button> : null}
          <a className="btn btn-secondary min-h-[36px] px-3 py-1 text-xs" href={api.rhapsody.layoutUrl(l.assignment_id)} target="_blank" rel="noreferrer">Preview layout</a>
        </div>
      </div>
      {!profileOk && stage.key !== "new" && stage.key !== "progress" ? (
        <p className="mt-2 text-xs text-amber-600">This language has no active typesetting profile. <Link className="underline" href={`/rhapsody/publishing/profiles/${l.language}`}>Set it up</Link> before generating a proof.</p>) : null}
      <PublicationPanel assignmentId={l.assignment_id} status={l.status} />
    </div>
  );
}

export function EditionProduction() {
  const [data, setData] = useState<PublishingProduction[] | null>(null);
  const [filter, setFilter] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try { setData(await api.publishing.production()); setUpdated(new Date()); } catch (x) { setNotice({ kind: "error", text: errText(x) }); }
  }, []);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => { if (!document.hidden) void load(); }, REFRESH_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of data ?? []) for (const l of e.languages) { const k = stageOf(l).key; c[k] = (c[k] ?? 0) + 1; }
    return c;
  }, [data]);

  async function approve(id: string) {
    setBusy(true); setNotice(null);
    try { await api.rhapsody.review(id, "approved"); await load(); setNotice({ kind: "success", text: "Translation approved. It is now ready for layout." }); }
    catch (x) { setNotice({ kind: "error", text: errText(x) }); } finally { setBusy(false); }
  }

  return (
    <AdminOnly>
      <div className="space-y-5">
        {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Filter by stage">
          <button className={`pill ${filter === null ? "pill-violet" : "pill-grey"}`} onClick={() => setFilter(null)}>All · {Object.values(counts).reduce((a, b) => a + b, 0)}</button>
          {FILTERS.map((f) => (
            <button key={f.key} className={`pill pill-${filter === f.key ? f.pill : "grey"}`} aria-pressed={filter === f.key} onClick={() => setFilter(filter === f.key ? null : f.key)}>{f.label} · {counts[f.key] ?? 0}</button>))}
          <span className="ml-auto text-xs text-ink-muted">{updated ? `Updated ${updated.toLocaleTimeString()} · refreshes automatically` : ""}</span>
        </div>
        {!data ? <Spinner /> : data.length === 0 ? <EmptyState title="No editions yet">Create an edition from Rhapsody of Realities, then activate its master.</EmptyState> : data.map((e) => {
          const rows = e.languages.filter((l) => !filter || stageOf(l).key === filter)
            .sort((a, b) => STAGE_ORDER.indexOf(stageOf(a).key) - STAGE_ORDER.indexOf(stageOf(b).key) || a.language_name.localeCompare(b.language_name));
          return (
            <section key={e.edition_id} className="card space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-lg font-bold">{e.title}</h2>
                <span className="flex items-center gap-2 text-xs text-ink-muted">{e.languages.length} language(s){e.master_active ? null : <span className="pill pill-orange">Master not activated</span>}</span>
              </div>
              {rows.length ? rows.map((l) => <Row key={l.assignment_id} l={l} busy={busy} onApprove={(id) => void approve(id)} />)
                : <p className="text-sm text-ink-muted">{e.languages.length ? "No translations at this stage." : "No translations started yet."}</p>}
            </section>);
        })}
      </div>
    </AdminOnly>
  );
}
