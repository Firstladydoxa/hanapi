"""PUBLIC pydantic schemas (translator-facing whitelist).

Nothing here may carry provider/model/routing information. Do not import
`internal_schemas` from this module.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_serializer

LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]{2,8})?$")


def _norm_lang(v: str) -> str:
    v = (v or "").strip().lower().replace("_", "-")
    if not LANG_RE.match(v):
        raise ValueError("invalid language code")
    return v


LangCode = Annotated[str, StringConstraints(max_length=16)]
Tier = Literal["production", "assisted", "experimental", "unsupported"]
MemberRole = Literal["translator", "reviewer", "project_manager"]
UserRole = Literal["translator", "reviewer", "project_manager", "team_leader", "tni_admin", "technical_admin", "auditor"]


class Public(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Req(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


# ---------------------------------------------------------------- auth
class LoginRequest(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class RegisterRequest(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    password: Annotated[str, StringConstraints(min_length=12, max_length=1024)]
    expertise_language: Annotated[str, StringConstraints(min_length=2, max_length=16)]


class ExpertiseRequest(Req):
    expertise_language: Annotated[str, StringConstraints(min_length=2, max_length=16)]


class EmailOnlyRequest(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]


class EmailCodeRequest(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    code: Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class PasswordResetComplete(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    code: Annotated[str, StringConstraints(pattern=r"^\d{6}$")]
    new_password: Annotated[str, StringConstraints(min_length=12, max_length=1024)]


class RecoveryLinkRequest(Req):
    token: Annotated[str, StringConstraints(min_length=20, max_length=4096)]


class UserOut(Public):
    id: str
    email: str
    display_name: str
    role: str
    status: str
    expertise_language: Optional[str] = None
    expertise_language_name: Optional[str] = None


class SessionOut(Public):
    user: UserOut
    csrf_token: str


class OkOut(Public):
    ok: bool = True


# ---------------------------------------------------------------- projects / languages
class LanguageOut(Public):
    code: str
    display_name: str
    script: Optional[str] = None
    native_name: Optional[str] = None


class LanguageSupportOut(Public):
    code: str
    name: str
    native_name: Optional[str] = None
    script: Optional[str] = None
    tier: Tier
    availability: Literal["enabled", "enabled_with_review", "controlled_testing", "not_enabled"]
    reviewed: bool = False


class DirectionOut(Public):
    source_code: str
    target_code: str
    readiness_tier: Tier
    review_note: Optional[str] = None


class ProjectListItem(Public):
    id: str
    name: str
    domain: Optional[str] = None
    style: Optional[str] = None
    member_role: str


class ProjectDetail(ProjectListItem):
    instructions: Optional[str] = None
    can_approve: bool
    language_directions: List[DirectionOut]


# ---------------------------------------------------------------- warnings / knowledge
class WarningOut(Public):
    type: Literal["number", "terminology", "name", "consistency", "format", "readiness"]
    severity: Literal["info", "warning"]
    message: str
    span: Optional[Any] = None


class TMMatchOut(Public):
    source_text: str
    target_text: str
    match_percent: int
    tm_id: str


class TermOut(Public):
    source_term: str
    target_term: str
    usage_note: Optional[str] = None
    forbidden: List[str] = []


class UserRef(Public):
    id: str
    display_name: str


class ApprovalOut(Public):
    approver: UserRef
    decision: Literal["approved", "rejected"]
    comment: Optional[str] = None
    created_at: datetime


class VersionOut(Public):
    version_id: str
    version_number: int
    target_text: str
    origin: Literal["ai", "human"]
    created_by: UserRef
    created_at: datetime
    parent_version_id: Optional[str] = None
    change_note: Optional[str] = None
    approval_state: Literal["unapproved", "approved", "rejected"]
    approval: Optional[ApprovalOut] = None


# ---------------------------------------------------------------- translate
class TranslateRequest(Req):
    project_id: str = Field(max_length=64)
    source_language: LangCode
    target_language: LangCode
    text: str = Field(min_length=1, max_length=200_000)
    context: Optional[str] = Field(default=None, max_length=50_000)
    domain: Optional[str] = Field(default=None, max_length=100)

    @field_validator("source_language", "target_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class TranslateResponse(Public):
    translation_id: str
    version_id: str
    status: Literal["draft"] = "draft"
    source_language: str
    target_language: str
    source_text: str
    translated_text: str
    review_required: bool = True
    review_note: Optional[str] = None
    warnings: List[WarningOut] = []
    tm_matches: List[TMMatchOut] = []
    terminology: List[TermOut] = []
    message: str


# ---------------------------------------------------------------- translations / versions
class TranslationOut(Public):
    translation_id: str
    project_id: str
    source_language: str
    target_language: str
    source_text: str
    context: Optional[str] = None
    status: str
    versions: List[VersionOut]
    current_version_id: Optional[str] = None


class TranslationListItem(Public):
    translation_id: str
    source_text: str
    target_language: str
    status: str
    updated_at: datetime


class NewVersionRequest(Req):
    target_text: str = Field(min_length=1, max_length=200_000)
    parent_version_id: str = Field(max_length=64)
    change_note: Optional[str] = Field(default=None, max_length=1000)


class NewVersionResponse(Public):
    version: VersionOut
    warnings: List[WarningOut] = []


class ApproveRequest(Req):
    decision: Literal["approved", "rejected"]
    comment: Optional[str] = Field(default=None, max_length=2000)


class ApproveResponse(Public):
    version: VersionOut
    message: str


class CompareOut(Public):
    translation_id: str
    a_version_id: str
    b_version_id: str
    similarity_percent: int
    changes: List[Dict[str, str]]


# ---------------------------------------------------------------- jobs
class JobRequest(Req):
    project_id: str = Field(max_length=64)
    source_language: LangCode
    target_language: LangCode
    title: Optional[str] = Field(default=None, max_length=300)
    text: Optional[str] = Field(default=None, max_length=1_000_000)
    segments: Optional[List[Annotated[str, StringConstraints(max_length=20_000)]]] = Field(default=None, max_length=2000)
    options: Optional[Dict[str, Any]] = None

    @field_validator("source_language", "target_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class JobCreated(Public):
    job_id: str
    status: str
    segment_count: int


class JobProgress(Public):
    total: int
    done: int
    approved: int


class JobSegmentOut(Public):
    segment_id: str
    sequence: int
    source_text: str
    status: str
    current_version: Optional[VersionOut] = None
    warnings: List[WarningOut] = []


class JobOut(Public):
    job_id: str
    project_id: str
    title: Optional[str] = None
    source_language: str
    target_language: str
    status: str
    progress: JobProgress
    segments: List[JobSegmentOut]


class JobSummary(Public):
    job_id: str
    title: Optional[str] = None
    source_language: str
    target_language: str
    status: str
    progress: JobProgress
    created_at: datetime


# ---------------------------------------------------------------- knowledge
class TMResult(Public):
    tm_id: str
    source_text: str
    target_text: str
    match_percent: int
    match_type: Literal["exact", "fuzzy"]
    approved_at: datetime
    provenance: Dict[str, str]


class TMSearchOut(Public):
    results: List[TMResult]


class TermResult(Public):
    term_id: str
    source_term: str
    target_term: str
    definition: Optional[str] = None
    domain: Optional[str] = None
    part_of_speech: Optional[str] = None
    usage_note: Optional[str] = None
    forbidden: List[str] = []
    status: str


class TermSearchOut(Public):
    results: List[TermResult]


class QARequest(Req):
    project_id: str = Field(max_length=64)
    source_text: str = Field(min_length=1, max_length=200_000)
    target_text: str = Field(max_length=200_000)
    source_language: LangCode
    target_language: LangCode

    @field_validator("source_language", "target_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class QAOut(Public):
    warnings: List[WarningOut]


# ---------------------------------------------------------------- chat
class ChatRequest(Req):
    project_id: str = Field(max_length=64)
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: Optional[str] = Field(default=None, max_length=64)
    source_language: Optional[LangCode] = None
    target_language: Optional[LangCode] = None
    # Optional: the ONE translation/segment the translator is asking about. Only this item is shared with HAN as context.
    context_translation_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("source_language", "target_language")
    @classmethod
    def _lang(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _norm_lang(v)


class Clarification(Public):
    question: str
    field: str


class SourceRef(Public):
    """A TNI knowledge source an answer was grounded in (visible only to users authorised for that document)."""

    title: str
    category: str
    version: int


class ChatAction(Public):
    type: Literal["open_in_workspace", "open_rhapsody"]
    translation_id: Optional[str] = None
    path: Optional[str] = None
    label: Optional[str] = None

    @model_serializer(mode="wrap")
    def _drop_empty(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class ChatResponse(Public):
    conversation_id: str
    reply: str
    translation: Optional[TranslateResponse] = None
    clarification: Optional[Clarification] = None
    actions: List[ChatAction] = []
    # additive fields (older clients ignore them)
    sources: List[SourceRef] = []
    message_id: Optional[str] = None
    title: Optional[str] = None


# ---------------------------------------------------------------- persistent conversations
ConversationStatus = Literal["active", "archived"]


class ConversationCreate(Req):
    project_id: Optional[str] = Field(default=None, max_length=64)
    title: Optional[str] = Field(default=None, max_length=200)


class ConversationPatch(Req):
    title: Optional[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = None
    status: Optional[ConversationStatus] = None


class MessageIn(Req):
    message: str = Field(min_length=1, max_length=20_000)
    source_language: Optional[LangCode] = None
    target_language: Optional[LangCode] = None
    context_translation_id: Optional[str] = Field(default=None, max_length=64)


class MessageOut(Public):
    id: str
    seq: int
    role: Literal["user", "assistant"]
    content: str
    kind: str = "text"  # greeting | text | translation | clarification | answer
    created_at: datetime
    translation: Optional[TranslateResponse] = None
    clarification: Optional[Clarification] = None
    actions: List[ChatAction] = []
    sources: List[SourceRef] = []


class ConversationOut(Public):
    id: str
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime] = None
    message_count: int = 0
    preview: Optional[str] = None


class ConversationDetail(ConversationOut):
    messages: List[MessageOut]
    has_more_before: bool = False
    starters: List[str] = []


class MessagesPage(Public):
    messages: List[MessageOut]
    has_more_before: bool


# ---------------------------------------------------------------- admin (non-engine)
class AdminUserCreate(Req):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    role: UserRole
    password: Optional[Annotated[str, StringConstraints(min_length=12, max_length=1024)]] = None
    engine_details_granted: bool = False


class AdminUserPatch(Req):
    display_name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = None
    role: Optional[UserRole] = None
    status: Optional[Literal["active", "disabled"]] = None
    password: Optional[Annotated[str, StringConstraints(min_length=12, max_length=1024)]] = None
    engine_details_granted: Optional[bool] = None


class AdminUserOut(Public):
    id: str
    email: str
    display_name: str
    role: str
    status: str
    engine_details_granted: bool
    created_at: datetime
    generated_password: Optional[str] = None


class AdminProjectIn(Req):
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    client: Optional[str] = Field(default=None, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=100)
    style: Optional[str] = Field(default=None, max_length=100)
    instructions: Optional[str] = Field(default=None, max_length=20_000)
    retention_days: Optional[int] = Field(default=None, ge=1, le=36500)
    allow_external_processing: bool = False
    pilot_opt_in: bool = False
    monthly_char_quota: Optional[int] = Field(default=None, ge=0)
    monthly_spend_limit: Optional[float] = Field(default=None, ge=0)
    spend_alert_pct: int = Field(default=80, ge=1, le=100)
    directions: Optional[List[Dict[str, str]]] = None


class AdminProjectPatch(Req):
    name: Optional[Annotated[str, StringConstraints(min_length=1, max_length=200)]] = None
    client: Optional[str] = Field(default=None, max_length=200)
    domain: Optional[str] = Field(default=None, max_length=100)
    style: Optional[str] = Field(default=None, max_length=100)
    instructions: Optional[str] = Field(default=None, max_length=20_000)
    status: Optional[Literal["active", "archived"]] = None
    retention_days: Optional[int] = Field(default=None, ge=1, le=36500)
    allow_external_processing: Optional[bool] = None
    pilot_opt_in: Optional[bool] = None
    monthly_char_quota: Optional[int] = Field(default=None, ge=0)
    monthly_spend_limit: Optional[float] = Field(default=None, ge=0)
    spend_alert_pct: Optional[int] = Field(default=None, ge=1, le=100)
    directions: Optional[List[Dict[str, str]]] = None


class AdminProjectOut(Public):
    id: str
    name: str
    client: Optional[str] = None
    domain: Optional[str] = None
    style: Optional[str] = None
    instructions: Optional[str] = None
    status: str
    retention_days: Optional[int] = None
    allow_external_processing: bool
    pilot_opt_in: bool
    monthly_char_quota: Optional[int] = None
    monthly_spend_limit: Optional[float] = None
    spend_alert_pct: int


class MemberIn(Req):
    user_id: str = Field(max_length=64)
    role: MemberRole
    can_approve: Optional[bool] = None


class MemberOut(Public):
    user_id: str
    email: str
    display_name: str
    role: str
    can_approve: bool


class MembersPut(Req):
    members: List[MemberIn] = Field(max_length=500)


class TermIn(Req):
    project_id: Optional[str] = Field(default=None, max_length=64)
    scope: Literal["project", "global"] = "project"
    source_language: LangCode
    target_language: LangCode
    source_term: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    target_term: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    definition: Optional[str] = Field(default=None, max_length=5000)
    domain: Optional[str] = Field(default=None, max_length=100)
    part_of_speech: Optional[str] = Field(default=None, max_length=50)
    usage_note: Optional[str] = Field(default=None, max_length=2000)
    forbidden: List[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=50)
    status: Literal["approved", "draft", "deprecated"] = "draft"

    @field_validator("source_language", "target_language")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class TermPatch(Req):
    target_term: Optional[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = None
    definition: Optional[str] = Field(default=None, max_length=5000)
    domain: Optional[str] = Field(default=None, max_length=100)
    part_of_speech: Optional[str] = Field(default=None, max_length=50)
    usage_note: Optional[str] = Field(default=None, max_length=2000)
    forbidden: Optional[List[Annotated[str, StringConstraints(min_length=1, max_length=300)]]] = Field(default=None, max_length=50)
    status: Optional[Literal["approved", "draft", "deprecated"]] = None
    comment: Optional[str] = Field(default=None, max_length=1000)


class AdminTermOut(TermResult):
    project_id: Optional[str] = None
    scope: str
    source_language: str
    target_language: str


class DirectionPut(Req):
    source_code: LangCode
    target_code: LangCode
    readiness_tier: Tier
    review_note: Optional[str] = Field(default=None, max_length=2000)
    benchmark_ref: Optional[str] = Field(default=None, max_length=200)

    @field_validator("source_code", "target_code")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class DirectionsPut(Req):
    directions: List[DirectionPut] = Field(max_length=2000)


class LanguagePut(Req):
    code: LangCode
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    script: Optional[str] = Field(default=None, max_length=32)
    region: Optional[str] = Field(default=None, max_length=64)
    active: bool = True

    @field_validator("code")
    @classmethod
    def _lang(cls, v: str) -> str:
        return _norm_lang(v)


class AuditEventOut(Public):
    id: str
    actor_id: Optional[str] = None
    actor_role: Optional[str] = None
    project_id: Optional[str] = None
    action: str
    object_type: Optional[str] = None
    object_id: Optional[str] = None
    outcome: str
    request_id: Optional[str] = None
    created_at: datetime
    details: Optional[Dict[str, Any]] = None


class ErrorBody(BaseModel):
    code: str
    message: str


class AdminDirectionOut(DirectionOut):
    technical_status: str = "untested"
    technical_checked_at: Optional[datetime] = None
    technical_detail: Optional[Dict[str, Any]] = None
    validation_status: str = "pending"


class DirectionValidationPut(Req):
    source_code: LangCode
    target_code: LangCode
    validation_status: Literal["pending", "in_review", "validated", "rejected"]
    note: Optional[str] = Field(default=None, max_length=2000)


class PilotEnableIn(Req):
    codes: Optional[List[Annotated[str, StringConstraints(max_length=16)]]] = Field(default=None, max_length=500)


class DirectionTestIn(Req):
    source_code: LangCode
    target_code: LangCode
    text: Annotated[str, StringConstraints(min_length=1, max_length=500)] = "Good morning, everyone."


class DirectionTestOut(Public):
    source_code: str
    target_code: str
    output: str
    flag: Optional[str] = None
    technical_status: str
