"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError, type LanguageSupport, type ProjectListItem, type ReviewContentType, type ReviewDraft, type ReviewMine, type ReviewSample, type ReviewSeverity } from "@/lib/api";
import { Alert, Field, Spinner } from "./ui";

const CONTENT: { value: ReviewContentType; label: string }[] = [
  { value: "general", label: "General" }, { value: "scripture", label: "Scripture" }, { value: "ministry", label: "Ministry" },
  { value: "terminology", label: "Terminology" }, { value: "other", label: "Other" },
];
const SEVERITY: { value: ReviewSeverity; label: string; help: string }[] = [
  { value: "none", label: "No errors", help: "Correct and ready to use" },
  { value: "minor", label: "Minor", help: "Small wording or style issues; meaning is intact" },
  { value: "major", label: "Major", help: "Meaning is changed or hard to understand" },
  { value: "critical", label: "Critical", help: "Dangerous, offensive or doctrinally wrong" },
];
const SCALE = [1, 2, 3, 4, 5];

function Scale({ id, label, hint, value, onChange }: { id: string; label: string; hint: string; value: number; onChange: (n: number) => void }) {
  return (
    <fieldset aria-labelledby={`${id}-l`}>
      <legend id={`${id}-l`} className="label">{label}</legend>
      <div className="flex gap-2" role="radiogroup" aria-label={label}>
        {SCALE.map((n) => (
          <button key={n} type="button" role="radio" aria-checked={value === n} onClick={() => onChange(n)}
            className={`btn min-w-[42px] ${value === n ? "btn-primary" : "btn-secondary"}`}>{n}</button>
        ))}
      </div>
      <p className="mt-1 text-xs text-ink-muted">{hint}</p>
    </fieldset>
  );
}

export function ReviewLanguages() {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [langs, setLangs] = useState<LanguageSupport[]>([]);
  const [samples, setSamples] = useState<ReviewSample[]>([]);
  const [projectId, setProjectId] = useState("");
  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("");
  const [text, setText] = useState("");
  const [contentType, setContentType] = useState<ReviewContentType>("general");
  const [draft, setDraft] = useState<ReviewDraft | null>(null);
  const [adequacy, setAdequacy] = useState(0);
  const [fluency, setFluency] = useState(0);
  const [severity, setSeverity] = useState<ReviewSeverity | "">("");
  const [comment, setComment] = useState("");
  const [mine, setMine] = useState<ReviewMine[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.projects(), api.languageSupport(), api.reviews.samples()])
      .then(([p, l, s]) => { setProjects(p); setProjectId(p[0]?.id ?? ""); setLangs(l.filter((x) => x.availability !== "not_enabled")); setSamples(s); })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Unable to load the review tools."));
  }, []);

  const names = useMemo(() => Object.fromEntries(langs.map((l) => [l.code, l.name])), [langs]);
  const reloadMine = useCallback(() => {
    if (source && target) api.reviews.mine(source, target).then(setMine).catch(() => setMine([]));
  }, [source, target]);
  useEffect(() => { setDraft(null); setDone(null); reloadMine(); }, [source, target, reloadMine]);

  const reset = () => { setDraft(null); setAdequacy(0); setFluency(0); setSeverity(""); setComment(""); setText(""); };
  const valid = adequacy > 0 && fluency > 0 && severity !== "";

  async function getDraft() {
    setBusy(true); setError(null); setDone(null);
    try { setDraft(await api.reviews.draft({ project_id: projectId, source_code: source, target_code: target, text: text.trim() })); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not prepare a draft."); }
    finally { setBusy(false); }
  }
  async function submit() {
    if (!draft || !valid) return;
    setBusy(true); setError(null);
    try {
      await api.reviews.submit({ source_code: source, target_code: target, source_text: draft.source_text, draft_text: draft.draft_text, version_id: draft.version_id,
        content_type: contentType, adequacy, fluency, severity: severity as ReviewSeverity, comment: comment.trim() || undefined });
      setDone("Thank you. Your score has been recorded."); reset(); reloadMine();
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not save your score."); }
    finally { setBusy(false); }
  }

  if (!projects) return error ? <Alert>{error}</Alert> : <Spinner label="Loading review tools" />;
  if (!projects.length) return <Alert kind="info">You need to be a member of a project before you can review drafts.</Alert>;
  const pair = source && target && source !== target;
  const countByType = CONTENT.map((c) => ({ ...c, n: mine.filter((m) => m.content_type === c.value).length })).filter((c) => c.n);

  return (
    <div className="space-y-5">
      <Alert kind="info">Help vet a language: choose a language pair you know well, get HAN&apos;s draft for a sentence, and score it honestly. TNI uses these scores to decide whether a language is ready. Nothing you score is published.</Alert>
      {error ? <Alert>{error}</Alert> : null}
      {done ? <Alert kind="success">{done}</Alert> : null}

      <section className="card space-y-4" aria-label="Choose languages">
        <div className="grid gap-3 sm:grid-cols-3">
          {projects.length > 1 ? (
            <Field label="Project" htmlFor="rv-project"><select id="rv-project" className="input" value={projectId} onChange={(e) => setProjectId(e.target.value)}>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></Field>
          ) : null}
          <Field label="From" htmlFor="rv-from"><select id="rv-from" className="input" value={source} onChange={(e) => setSource(e.target.value)}>{langs.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select></Field>
          <Field label="To" htmlFor="rv-to"><select id="rv-to" className="input" value={target} onChange={(e) => setTarget(e.target.value)}><option value="">Choose a language</option>{langs.filter((l) => l.code !== source).map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}</select></Field>
        </div>
        {pair ? <p className="text-xs text-ink-muted">You have scored <strong className="text-ink">{mine.length}</strong> draft{mine.length === 1 ? "" : "s"} for {names[source] ?? source} → {names[target] ?? target}{countByType.length ? ` (${countByType.map((c) => `${c.label} ${c.n}`).join(", ")})` : ""}. Reviewers are asked for at least 10 scored drafts per language pair, across different kinds of text.</p> : null}
      </section>

      {pair ? (
        <section className="card space-y-4" aria-label="Score a draft">
          {!draft ? (
            <>
              {source === "en" ? (
                <div>
                  <p className="label">Suggested sentences</p>
                  <div className="flex flex-wrap gap-2">
                    {samples.map((s) => (
                      <button key={s.text} type="button" className="rounded-full border border-line bg-surface px-3 py-1 text-left text-xs text-ink-soft hover:bg-wash"
                        onClick={() => { setText(s.text); setContentType(s.content_type); }}>{s.text.length > 58 ? `${s.text.slice(0, 58)}…` : s.text}</button>
                    ))}
                  </div>
                </div>
              ) : null}
              <Field label={`Sentence in ${names[source] ?? source}`} htmlFor="rv-text"><textarea id="rv-text" className="input min-h-[96px]" maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} /></Field>
              <Field label="Kind of text" htmlFor="rv-type"><select id="rv-type" className="input sm:max-w-xs" value={contentType} onChange={(e) => setContentType(e.target.value as ReviewContentType)}>{CONTENT.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}</select></Field>
              <button type="button" className="btn btn-primary" disabled={busy || !text.trim()} onClick={() => void getDraft()}>{busy ? "Preparing draft…" : "Get HAN's draft"}</button>
            </>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-line bg-wash p-3"><p className="label">Original ({names[source] ?? source})</p><p className="whitespace-pre-wrap text-sm">{draft.source_text}</p></div>
                <div className="rounded-lg border border-line bg-wash p-3"><p className="label">HAN&apos;s draft ({names[target] ?? target})</p><p className="whitespace-pre-wrap text-sm">{draft.draft_text}</p></div>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <Scale id="rv-adq" label="Adequacy" hint="1 = meaning lost, 5 = the full meaning is carried over" value={adequacy} onChange={setAdequacy} />
                <Scale id="rv-flu" label="Fluency" hint="1 = unnatural or unreadable, 5 = reads naturally to a native speaker" value={fluency} onChange={setFluency} />
              </div>
              <fieldset>
                <legend className="label">Most serious error</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {SEVERITY.map((o) => (
                    <label key={o.value} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 text-sm ${severity === o.value ? "border-brand bg-brand-light" : "border-line"}`}>
                      <input type="radio" name="rv-sev" checked={severity === o.value} onChange={() => setSeverity(o.value)} className="mt-1" />
                      <span><span className="font-semibold">{o.label}</span><span className="block text-xs text-ink-muted">{o.help}</span></span>
                    </label>
                  ))}
                </div>
              </fieldset>
              <Field label="Comment (optional)" htmlFor="rv-comment"><textarea id="rv-comment" className="input min-h-[64px]" maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="What is wrong, or what would you change?" /></Field>
              <div className="flex gap-2">
                <button type="button" className="btn btn-primary" disabled={busy || !valid} onClick={() => void submit()}>{busy ? "Saving…" : "Save score"}</button>
                <button type="button" className="btn btn-secondary" disabled={busy} onClick={reset}>Skip this sentence</button>
              </div>
            </>
          )}
        </section>
      ) : null}
    </div>
  );
}
