"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type Job, type JobSegment, type JobSummary, type ProjectDetail, type TermResult, type TMResult } from "@/lib/api";
import { buildExport, downloadText } from "@/lib/export";
import { KIND_STYLE, TIER_LABEL, versionKind } from "@/lib/labels";
import { pairKey, usableDirections } from "./QuickTranslate";
import { ReviewPanel } from "./ReviewPanel";
import { Alert, EmptyState, Spinner, StatusChip } from "./ui";

const ACTIVE = new Set(["queued", "processing"]);
const askHan = (projectId: string, id: string) => window.location.assign(`/projects/${projectId}/chat?about=${encodeURIComponent(id)}`);

export function Workspace({ project, names, openTranslationId }: { project: ProjectDetail; names: Record<string, string>; openTranslationId?: string | null }) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newOpen, setNewOpen] = useState(false);

  const loadJobs = useCallback(async () => {
    try { setJobs(await api.jobs(project.id)); } catch (e) { setError(e instanceof ApiError ? e.message : "Unable to load jobs."); }
  }, [project.id]);

  useEffect(() => { void loadJobs(); }, [loadJobs]);
  useEffect(() => { if (jobs && jobs.length === 0 && !openTranslationId) setNewOpen(true); }, [jobs, openTranslationId]);

  return (
    <div className="han-stack">
      <section className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">New translation job</h2>
            <p className="text-xs text-ink-muted">Paste a longer text; paragraphs become segments you can review one by one.</p>
          </div>
          <button type="button" className="btn btn-secondary" aria-expanded={newOpen} onClick={() => setNewOpen((o) => !o)}>{newOpen ? "Hide form" : "＋ New job"}</button>
        </div>
        {newOpen ? <div className="mt-4 border-t border-line pt-4"><NewJob project={project} names={names} onCreated={(id) => { setJobId(id); setNewOpen(false); void loadJobs(); }} /></div> : null}
      </section>

      <section aria-labelledby="jobs-title">
        <h2 id="jobs-title" className="han-section-title">Your jobs</h2>
        {error ? <Alert>{error}</Alert> : null}
        {!jobs && !error ? <Spinner /> : null}
        {jobs?.length === 0 ? <p className="text-sm text-ink-muted">No jobs yet. Create one above.</p> : null}
        <div className="han-job-grid">
          {jobs?.map((j) => (
            <button key={j.job_id} type="button" className="han-job-card" onClick={() => setJobId(j.job_id)} aria-current={jobId === j.job_id}>
              <span className="block text-sm font-semibold">{j.title || `${names[j.source_language] ?? j.source_language} → ${names[j.target_language] ?? j.target_language}`}</span>
              <span className="mt-1 block text-xs text-ink-muted">{j.progress.approved}/{j.progress.total} approved · {j.status}</span>
            </button>
          ))}
        </div>
      </section>

      <section aria-label="Selected job">
        {jobId ? <JobView key={jobId} jobId={jobId} project={project} onChanged={() => void loadJobs()} />
          : openTranslationId ? (
            <div className="card"><h2 className="mb-3 text-lg font-semibold">Quick translation</h2>
              <ReviewPanel translationId={openTranslationId} canApprove={project.can_approve} onAskHan={() => askHan(project.id, openTranslationId)} /></div>
          ) : <EmptyState title="Select or create a job">Choose a job above to review its segments.</EmptyState>}
      </section>
    </div>
  );
}

function NewJob({ project, names, onCreated }: { project: ProjectDetail; names: Record<string, string>; onCreated: (id: string) => void }) {
  const directions = useMemo(() => usableDirections(project), [project]);
  const [pair, setPair] = useState(directions[0] ? pairKey(directions[0]) : "");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const [source, target] = pair.split(">");
    if (!source || !target) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.createJob({ project_id: project.id, source_language: source, target_language: target, title: title.trim() || undefined, text });
      setText("");
      setTitle("");
      onCreated(r.job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "I couldn't start this job. Please try again shortly.");
    } finally { setBusy(false); }
  }

  if (directions.length === 0) return <Alert kind="info">No language pairs are available for this project yet.</Alert>;
  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
      <div>
        <label className="label" htmlFor="job-title">Title (optional)</label>
        <input id="job-title" className="input" maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>
      <div>
        <label className="label" htmlFor="job-pair">Language pair</label>
        <select id="job-pair" className="input" value={pair} onChange={(e) => setPair(e.target.value)}>
          {directions.map((d) => <option key={pairKey(d)} value={pairKey(d)}>{names[d.source_code] ?? d.source_code} → {names[d.target_code] ?? d.target_code} ({TIER_LABEL[d.readiness_tier]})</option>)}
        </select>
      </div>
      </div>
      <div>
        <label className="label" htmlFor="job-text">Text (paragraphs become segments)</label>
        <textarea id="job-text" className="input min-h-[160px]" value={text} onChange={(e) => setText(e.target.value)} maxLength={200000} />
      </div>
      {error ? <Alert>{error}</Alert> : null}
      <button className="btn btn-primary" type="submit" disabled={busy || !text.trim()}>{busy ? "Preparing…" : "Create job"}</button>
    </form>
  );
}

function JobView({ jobId, project, onChanged }: { jobId: string; project: ProjectDetail; onChanged: () => void }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try { setJob(await api.job(jobId)); } catch (e) { setError(e instanceof ApiError ? e.message : "Unable to load this job."); }
  }, [jobId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {
    if (!job || !ACTIVE.has(job.status)) return;
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [job, refresh]);

  if (error) return <Alert>{error}</Alert>;
  if (!job) return <Spinner label="Loading job" />;

  const pct = job.progress.total ? Math.round((job.progress.approved / job.progress.total) * 100) : 0;
  const exportApproved = buildExport(job, false);
  const exportDrafts = buildExport(job, true);

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">{job.title || "Translation job"}</h2>
            <p className="text-xs text-ink-muted">{job.source_language.toUpperCase()} → {job.target_language.toUpperCase()} · {job.status}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn btn-secondary" disabled={exportApproved.count === 0} onClick={() => downloadText("han-approved.txt", exportApproved.text)}>Export approved ({exportApproved.count})</button>
            <button type="button" className="btn btn-secondary" disabled={exportDrafts.count === 0} onClick={() => downloadText("han-draft-for-review.txt", exportDrafts.text)}
              title="Includes unapproved drafts. For review only, not final work.">Export incl. drafts ({exportDrafts.count})</button>
          </div>
        </div>
        <div className="mt-3" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Approved segments">
          <div className="h-2 overflow-hidden rounded-full bg-wash"><div className="h-full bg-brand transition-all" style={{ width: `${pct}%` }} /></div>
          <p className="mt-1 text-xs text-ink-muted">{job.progress.approved} approved · {job.progress.done} drafted · {job.progress.total} segments</p>
        </div>
        {ACTIVE.has(job.status) ? <p className="mt-2"><Spinner label="HAN is preparing drafts" /></p> : null}
        {job.status === "partial" || job.status === "failed" ? <div className="mt-2"><Alert kind="info">Some segments couldn&apos;t be drafted and are marked &quot;Needs attention&quot;. Please translate them manually or try again later.</Alert></div> : null}
      </div>

      <ul className="space-y-3" aria-label="Segments">
        {job.segments.map((s) => (
          <SegmentRow key={s.segment_id} seg={s} open={s.segment_id === activeId} onToggle={() => setActiveId(s.segment_id === activeId ? null : s.segment_id)}>
            <ActiveSegment key={s.segment_id} seg={s} job={job} project={project} onChanged={() => { void refresh(); onChanged(); }} />
          </SegmentRow>
        ))}
      </ul>
    </div>
  );
}

function SegmentRow({ seg, open, onToggle, children }: { seg: JobSegment; open: boolean; onToggle: () => void; children: ReactNode }) {
  const v = seg.current_version;
  const kind = v ? versionKind(v) : null;
  return (
    <li className={`han-segment-row ${open ? "is-open" : ""}`}>
      <button type="button" onClick={onToggle} aria-expanded={open}
        className="grid w-full gap-3 p-4 text-left sm:grid-cols-2">
        <div>
          <p className="mb-1 text-[11px] font-bold text-ink-muted">#{seg.sequence} · Source</p>
          <p className="whitespace-pre-wrap text-sm">{seg.source_text}</p>
        </div>
        <div>
          <p className="mb-1 flex items-center justify-between gap-2 text-[11px] font-bold text-ink-muted">Target <span className="inline-flex items-center gap-2"><StatusChip status={seg.status} /><span aria-hidden>{open ? "▴" : "▾"}</span></span></p>
          {v && kind ? <p className={`whitespace-pre-wrap rounded-md border px-2 py-1 text-sm ${KIND_STYLE[kind]}`}>{v.target_text}</p> : <p className="text-sm italic text-ink-muted">Not translated</p>}
          {seg.warnings.length ? <p className="mt-1 text-[11px] font-semibold text-warn-text">{seg.warnings.length} check{seg.warnings.length > 1 ? "s" : ""} to review</p> : null}
        </div>
      </button>
      {open ? <div className="han-segment-detail">{children}</div> : null}
    </li>
  );
}

function ActiveSegment({ seg, job, project, onChanged }: { seg: JobSegment; job: Job; project: ProjectDetail; onChanged: () => void }) {
  const [tm, setTm] = useState<TMResult[]>([]);
  const [terms, setTerms] = useState<TermResult[]>([]);

  useEffect(() => {
    let live = true;
    const base = { project_id: project.id, source_language: job.source_language, target_language: job.target_language };
    api.tmSearch({ ...base, q: seg.source_text.slice(0, 2000) }).then((r) => live && setTm(r.results)).catch(() => undefined);
    api.termSearch(base).then((r) => live && setTerms(r.results.filter((t) => seg.source_text.toLowerCase().includes(t.source_term.toLowerCase())))).catch(() => undefined);
    return () => { live = false; };
  }, [seg.source_text, seg.segment_id, project.id, job.source_language, job.target_language]);

  if (!seg.current_version) return <EmptyState title="No draft for this segment">HAN couldn&apos;t prepare a draft. Please translate it manually or try again later.</EmptyState>;
  return (
    <div>
      <ReviewPanel translationId={seg.segment_id} canApprove={project.can_approve} onChanged={onChanged} onAskHan={() => askHan(project.id, seg.segment_id)}
        context={{
          warnings: seg.warnings,
          tm_matches: tm.map((m) => ({ source_text: m.source_text, target_text: m.target_text, match_percent: m.match_percent, tm_id: m.tm_id })),
          terminology: terms.map((t) => ({ source_term: t.source_term, target_term: t.target_term, usage_note: t.usage_note, forbidden: t.forbidden })),
        }} />
    </div>
  );
}
