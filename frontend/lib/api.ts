/**
 * Typed client for the HAN API. The browser only talks to same-origin `/v1/*` (proxied to the backend);
 * it never holds provider credentials and never calls a model provider.
 */

export type Role = "translator" | "reviewer" | "project_manager" | "team_leader" | "tni_admin" | "technical_admin" | "auditor";
export type Tier = "production" | "assisted" | "experimental" | "unsupported";
export type SegmentStatus = "not_started" | "draft" | "in_review" | "approved" | "rejected" | "needs_attention";
export type JobStatus = "queued" | "processing" | "ready" | "failed" | "partial";

export interface User { id: string; email: string; display_name: string; role: Role; status: string; expertise_language?: string | null; expertise_language_name?: string | null }
export interface RegistrationLanguage { code: string; display_name: string; native_name: string | null }
export interface Session { user: User; csrf_token: string }
export interface ProjectListItem { id: string; name: string; domain: string | null; style: string | null; member_role: string }
export interface Direction { source_code: string; target_code: string; readiness_tier: Tier; review_note: string | null }
export interface ProjectDetail extends ProjectListItem { instructions: string | null; can_approve: boolean; language_directions: Direction[] }
export interface Language { code: string; display_name: string; script: string | null }
export interface Warning { type: "number" | "terminology" | "name" | "consistency" | "format" | "readiness"; severity: "info" | "warning"; message: string; span?: unknown }
export interface TMMatch { source_text: string; target_text: string; match_percent: number; tm_id: string }
export interface Term { source_term: string; target_term: string; usage_note: string | null; forbidden: string[] }
export interface UserRef { id: string; display_name: string }
export interface Approval { approver: UserRef; decision: "approved" | "rejected"; comment: string | null; created_at: string }
export interface Version {
  version_id: string; version_number: number; target_text: string; origin: "ai" | "human"; created_by: UserRef; created_at: string;
  parent_version_id: string | null; change_note: string | null; approval_state: "unapproved" | "approved" | "rejected"; approval: Approval | null;
}
export interface TranslateResponse {
  translation_id: string; version_id: string; status: "draft"; source_language: string; target_language: string; source_text: string;
  translated_text: string; review_required: boolean; review_note: string | null; warnings: Warning[]; tm_matches: TMMatch[]; terminology: Term[]; message: string;
}
export interface Translation {
  translation_id: string; project_id: string; source_language: string; target_language: string; source_text: string; context: string | null;
  status: string; versions: Version[]; current_version_id: string | null;
}
export interface JobProgress { total: number; done: number; approved: number }
export interface JobSegment { segment_id: string; sequence: number; source_text: string; status: SegmentStatus; current_version: Version | null; warnings: Warning[] }
export interface Job { job_id: string; project_id: string; title: string | null; source_language: string; target_language: string; status: JobStatus; progress: JobProgress; segments: JobSegment[] }
export interface JobSummary { job_id: string; title: string | null; source_language: string; target_language: string; status: JobStatus; progress: JobProgress; created_at: string }
export interface TMResult { tm_id: string; source_text: string; target_text: string; match_percent: number; match_type: "exact" | "fuzzy"; approved_at: string; provenance: Record<string, string> }
export interface TermResult { term_id: string; source_term: string; target_term: string; definition: string | null; domain: string | null; part_of_speech: string | null; usage_note: string | null; forbidden: string[]; status: string }
export interface SourceRef { title: string; category: string; version: number | null }

export interface RhapsodyMaster { id: string; version_number: number; segment_count: number; section_count: number; activated_at: string | null;
  validation: { blocking_errors?: string[]; warnings?: string[]; articles?: number; expected_articles?: number; missing_days?: number[]; locked_segments?: number } }
export interface RhapsodySource { id: string; filename: string; format: string; byte_size: number; created_at: string }
export interface RhapsodyEdition { id: string; title: string; month: number; year: number; status: string; active_master_version_id: string | null; sources: RhapsodySource[]; master_versions: RhapsodyMaster[] }
export interface RhapsodyAssignmentRow { id: string; master_version_id: string; target_language: string; translator_id: string; reviewer_id: string | null; due_at: string | null; status: string;
  edition_title: string; draft_status: string; draft_total: number; draft_done: number }
export interface RhapsodySection { id: string; stable_key: string; type: string; title: string; sequence: number; day_number: number | null; formatting: Record<string, unknown> | null }
export interface RhapsodySegmentOut { id: string; stable_key: string; section_id: string; source_text: string; sequence: number; metadata: Record<string, unknown> | null;
  translation_status: string; current_version_id: string | null; version_number: number | null; target_text: string; origin: string | null; draft_source: string | null;
  glossary: { source?: string; target?: string }[]; warnings: string[] }
export interface RhapsodyComment { id: string; segment_id: string | null; author: string; body: string; resolved: boolean; created_at: string }
export interface RhapsodyDraftState { status: string; total: number; done: number; note: string | null }
export interface RhapsodyAssignmentDetail { id: string; edition: { id: string; title: string; month: number; year: number }; master_version_id: string; target_language: string; status: string;
  can_edit: boolean; translator: string | null; draft: RhapsodyDraftState; sections: RhapsodySection[]; segments: RhapsodySegmentOut[]; comments: RhapsodyComment[] }
export interface RhapsodyMasterPreview { id: string; version_number: number; validation: RhapsodyMaster["validation"]; sections: RhapsodySection[];
  segments: { id: string; stable_key: string; section_id: string; source_text: string; sequence: number; metadata: Record<string, unknown> | null }[] }
export interface RhapsodySaveResult { segment_id: string; version_id: string; version_number: number; target_text: string; status: string; origin?: string; warnings?: string[] }

export interface ChatActionOut { type: "open_in_workspace" | "open_rhapsody" | "open_page"; translation_id?: string | null; path?: string | null; label?: string | null }
export interface ChatResponse {
  conversation_id: string; reply: string; translation: TranslateResponse | null;
  clarification: { question: string; field: string } | null; actions: ChatActionOut[];
  sources?: SourceRef[]; message_id?: string | null; title?: string | null;
}
export interface ChatMessageOut {
  id: string; seq: number; role: "user" | "assistant"; content: string; kind: string; created_at: string;
  translation: TranslateResponse | null; clarification: { question: string; field: string } | null;
  actions: ChatActionOut[]; sources: SourceRef[];
}
export interface ConversationSummary {
  id: string; project_id: string | null; project_name: string | null; title: string; status: string; created_at: string; updated_at: string;
  last_message_at: string | null; message_count: number; preview: string | null;
}
export interface ConversationDetail extends ConversationSummary { messages: ChatMessageOut[]; has_more_before: boolean; starters: string[] }
export type Availability = "enabled" | "enabled_with_review" | "controlled_testing" | "not_enabled";
export type ReviewContentType = "general" | "scripture" | "ministry" | "terminology" | "other";
export type ReviewSeverity = "none" | "minor" | "major" | "critical";
export interface ReviewSample { content_type: ReviewContentType; text: string }
export interface ReviewDraft { version_id: string; source_text: string; draft_text: string }
export interface ReviewSubmit {
  source_code: string; target_code: string; source_text: string; draft_text: string; version_id?: string;
  content_type: ReviewContentType; adequacy: number; fluency: number; severity: ReviewSeverity; comment?: string;
}
export interface ReviewMine { id: string; source_code: string; target_code: string; content_type: ReviewContentType; adequacy: number; fluency: number; severity: ReviewSeverity; comment: string | null }
export interface EvidenceCriterion { key: string; label: string; value: number | null; required: string; met: boolean }
export interface EvidenceSummary {
  segments: number; reviewers: number; reviewers_total: number; content_types: number; mean_adequacy: number | null; mean_fluency: number | null;
  critical_errors: number; major_rate: number | null; reviewer_spread: number | null; days: number;
}
export interface EvidenceReadiness { ready_for: "assisted" | "production" | null; next_tier: string | null; criteria: EvidenceCriterion[] }
export interface EvidenceItem {
  source_code: string; target_code: string; source_name: string; target_name: string; tier: Tier; technical_status: string;
  validation_status: string; summary: EvidenceSummary; readiness: EvidenceReadiness;
}
export interface EvidenceReview {
  id: string; reviewer: string; source_text: string; draft_text: string; content_type: ReviewContentType; adequacy: number; fluency: number;
  severity: ReviewSeverity; comment: string | null; created_at: string;
}
export interface EvidenceDetail extends EvidenceItem { reviews: EvidenceReview[] }
export interface LanguageSupport { code: string; name: string; native_name: string | null; script: string | null; tier: Tier; availability: Availability; reviewed: boolean }
export interface AdminDirection extends Direction {
  technical_status: "untested" | "passed" | "degraded" | "failed"; technical_checked_at: string | null; technical_detail: Record<string, unknown> | null;
  validation_status: "pending" | "in_review" | "validated" | "rejected";
}
export interface KnowledgeVersion { id: string; version_number: number; filename: string | null; note: string | null; created_at: string; approved_at: string | null; is_active: boolean; preview: string | null; text: string | null }
export interface KnowledgeDoc {
  id: string; title: string; category: string; status: string; languages: string[]; audience_roles: string[]; project_id: string | null; project_name: string | null;
  system_managed: boolean; version_count: number; chunk_count: number; approved_version: number | null; updated_at: string;
}
export interface KnowledgeDetail extends KnowledgeDoc { versions: KnowledgeVersion[] }
export interface AdminUser extends User { engine_details_granted: boolean; created_at: string; generated_password?: string | null }
export interface AdminProject {
  id: string; name: string; client: string | null; domain: string | null; style: string | null; instructions: string | null; status: string;
  retention_days: number | null; allow_external_processing: boolean; pilot_opt_in: boolean; monthly_char_quota: number | null;
  monthly_spend_limit: number | null; spend_alert_pct: number;
}
export interface Member { user_id: string; email: string; display_name: string; role: string; can_approve: boolean }
export interface AdminTerm extends TermResult { project_id: string | null; scope: string; source_language: string; target_language: string }
export interface AuditEvent { id: string; actor_id: string | null; actor_role: string | null; project_id: string | null; action: string; object_type: string | null; object_id: string | null; outcome: string; request_id: string | null; created_at: string; details: Record<string, unknown> | null }

export type GlossaryKind = "word" | "expression" | "sentence";
export interface GlossaryEntry { id: string; language: string; source_text: string; target_text: string; kind: GlossaryKind; notes: string | null; updated_at: string; updated_by: string | null }
export interface GlossaryLanguage { code: string; name: string; native_name: string | null; entries: number; can_manage: boolean; leaders: string[] }
export interface GlossaryOverview {
  total_entries: number; languages_with_entries: number; managed_languages: number; can_manage_any: boolean; is_admin: boolean;
  languages: GlossaryLanguage[]; recent: GlossaryEntry[];
}
export interface GlossaryLead { user_id: string; display_name: string; email: string; languages: string[] }
export interface GlossaryImportResult { added: number; updated: number; skipped: number; errors: string[] }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public fields?: { field: string; message: string }[]) {
    super(message);
    this.name = "ApiError";
  }
}

const GENERIC = "Something went wrong. Please try again shortly.";
let csrfToken = "";

export function setCsrf(token: string): void { csrfToken = token; }
export function getCsrf(): string { return csrfToken; }

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
const AUTH_PATHS = ["/v1/auth/login", "/v1/auth/me"];

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const form = typeof FormData !== "undefined" && body instanceof FormData;
  if (body !== undefined && !form) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  let res: Response;
  try {
    res = await fetch(path, { method, headers, credentials: "same-origin", body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network_error", "I couldn't reach the service. Please check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  if (res.ok) return (await res.json()) as T;
  let code = "error";
  let message = GENERIC;
  let fields: { field: string; message: string }[] | undefined;
  try {
    const data = (await res.json()) as { detail?: { code?: string; message?: string; fields?: { field: string; message: string }[] } };
    code = data.detail?.code ?? code;
    message = data.detail?.message ?? message;
    fields = data.detail?.fields;
  } catch { /* non-JSON error body: keep generic message */ }
  if (res.status === 401 && !AUTH_PATHS.includes(path) && typeof window !== "undefined") {
    window.location.assign("/login");
  }
  throw new ApiError(res.status, code, message, fields);
}

const qs = (params: Record<string, string | number | undefined>): string => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const api = {
  register: (email: string, display_name: string, password: string, expertise_language: string) => request<{ email: string; message: string }>("POST", "/v1/auth/register", { email, display_name, password, expertise_language }),
  registrationLanguages: () => request<RegistrationLanguage[]>("GET", "/v1/auth/languages"),
  setExpertise: (expertise_language: string) => request<User>("PUT", "/v1/auth/expertise", { expertise_language }),
  verifyEmail: (email: string, code: string) => request<{ message: string }>("POST", "/v1/auth/verify-email", { email, code }),
  resendVerification: (email: string) => request<{ message: string }>("POST", "/v1/auth/resend-verification", { email }),
  recoverRegistration: (token: string) => request<{ email: string; message: string }>("POST", "/v1/auth/registration/recovery-link", { token }),
  requestPasswordReset: (email: string) => request<{ message: string }>("POST", "/v1/auth/password-reset/request", { email }),
  confirmPasswordReset: (email: string, code: string, new_password: string) => request<{ message: string }>("POST", "/v1/auth/password-reset/confirm", { email, code, new_password }),
  login: async (email: string, password: string): Promise<Session> => {
    const s = await request<Session>("POST", "/v1/auth/login", { email, password });
    setCsrf(s.csrf_token);
    return s;
  },
  me: async (): Promise<Session> => {
    const s = await request<Session>("GET", "/v1/auth/me");
    setCsrf(s.csrf_token);
    return s;
  },
  logout: () => request<{ ok: boolean }>("POST", "/v1/auth/logout", {}),
  projects: () => request<ProjectListItem[]>("GET", "/v1/projects"),
  project: (id: string) => request<ProjectDetail>("GET", `/v1/projects/${id}`),
  languages: () => request<Language[]>("GET", "/v1/languages"),
  translate: (b: { project_id: string; source_language: string; target_language: string; text: string; context?: string }) =>
    request<TranslateResponse>("POST", "/v1/translate", b),
  chat: (b: { project_id: string; message: string; conversation_id?: string }) => request<ChatResponse>("POST", "/v1/chat", b),
  rhapsody: {
    editions: () => request<RhapsodyEdition[]>("GET", "/v1/rhapsody/editions"),
    edition: (id: string) => request<RhapsodyEdition>("GET", `/v1/rhapsody/editions/${id}`),
    deleteEdition: (id: string) => request<void>("DELETE", `/v1/rhapsody/editions/${id}`),
    createEdition: (month: number, year: number) => request<RhapsodyEdition>("POST", "/v1/rhapsody/editions", { month, year }),
    chatAttachment: (f: FormData) => request<RhapsodySource & { edition_id: string; edition_title: string }>("POST", "/v1/rhapsody/chat-attachment", f),
    upload: (id: string, f: FormData) => request<RhapsodySource>("POST", `/v1/rhapsody/editions/${id}/sources`, f),
    ingest: (id: string, f: FormData) => request<{ master_version_id?: string }>("POST", `/v1/rhapsody/editions/${id}/ingest`, f),
    master: (id: string, mv: string) => request<RhapsodyMasterPreview>("GET", `/v1/rhapsody/editions/${id}/masters/${mv}`),
    activate: (id: string, mv: string) => request<{ status: string }>("POST", `/v1/rhapsody/editions/${id}/activate?master_version_id=${mv}`),
    start: (id: string, language: string) => request<RhapsodyAssignmentRow & { created: boolean }>("POST", `/v1/rhapsody/editions/${id}/start`, { language, draft: true }),
    assignments: () => request<RhapsodyAssignmentRow[]>("GET", "/v1/rhapsody/assignments"),
    assignment: (id: string) => request<RhapsodyAssignmentDetail>("GET", `/v1/rhapsody/assignments/${id}`),
    save: (a: string, seg: string, target_text: string, expected_version_id?: string | null) =>
      request<RhapsodySaveResult>("PUT", `/v1/rhapsody/assignments/${a}/segments/${seg}`, { target_text, expected_version_id: expected_version_id ?? undefined }),
    redraft: (a: string, seg: string, target_text: string, expected_version_id?: string | null) =>
      request<RhapsodySaveResult>("POST", `/v1/rhapsody/assignments/${a}/segments/${seg}/redraft`, { target_text, expected_version_id: expected_version_id ?? undefined }),
    draftAll: (a: string) => request<{ started: boolean; draft: RhapsodyDraftState }>("POST", `/v1/rhapsody/assignments/${a}/draft`),
    progress: (a: string) => request<{ status: string; draft: RhapsodyDraftState }>("GET", `/v1/rhapsody/assignments/${a}/progress`),
    comment: (a: string, body: string, segment_id?: string) => request<RhapsodyComment>("POST", `/v1/rhapsody/assignments/${a}/comments`, { body, segment_id }),
    submit: (a: string) => request<{ status: string }>("POST", `/v1/rhapsody/assignments/${a}/submit`),
    review: (a: string, decision: "approved" | "changes_requested", note?: string) => request<{ status: string }>("POST", `/v1/rhapsody/assignments/${a}/review`, { decision, note }),
    exportUrl: (a: string) => `/v1/rhapsody/assignments/${a}/export.docx`,
    layoutUrl: (a: string) => `/v1/rhapsody/assignments/${a}/layout.pdf`,
    masterLayoutUrl: (id: string, mv: string) => `/v1/rhapsody/editions/${id}/masters/${mv}/layout.pdf`,
  },
  publishing: {
    fonts: () => request<PublishingFont[]>("GET", "/v1/rhapsody/publishing/fonts"),
    uploadFont: (f: FormData) => request<PublishingFont>("POST", "/v1/rhapsody/publishing/fonts", f),
    deleteFont: (id: string) => request<void>("DELETE", `/v1/rhapsody/publishing/fonts/${id}`),
    profiles: () => request<PublishingProfile[]>("GET", "/v1/rhapsody/publishing/profiles"),
    saveProfile: (code: string, b: { direction: "ltr" | "rtl"; locale: string; fonts: Record<string, string> }) => request<PublishingProfile>("PUT", `/v1/rhapsody/publishing/profiles/${code}`, b),
    validate: (code: string) => request<{ status: string; checks: { severity: string; message: string }[] }>("POST", `/v1/rhapsody/publishing/profiles/${code}/validate`),
    activate: (code: string) => request<{ status: string }>("POST", `/v1/rhapsody/publishing/profiles/${code}/activate`),
  },
  glossary: {
    overview: () => request<GlossaryOverview>("GET", "/v1/glossary/overview"),
    entries: (lang: string, p: { q?: string; kind?: string; limit?: number; offset?: number } = {}) =>
      request<{ total: number; items: GlossaryEntry[] }>("GET", `/v1/glossary/${lang}/entries${qs(p)}`),
    create: (lang: string, b: { source_text: string; target_text: string; kind?: GlossaryKind; notes?: string }) => request<GlossaryEntry>("POST", `/v1/glossary/${lang}/entries`, b),
    update: (lang: string, id: string, b: Partial<{ source_text: string; target_text: string; kind: GlossaryKind; notes: string }>) => request<GlossaryEntry>("PATCH", `/v1/glossary/${lang}/entries/${id}`, b),
    remove: (lang: string, id: string) => request<void>("DELETE", `/v1/glossary/${lang}/entries/${id}`),
    import: (lang: string, f: FormData) => request<GlossaryImportResult>("POST", `/v1/glossary/${lang}/import`, f),
    exportUrl: (lang: string) => `/v1/glossary/${lang}/export`,
    leads: () => request<GlossaryLead[]>("GET", "/v1/glossary/leads"),
    setLeads: (userId: string, languages: string[]) => request<GlossaryLead>("PUT", `/v1/glossary/leads/${userId}`, { languages }),
  },
  languageSupport: () => request<LanguageSupport[]>("GET", "/v1/language-support"),
  reviews: {
    samples: () => request<ReviewSample[]>("GET", "/v1/reviews/samples"),
    draft: (b: { project_id: string; source_code: string; target_code: string; text: string }) => request<ReviewDraft>("POST", "/v1/reviews/draft", b),
    submit: (b: ReviewSubmit) => request<ReviewMine>("POST", "/v1/reviews", b),
    mine: (source_code: string, target_code: string) => request<ReviewMine[]>("GET", `/v1/reviews/mine${qs({ source_code, target_code })}`),
  },
  conversations: {
    list: (p: { q?: string; status?: "active" | "archived"; project_id?: string; scope?: "general"; limit?: number } = {}) => request<ConversationSummary[]>("GET", `/v1/conversations${qs(p)}`),
    create: (project_id?: string) => request<ConversationDetail>("POST", "/v1/conversations", project_id ? { project_id } : {}),
    get: (id: string) => request<ConversationDetail>("GET", `/v1/conversations/${id}`),
    older: (id: string, before_seq: number) => request<{ messages: ChatMessageOut[]; has_more_before: boolean }>("GET", `/v1/conversations/${id}/messages${qs({ before_seq })}`),
    send: (id: string, b: { message: string; context_translation_id?: string }) => request<ChatResponse>("POST", `/v1/conversations/${id}/messages`, b),
    patch: (id: string, b: { title?: string; status?: "active" | "archived" }) => request<ConversationSummary>("PATCH", `/v1/conversations/${id}`, b),
    remove: (id: string) => request<void>("DELETE", `/v1/conversations/${id}`),
  },
  translation: (id: string) => request<Translation>("GET", `/v1/translations/${id}`),
  saveVersion: (id: string, b: { target_text: string; parent_version_id: string; change_note?: string }) =>
    request<{ version: Version; warnings: Warning[] }>("POST", `/v1/translations/${id}/versions`, b),
  decide: (versionId: string, decision: "approved" | "rejected", comment?: string) =>
    request<{ version: Version; message: string }>("POST", `/v1/versions/${versionId}/approve`, { decision, comment }),
  createJob: (b: { project_id: string; source_language: string; target_language: string; title?: string; text: string }) =>
    request<{ job_id: string; status: JobStatus; segment_count: number }>("POST", "/v1/translation-jobs", b),
  jobs: (projectId: string) => request<JobSummary[]>("GET", `/v1/translation-jobs${qs({ project_id: projectId })}`),
  job: (id: string) => request<Job>("GET", `/v1/translation-jobs/${id}`),
  tmSearch: (p: { project_id: string; source_language: string; target_language: string; q: string }) =>
    request<{ results: TMResult[] }>("GET", `/v1/tm/search${qs(p)}`),
  termSearch: (p: { project_id: string; source_language: string; target_language: string; q?: string }) =>
    request<{ results: TermResult[] }>("GET", `/v1/terminology/search${qs(p)}`),
  qaCheck: (b: { project_id: string; source_text: string; target_text: string; source_language: string; target_language: string }) =>
    request<{ warnings: Warning[] }>("POST", "/v1/qa/check", b),
  admin: {
    users: () => request<AdminUser[]>("GET", "/v1/admin/users"),
    createUser: (b: { email: string; display_name: string; role: Role; password?: string }) => request<AdminUser>("POST", "/v1/admin/users", b),
    patchUser: (id: string, b: Partial<{ role: Role; status: "active" | "disabled"; display_name: string }>) => request<AdminUser>("PATCH", `/v1/admin/users/${id}`, b),
    projects: () => request<AdminProject[]>("GET", "/v1/admin/projects"),
    createProject: (b: Partial<AdminProject> & { name: string }) => request<AdminProject>("POST", "/v1/admin/projects", b),
    patchProject: (id: string, b: Partial<AdminProject>) => request<AdminProject>("PATCH", `/v1/admin/projects/${id}`, b),
    members: (id: string) => request<Member[]>("GET", `/v1/admin/projects/${id}/members`),
    putMembers: (id: string, members: { user_id: string; role: string; can_approve?: boolean }[]) => request<Member[]>("PUT", `/v1/admin/projects/${id}/members`, { members }),
    terms: (projectId?: string) => request<AdminTerm[]>("GET", `/v1/admin/terminology${qs({ project_id: projectId })}`),
    createTerm: (b: { project_id?: string; scope: "project" | "global"; source_language: string; target_language: string; source_term: string; target_term: string; status?: string }) =>
      request<AdminTerm>("POST", "/v1/admin/terminology", b),
    patchTerm: (id: string, b: { status?: string; comment?: string; target_term?: string }) => request<AdminTerm>("PATCH", `/v1/admin/terminology/${id}`, b),
    directions: () => request<AdminDirection[]>("GET", "/v1/admin/language-directions"),
    setValidation: (b: { source_code: string; target_code: string; validation_status: AdminDirection["validation_status"]; note?: string }) =>
      request<AdminDirection>("PUT", "/v1/admin/language-directions/validation", b),
    testDirection: (b: { source_code: string; target_code: string; text?: string }) =>
      request<{ source_code: string; target_code: string; output: string; flag: string | null; technical_status: string }>("POST", "/v1/admin/language-directions/test", b),
    enablePilot: (codes?: string[]) => request<Record<string, unknown>>("POST", "/v1/admin/languages/enable-pilot", codes ? { codes } : {}),
    evidence: {
      list: () => request<EvidenceItem[]>("GET", "/v1/admin/language-evidence"),
      get: (src: string, tgt: string) => request<EvidenceDetail>("GET", `/v1/admin/language-evidence/${src}/${tgt}`),
      promote: (src: string, tgt: string) => request<{ tier: Tier }>("POST", `/v1/admin/language-evidence/${src}/${tgt}/promote`, {}),
    },
    knowledge: {
      list: () => request<KnowledgeDoc[]>("GET", "/v1/admin/knowledge/documents"),
      get: (id: string) => request<KnowledgeDetail>("GET", `/v1/admin/knowledge/documents/${id}`),
      create: (b: { title: string; category: string; text: string; languages?: string[]; audience_roles?: string[]; project_id?: string }) => request<KnowledgeDetail>("POST", "/v1/admin/knowledge/documents", b),
      upload: (f: FormData) => request<KnowledgeDetail>("POST", "/v1/admin/knowledge/documents/upload", f),
      addVersion: (id: string, text: string, note?: string) => request<KnowledgeDetail>("POST", `/v1/admin/knowledge/documents/${id}/versions`, { text, note }),
      approve: (id: string, versionId: string) => request<KnowledgeDetail>("POST", `/v1/admin/knowledge/documents/${id}/versions/${versionId}/approve`, {}),
      deactivate: (id: string) => request<KnowledgeDetail>("POST", `/v1/admin/knowledge/documents/${id}/deactivate`, {}),
      reindex: () => request<{ indexed: number }>("POST", "/v1/admin/knowledge/reindex", {}),
    },
    putDirections: (directions: { source_code: string; target_code: string; readiness_tier: Tier; review_note?: string }[]) =>
      request<Direction[]>("PUT", "/v1/admin/language-directions", { directions }),
    audit: (p: { action?: string; limit?: number } = {}) => request<AuditEvent[]>("GET", `/v1/admin/audit-events${qs(p)}`),
    // Protected operations: the backend returns these only to technical administrators (or explicitly granted users).
    models: () => request<Record<string, unknown>[]>("GET", "/v1/admin/models"),
    routingEvents: () => request<Record<string, unknown>[]>("GET", "/v1/admin/routing-events"),
    usage: () => request<{ since: string; rows: Record<string, unknown>[] }>("GET", "/v1/admin/usage"),
    health: () => request<Record<string, unknown>>("GET", "/v1/admin/health"),
  },
};

export interface PublishingFont { id: string; family: string; style: string; format: string; license_name: string; byte_size: number }
export interface PublishingProfile { id: string | null; language_code: string; language_name: string; direction: "ltr" | "rtl"; locale: string; status: string; fonts: Record<string, PublishingFont> }
