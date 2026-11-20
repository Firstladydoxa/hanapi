"use client";

import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { api, ApiError, type AdminDirection, type AdminProject, type AdminTerm, type AdminUser, type Direction, type Language, type Member, type Role, type Tier } from "@/lib/api";
import { formatDate, ROLE_LABEL, TIER_LABEL } from "@/lib/labels";
import { Alert, EmptyState, Spinner, TierBadge } from "./ui";

const errText = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Please try again.");
const ROLES: Role[] = ["translator", "reviewer", "project_manager", "team_leader", "tni_admin", "technical_admin", "auditor"];
const TIERS: Tier[] = ["production", "assisted", "experimental", "unsupported"];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="card space-y-4"><h2 className="text-lg font-semibold">{title}</h2>{children}</section>;
}

function useLoad<T>(loader: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => { loader().then((d) => { setData(d); setError(null); }).catch((e) => setError(errText(e))); }, [loader]);
  useEffect(() => { reload(); }, [reload]);
  return { data, error, reload };
}

export function UsersPanel() {
  const { data, error, reload } = useLoad(api.admin.users);
  const [form, setForm] = useState({ email: "", display_name: "", role: "translator" as Role, password: "" });
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      const u = await api.admin.createUser({ ...form, password: form.password || undefined });
      setNotice({ kind: "success", text: u.generated_password ? `User created. One-time password (copy it now, it will not be shown again): ${u.generated_password}` : "User created." });
      setForm({ email: "", display_name: "", role: "translator", password: "" });
      reload();
    } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  async function toggle(u: AdminUser) {
    try { await api.admin.patchUser(u.id, { status: u.status === "active" ? "disabled" : "active" }); reload(); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }

  return (
    <Section title="Users">
      {error ? <Alert>{error}</Alert> : null}
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <div><label className="label" htmlFor="u-email">Email</label><input id="u-email" className="input" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div><label className="label" htmlFor="u-name">Name</label><input id="u-name" className="input" required value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} /></div>
        <div><label className="label" htmlFor="u-role">Role</label>
          <select id="u-role" className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></div>
        <div><label className="label" htmlFor="u-pw">Password (optional)</label><input id="u-pw" className="input" type="password" minLength={12} autoComplete="new-password" placeholder="Generated if empty" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
        <div className="flex items-end"><button className="btn btn-primary w-full" type="submit">Create user</button></div>
      </form>
      {!data ? <Spinner /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Name</th><th className="pr-4">Email</th><th className="pr-4">Role</th><th className="pr-4">Status</th><th /></tr></thead>
            <tbody>{data.map((u) => (
              <tr key={u.id} className="border-t border-line">
                <td className="py-2 pr-4 font-semibold">{u.display_name}</td><td className="pr-4">{u.email}</td><td className="pr-4">{ROLE_LABEL[u.role] ?? u.role}</td>
                <td className="pr-4">{u.status}</td>
                <td className="text-right"><button type="button" className="btn btn-secondary min-h-[32px] px-3" onClick={() => void toggle(u)}>{u.status === "active" ? "Disable" : "Enable"}</button></td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

export function ProjectsPanel() {
  const projects = useLoad(api.admin.projects);
  const users = useLoad(api.admin.users);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string>("");
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    try { await api.admin.createProject({ name }); setName(""); projects.reload(); setNotice({ kind: "success", text: "Project created." }); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  async function patch(p: AdminProject, b: Partial<AdminProject>) {
    try { await api.admin.patchProject(p.id, b); projects.reload(); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }

  return (
    <Section title="Projects">
      {projects.error ? <Alert>{projects.error}</Alert> : null}
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      <form onSubmit={create} className="flex flex-wrap items-end gap-3">
        <div className="min-w-[240px] flex-1"><label className="label" htmlFor="p-name">New project name</label><input id="p-name" className="input" required value={name} onChange={(e) => setName(e.target.value)} /></div>
        <button className="btn btn-primary" type="submit">Create project</button>
      </form>
      {!projects.data ? <Spinner /> : projects.data.length === 0 ? <EmptyState title="No projects yet" /> : (
        <ul className="space-y-3">{projects.data.map((p) => (
          <li key={p.id} className="rounded-lg border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><p className="font-semibold">{p.name}</p><p className="text-xs text-ink-muted">{p.status}</p></div>
              <div className="flex flex-wrap items-center gap-4 text-xs">
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={p.allow_external_processing} onChange={(e) => void patch(p, { allow_external_processing: e.target.checked })} /> Allow external processing</label>
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={p.pilot_opt_in} onChange={(e) => void patch(p, { pilot_opt_in: e.target.checked })} /> Pilot opt-in</label>
                <button type="button" className="btn btn-secondary min-h-[32px] px-3" onClick={() => setSelected(selected === p.id ? "" : p.id)}>Members</button>
              </div>
            </div>
            {selected === p.id ? <Members projectId={p.id} users={users.data ?? []} /> : null}
          </li>))}
        </ul>
      )}
    </Section>
  );
}

function Members({ projectId, users }: { projectId: string; users: AdminUser[] }) {
  const loader = useCallback(() => api.admin.members(projectId), [projectId]);
  const { data, reload } = useLoad<Member[]>(loader);
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("translator");
  const [msg, setMsg] = useState<string | null>(null);

  async function save(next: { user_id: string; role: string; can_approve?: boolean }[]) {
    try { await api.admin.putMembers(projectId, next); reload(); setMsg(null); } catch (err) { setMsg(errText(err)); }
  }
  if (!data) return <Spinner />;
  const current = data.map((m) => ({ user_id: m.user_id, role: m.role, can_approve: m.can_approve }));
  return (
    <div className="mt-3 space-y-3 border-t border-line pt-3">
      {msg ? <Alert>{msg}</Alert> : null}
      <ul className="space-y-1 text-sm">{data.map((m) => (
        <li key={m.user_id} className="flex items-center justify-between gap-2">
          <span>{m.display_name} <span className="text-xs text-ink-muted">({m.email}) · {m.role}{m.can_approve ? " · can approve" : ""}</span></span>
          <button type="button" className="text-xs font-semibold text-danger-text underline" onClick={() => void save(current.filter((c) => c.user_id !== m.user_id))}>Remove</button>
        </li>))}
      </ul>
      <div className="flex flex-wrap items-end gap-2">
        <div><label className="label" htmlFor={`m-user-${projectId}`}>Add member</label>
          <select id={`m-user-${projectId}`} className="input" value={userId} onChange={(e) => setUserId(e.target.value)}>
            <option value="">Select user…</option>{users.filter((u) => !data.some((m) => m.user_id === u.id)).map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select></div>
        <div><label className="label" htmlFor={`m-role-${projectId}`}>Project role</label>
          <select id={`m-role-${projectId}`} className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            {["translator", "reviewer", "project_manager"].map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}</select></div>
        <button type="button" className="btn btn-primary" disabled={!userId} onClick={() => { void save([...current, { user_id: userId, role }]); setUserId(""); }}>Add</button>
      </div>
    </div>
  );
}

export function TerminologyPanel() {
  const projects = useLoad(api.admin.projects);
  const terms = useLoad<AdminTerm[]>(useCallback(() => api.admin.terms(), []));
  const [form, setForm] = useState({ project_id: "", source_language: "en", target_language: "de", source_term: "", target_term: "" });
  const [notice, setNotice] = useState<string | null>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    try {
      await api.admin.createTerm({ ...form, project_id: form.project_id || undefined, scope: form.project_id ? "project" : "global" });
      setForm({ ...form, source_term: "", target_term: "" });
      terms.reload();
      setNotice(null);
    } catch (err) { setNotice(errText(err)); }
  }
  async function setStatus(t: AdminTerm, status: string) {
    try { await api.admin.patchTerm(t.term_id, { status, comment: `Status set to ${status}` }); terms.reload(); } catch (err) { setNotice(errText(err)); }
  }
  return (
    <Section title="Terminology">
      {terms.error ? <Alert>{terms.error}</Alert> : null}
      {notice ? <Alert>{notice}</Alert> : null}
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <div className="lg:col-span-2"><label className="label" htmlFor="t-project">Scope</label>
          <select id="t-project" className="input" value={form.project_id} onChange={(e) => setForm({ ...form, project_id: e.target.value })}>
            <option value="">Global glossary</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
        <div><label className="label" htmlFor="t-src">From</label><input id="t-src" className="input" required maxLength={16} value={form.source_language} onChange={(e) => setForm({ ...form, source_language: e.target.value })} /></div>
        <div><label className="label" htmlFor="t-tgt">To</label><input id="t-tgt" className="input" required maxLength={16} value={form.target_language} onChange={(e) => setForm({ ...form, target_language: e.target.value })} /></div>
        <div><label className="label" htmlFor="t-st">Source term</label><input id="t-st" className="input" required value={form.source_term} onChange={(e) => setForm({ ...form, source_term: e.target.value })} /></div>
        <div><label className="label" htmlFor="t-tt">Target term</label><input id="t-tt" className="input" required value={form.target_term} onChange={(e) => setForm({ ...form, target_term: e.target.value })} /></div>
        <div className="lg:col-span-6"><button className="btn btn-primary" type="submit">Add term (saved as draft)</button></div>
      </form>
      {!terms.data ? <Spinner /> : terms.data.length === 0 ? <p className="text-sm text-ink-muted">No terms yet.</p> : (
        <div className="overflow-x-auto"><table className="w-full text-left text-sm">
          <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Term</th><th className="pr-4">Pair</th><th className="pr-4">Scope</th><th className="pr-4">Status</th><th /></tr></thead>
          <tbody>{terms.data.map((t) => (
            <tr key={t.term_id} className="border-t border-line">
              <td className="py-2 pr-4">{t.source_term} → <strong>{t.target_term}</strong></td><td className="pr-4">{t.source_language}→{t.target_language}</td><td className="pr-4">{t.scope}</td><td className="pr-4">{t.status}</td>
              <td className="space-x-2 text-right">
                {t.status !== "approved" ? <button type="button" className="btn btn-secondary min-h-[32px] px-3" onClick={() => void setStatus(t, "approved")}>Approve</button> : null}
                {t.status !== "deprecated" ? <button type="button" className="btn btn-secondary min-h-[32px] px-3" onClick={() => void setStatus(t, "deprecated")}>Deprecate</button> : null}
              </td></tr>))}
          </tbody></table></div>
      )}
    </Section>
  );
}

const TECH_STYLE: Record<string, string> = { passed: "text-ok-text", degraded: "text-warn-text", failed: "text-danger-text", untested: "text-ink-muted" };
const VALIDATION = ["pending", "in_review", "validated", "rejected"] as const;
const PAGE = 80;

export function ReadinessPanel() {
  const dirs = useLoad(api.admin.directions);
  const langs = useLoad<Language[]>(api.languages);
  const [pending, setPending] = useState<Record<string, { tier: Tier; note: string }>>({});
  const [add, setAdd] = useState({ source: "en", target: "de", tier: "experimental" as Tier });
  const [notice, setNotice] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [q, setQ] = useState("");
  const [tierF, setTierF] = useState<"all" | Tier>("all");
  const [techF, setTechF] = useState("all");
  const [limit, setLimit] = useState(PAGE);
  const [tests, setTests] = useState<Record<string, string>>({});
  const key = (d: Pick<Direction, "source_code" | "target_code">) => `${d.source_code}>${d.target_code}`;
  const all = useMemo(() => dirs.data ?? [], [dirs.data]);
  const rows = useMemo(() => {
    const t = q.trim().toLowerCase();
    return all.filter((d) => (tierF === "all" || d.readiness_tier === tierF) && (techF === "all" || d.technical_status === techF) && (!t || key(d).includes(t)));
  }, [all, q, tierF, techF]);
  const summary = useMemo(() => {
    const c: Record<string, number> = {};
    for (const d of all) c[d.readiness_tier] = (c[d.readiness_tier] ?? 0) + 1;
    return c;
  }, [all]);

  async function save() {
    const changes = Object.entries(pending).map(([k, v]) => { const [source_code = "", target_code = ""] = k.split(">"); return { source_code, target_code, readiness_tier: v.tier, review_note: v.note || undefined }; });
    if (changes.length === 0) return;
    try { await api.admin.putDirections(changes); setPending({}); dirs.reload(); setNotice({ kind: "success", text: "Language readiness saved." }); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  async function addPair(e: FormEvent) {
    e.preventDefault();
    try { await api.admin.putDirections([{ source_code: add.source, target_code: add.target, readiness_tier: add.tier }]); dirs.reload(); setNotice({ kind: "success", text: "Language pair added." }); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  async function enablePilot() {
    if (!window.confirm("Open every technically verified English pair for controlled testing? These stay Experimental and are visible only to pilot projects. Nothing becomes Production.")) return;
    try { const r = await api.admin.enablePilot(); dirs.reload(); setNotice({ kind: "success", text: `Controlled testing enabled for ${String(r.directions_enabled ?? 0)} directions.` }); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  async function runTest(d: AdminDirection) {
    setTests((t) => ({ ...t, [key(d)]: "Testing…" }));
    try { const r = await api.admin.testDirection({ source_code: d.source_code, target_code: d.target_code }); setTests((t) => ({ ...t, [key(d)]: `${r.technical_status}${r.flag ? ` (${r.flag.replace("_", " ")})` : ""}: ${r.output.slice(0, 80)}` })); dirs.reload(); }
    catch (err) { setTests((t) => ({ ...t, [key(d)]: errText(err) })); }
  }
  async function validate(d: AdminDirection, v: AdminDirection["validation_status"]) {
    try { await api.admin.setValidation({ source_code: d.source_code, target_code: d.target_code, validation_status: v }); dirs.reload(); } catch (err) { setNotice({ kind: "error", text: errText(err) }); }
  }
  return (
    <Section title="Language readiness">
      <p className="text-sm text-ink-muted">Three independent things are tracked per direction: the <strong>tier</strong> (what translators may use), the <strong>technical check</strong> (does the system produce usable output) and <strong>human validation</strong> (has a qualified reviewer judged the quality). A passing technical check never makes a language Production; that is a human decision.</p>
      <p className="text-xs text-ink-muted">Directions by tier: {TIERS.map((t) => `${TIER_LABEL[t]} ${summary[t] ?? 0}`).join(" · ")}</p>
      {notice ? <Alert kind={notice.kind}>{notice.text}</Alert> : null}
      {dirs.error ? <Alert>{dirs.error}</Alert> : null}
      <div className="flex flex-wrap items-end gap-3">
        <button type="button" className="btn btn-secondary" onClick={() => void enablePilot()}>Enable verified languages for controlled testing</button>
      </div>
      <form onSubmit={addPair} className="flex flex-wrap items-end gap-3">
        <div><label className="label" htmlFor="d-src">From</label><select id="d-src" className="input" value={add.source} onChange={(e) => setAdd({ ...add, source: e.target.value })}>{langs.data?.map((l) => <option key={l.code} value={l.code}>{l.display_name}</option>)}</select></div>
        <div><label className="label" htmlFor="d-tgt">To</label><select id="d-tgt" className="input" value={add.target} onChange={(e) => setAdd({ ...add, target: e.target.value })}>{langs.data?.map((l) => <option key={l.code} value={l.code}>{l.display_name}</option>)}</select></div>
        <div><label className="label" htmlFor="d-tier">Tier</label><select id="d-tier" className="input" value={add.tier} onChange={(e) => setAdd({ ...add, tier: e.target.value as Tier })}>{TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}</select></div>
        <button className="btn btn-secondary" type="submit">Add pair</button>
      </form>
      <div className="flex flex-wrap items-end gap-3">
        <div><label className="label" htmlFor="f-q">Filter by code</label><input id="f-q" className="input" placeholder="e.g. yo" value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} /></div>
        <div><label className="label" htmlFor="f-tier">Tier</label><select id="f-tier" className="input" value={tierF} onChange={(e) => { setTierF(e.target.value as "all" | Tier); setLimit(PAGE); }}><option value="all">All tiers</option>{TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}</select></div>
        <div><label className="label" htmlFor="f-tech">Technical check</label><select id="f-tech" className="input" value={techF} onChange={(e) => { setTechF(e.target.value); setLimit(PAGE); }}>{["all", "passed", "degraded", "failed", "untested"].map((t) => <option key={t} value={t}>{t === "all" ? "Any" : t}</option>)}</select></div>
      </div>
      {!dirs.data ? <Spinner /> : rows.length === 0 ? <p className="text-sm text-ink-muted">No directions match.</p> : (
        <>
          <p className="text-xs text-ink-muted">Showing {Math.min(limit, rows.length)} of {rows.length}</p>
          <div className="overflow-x-auto"><table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-ink-muted"><tr><th className="py-2 pr-4">Direction</th><th className="pr-4">Current</th><th className="pr-4">New tier</th><th className="pr-4">Technical</th><th className="pr-4">Human validation</th><th>Review note</th></tr></thead>
            <tbody>{rows.slice(0, limit).map((d) => { const k = key(d); const p = pending[k]; return (
              <tr key={k} className="border-t border-line align-top">
                <td className="py-2 pr-4 font-semibold">{d.source_code} → {d.target_code}</td><td className="pr-4"><TierBadge tier={d.readiness_tier} /></td>
                <td className="pr-4"><label className="sr-only" htmlFor={`t-${k}`}>Tier for {k}</label>
                  <select id={`t-${k}`} className="input min-h-[34px] py-1" value={p?.tier ?? d.readiness_tier} onChange={(e) => setPending({ ...pending, [k]: { tier: e.target.value as Tier, note: p?.note ?? d.review_note ?? "" } })}>{TIERS.map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}</select></td>
                <td className="pr-4 text-xs"><span className={TECH_STYLE[d.technical_status]}>{d.technical_status}</span>
                  <button type="button" className="ml-2 underline" onClick={() => void runTest(d)}>Test</button>
                  {tests[k] ? <span className="mt-1 block max-w-[260px] break-words text-ink-muted">{tests[k]}</span> : null}</td>
                <td className="pr-4"><label className="sr-only" htmlFor={`v-${k}`}>Validation for {k}</label>
                  <select id={`v-${k}`} className="input min-h-[34px] py-1" value={d.validation_status} onChange={(e) => void validate(d, e.target.value as AdminDirection["validation_status"])}>{VALIDATION.map((v) => <option key={v} value={v}>{v.replace("_", " ")}</option>)}</select></td>
                <td><label className="sr-only" htmlFor={`n-${k}`}>Note for {k}</label>
                  <input id={`n-${k}`} className="input min-h-[34px] py-1" value={p?.note ?? d.review_note ?? ""} onChange={(e) => setPending({ ...pending, [k]: { tier: p?.tier ?? d.readiness_tier, note: e.target.value } })} /></td>
              </tr>); })}</tbody></table></div>
          <div className="flex gap-3">
            {rows.length > limit ? <button type="button" className="btn btn-secondary" onClick={() => setLimit(limit + PAGE)}>Show more</button> : null}
            <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={Object.keys(pending).length === 0}>Save changes</button>
          </div>
        </>
      )}
    </Section>
  );
}

export function AuditPanel() {
  const { data, error } = useLoad(useCallback(() => api.admin.audit({ limit: 100 }), []));
  if (error) return <Alert>{error}</Alert>;
  if (!data) return <Spinner />;
  return (
    <Section title="Audit events">
      <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <thead className="uppercase text-ink-muted"><tr><th className="py-2 pr-3">When</th><th className="pr-3">Action</th><th className="pr-3">Actor role</th><th className="pr-3">Object</th><th className="pr-3">Outcome</th><th>Request</th></tr></thead>
        <tbody>{data.map((e) => (
          <tr key={e.id} className="border-t border-line"><td className="py-1.5 pr-3 whitespace-nowrap">{formatDate(e.created_at)}</td><td className="pr-3 font-semibold">{e.action}</td><td className="pr-3">{e.actor_role ?? "—"}</td>
            <td className="pr-3">{e.object_type ?? "—"}</td><td className="pr-3">{e.outcome}</td><td className="font-mono">{e.request_id?.slice(0, 8) ?? "—"}</td></tr>))}
        </tbody></table></div>
    </Section>
  );
}

function Table({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="text-sm text-ink-muted">No records.</p>;
  const cols = Object.keys(rows[0] ?? {});
  return (
    <div className="overflow-x-auto"><table className="w-full text-left text-xs">
      <thead className="uppercase text-ink-muted"><tr>{cols.map((c) => <th key={c} className="py-2 pr-3">{c}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-line">{cols.map((c) => <td key={c} className="py-1.5 pr-3 align-top">{String(r[c] ?? "—")}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

/** Protected operational view. It simply shows what the backend returns; a 403 means the account lacks engine access. */
export function OpsPanel() {
  const [state, setState] = useState<{ models: Record<string, unknown>[]; events: Record<string, unknown>[]; usage: Record<string, unknown>[]; health: Record<string, unknown> } | null>(null);
  const [error, setError] = useState<{ restricted: boolean; text: string } | null>(null);
  useEffect(() => {
    Promise.all([api.admin.models(), api.admin.routingEvents(), api.admin.usage(), api.admin.health()])
      .then(([models, events, usage, health]) => setState({ models, events, usage: usage.rows, health }))
      .catch((e) => setError({ restricted: e instanceof ApiError && e.status === 403, text: errText(e) }));
  }, []);
  if (error?.restricted) return <EmptyState title="Access restricted">Operational details are available only to technical administrators.</EmptyState>;
  if (error) return <Alert>{error.text}</Alert>;
  if (!state) return <Spinner />;
  return (
    <div className="space-y-5">
      <Section title="Service health"><pre className="overflow-x-auto rounded-lg bg-wash p-3 text-xs">{JSON.stringify(state.health, null, 2)}</pre></Section>
      <Section title="Model registry"><Table rows={state.models} /></Section>
      <Section title="Usage (cost, latency, errors)"><Table rows={state.usage} /></Section>
      <Section title="Recent routing events"><Table rows={state.events.slice(0, 100)} /></Section>
    </div>
  );
}
