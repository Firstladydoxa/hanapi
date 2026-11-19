"""SQLAlchemy tables (system of record). Internal-only tables are marked INTERNAL."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")

USER_ROLES = ("translator", "reviewer", "project_manager", "team_leader", "tni_admin", "technical_admin", "auditor")
MEMBER_ROLES = ("translator", "reviewer", "project_manager")
READINESS_TIERS = ("production", "assisted", "experimental", "unsupported")
SEGMENT_STATUSES = ("not_started", "draft", "in_review", "approved", "rejected", "needs_attention")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    engine_details_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("role in ('translator','reviewer','project_manager','team_leader','tni_admin','technical_admin','auditor')", name="ck_users_role"),
        CheckConstraint("status in ('active','disabled')", name="ck_users_status"),
    )


class UserSession(Base):
    __tablename__ = "user_sessions"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ip: Mapped[Optional[str]] = mapped_column(String(64))


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    client: Mapped[Optional[str]] = mapped_column(String(200))
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    style: Mapped[Optional[str]] = mapped_column(String(100))
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    retention_days: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # Data policy: external (third-party) providers only if true.
    allow_external_processing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Opt-in to controlled pilots: allows `experimental` readiness directions.
    pilot_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    monthly_char_quota: Mapped[Optional[int]] = mapped_column(BigInteger)
    monthly_spend_limit: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    spend_alert_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    created_at: Mapped[datetime] = _now()
    members: Mapped[List["ProjectMember"]] = relationship(back_populates="project")


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship()
    __table_args__ = (CheckConstraint("role in ('translator','reviewer','project_manager')", name="ck_member_role"),)


class Language(Base):
    __tablename__ = "languages"
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    script: Mapped[Optional[str]] = mapped_column(String(32))
    region: Mapped[Optional[str]] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    native_name: Mapped[Optional[str]] = mapped_column(String(200))
    # engine family -> that engine's own language token, e.g. {"madlad": "sw"}. Absent family = the engine does not support it.
    model_codes: Mapped[Optional[Any]] = mapped_column(JSONType)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # passed TNI language evaluation
    notes: Mapped[Optional[str]] = mapped_column(Text)


class LanguageDirection(Base):
    __tablename__ = "language_directions"
    source_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), primary_key=True)
    target_code: Mapped[str] = mapped_column(ForeignKey("languages.code"), primary_key=True)
    readiness_tier: Mapped[str] = mapped_column(String(16), nullable=False, default="unsupported")
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    benchmark_ref: Mapped[Optional[str]] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    # Stage 1 (technical verification) and Stage 2 (human validation) are recorded separately from the tier.
    technical_status: Mapped[str] = mapped_column(String(16), nullable=False, default="untested", server_default="untested")
    technical_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    technical_detail: Mapped[Optional[Any]] = mapped_column(JSONType)
    validation_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    __table_args__ = (
        CheckConstraint("readiness_tier in ('production','assisted','experimental','unsupported')", name="ck_direction_tier"),
    )


class ProjectDirection(Base):
    """Optional restriction of a project to specific directions (none = all non-unsupported)."""

    __tablename__ = "project_directions"
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_code: Mapped[str] = mapped_column(String(16), primary_key=True)


class TranslationJob(Base):
    __tablename__ = "translation_jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(300))
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    input_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    options: Mapped[Optional[Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Segment(Base):
    """A source segment; also the `translation_id` of quick translations."""

    __tablename__ = "segments"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("translation_jobs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint(
            "status in ('not_started','draft','in_review','approved','rejected','needs_attention')", name="ck_segment_status"
        ),
        Index("ix_segments_project_creator", "project_id", "created_by"),
    )


class TranslationVersion(Base):
    """IMMUTABLE (DB trigger forbids UPDATE/DELETE)."""

    __tablename__ = "translation_versions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    segment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("segments.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(8), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now()
    parent_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("translation_versions.id"))
    change_note: Mapped[Optional[str]] = mapped_column(String(1000))
    workflow: Mapped[str] = mapped_column(String(32), nullable=False, default="translate")
    __table_args__ = (
        UniqueConstraint("segment_id", "version_number", name="uq_version_number"),
        CheckConstraint("origin in ('ai','human')", name="ck_version_origin"),
    )


class Approval(Base):
    """IMMUTABLE (DB trigger forbids UPDATE/DELETE). One decision per version."""

    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("translation_versions.id"), nullable=False, unique=True)
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (CheckConstraint("decision in ('approved','rejected')", name="ck_approval_decision"),)


class TranslationMemory(Base):
    """Approved human translations only. Drafts live in translation_versions and never here."""

    __tablename__ = "translation_memory"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("translation_versions.id"), nullable=False)
    approval_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("approvals.id"), nullable=False, unique=True)
    approved_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_tm_lookup", "project_id", "source_language", "target_language", "source_hash"),)


class TerminologyEntry(Base):
    __tablename__ = "terminology_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id"), index=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="project")
    source_language: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language: Mapped[str] = mapped_column(String(16), nullable=False)
    source_term: Mapped[str] = mapped_column(String(300), nullable=False)
    target_term: Mapped[str] = mapped_column(String(300), nullable=False)
    definition: Mapped[Optional[str]] = mapped_column(Text)
    domain: Mapped[Optional[str]] = mapped_column(String(100))
    part_of_speech: Mapped[Optional[str]] = mapped_column(String(50))
    usage_note: Mapped[Optional[str]] = mapped_column(Text)
    forbidden_alternatives: Mapped[Optional[Any]] = mapped_column(JSONType)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("status in ('approved','draft','deprecated')", name="ck_term_status"),
        CheckConstraint("scope in ('project','global')", name="ck_term_scope"),
        CheckConstraint(
            "(scope = 'global' AND project_id IS NULL) OR (scope = 'project' AND project_id IS NOT NULL)",
            name="ck_term_scope_project",
        ),
    )


class TerminologyApproval(Base):
    __tablename__ = "terminology_approval_history"
    id: Mapped[uuid.UUID] = _uuid_pk()
    entry_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("terminology_entries.id"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    from_status: Mapped[Optional[str]] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(1000))
    created_at: Mapped[datetime] = _now()


class ModelRegistry(Base):
    """INTERNAL. Never serialised to translator-facing clients."""

    __tablename__ = "model_registry"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # adapter kind
    model_name: Mapped[Optional[str]] = mapped_column(String(200))
    revision: Mapped[Optional[str]] = mapped_column(String(100))
    license: Mapped[Optional[str]] = mapped_column(String(100))
    license_cleared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    license_evidence: Mapped[Optional[str]] = mapped_column(Text)
    runtime: Mapped[Optional[str]] = mapped_column(String(100))
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deployment_status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_deployed")
    languages: Mapped[Optional[Any]] = mapped_column(JSONType)  # null = no model-level restriction
    max_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    cost_per_1k_chars: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    capability: Mapped[str] = mapped_column(String(16), nullable=False, default="translation", server_default="translation")  # translation | chat | embedding
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("deployment_status in ('not_deployed','deployed','degraded','retired')", name="ck_model_deploy"),
    )


class ModelDirectionScore(Base):
    """INTERNAL. Direction-specific benchmark score in [0,1] (nullable = not evaluated)."""

    __tablename__ = "model_direction_scores"
    model_key: Mapped[str] = mapped_column(ForeignKey("model_registry.key"), primary_key=True)
    source_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    target_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    benchmark_score: Mapped[Optional[float]] = mapped_column(Float)
    notes: Mapped[Optional[str]] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RoutingEvent(Base):
    """INTERNAL. One row per provider attempt (or per failed routing decision)."""

    __tablename__ = "routing_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    segment_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    source_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_key: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success|error|timeout|no_route
    error_category: Mapped[Optional[str]] = mapped_column(String(32))
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    estimated_cost: Mapped[Optional[float]] = mapped_column(Float)
    chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route_reason: Mapped[Optional[str]] = mapped_column(Text)
    fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _now()


class UsageRecord(Base):
    """INTERNAL. Billable/quota usage per project, model and direction."""

    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(String(16), nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (Index("ix_usage_project_month", "project_id", "created_at"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(32))
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_type: Mapped[Optional[str]] = mapped_column(String(32))
    object_id: Mapped[Optional[str]] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(64))
    ip: Mapped[Optional[str]] = mapped_column(String(64))
    details: Mapped[Optional[Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ChatConversation(Base):
    """A translator's persistent HAN conversation. Owned by one user; project is optional."""

    __tablename__ = "chat_conversations"
    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")  # active | archived | deleted
    state: Mapped[Optional[Any]] = mapped_column(JSONType)  # working context: pending clarification, last language pair, ...
    summary: Mapped[Optional[str]] = mapped_column(Text)  # rolling summary of OLDER messages; never authoritative over the messages
    summary_upto: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # messages (by seq) the summary covers
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("status in ('active','archived','deleted')", name="ck_conversation_status"),)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = _uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chat_conversations.id"), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")  # strict order within the conversation
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Safe, non-sensitive metadata only: kind (greeting|translation|answer|...), translation payload (public schema), knowledge sources.
    meta: Mapped[Optional[Any]] = mapped_column("metadata", JSONType)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("conversation_id", "seq", name="uq_message_seq"),)


KNOWLEDGE_CATEGORIES = ("institutional", "guidelines", "terminology", "language_resources", "platform", "faq", "doctrine")


class KnowledgeDocument(Base):
    """A governed source of TNI knowledge. Only `approved` documents are retrievable, and only their approved version."""

    __tablename__ = "knowledge_documents"
    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    languages: Mapped[Optional[Any]] = mapped_column(JSONType)  # language codes the content applies to; empty/null = all
    audience_roles: Mapped[Optional[Any]] = mapped_column(JSONType)  # user roles allowed to receive it; empty/null = every signed-in user
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id"), index=True)  # null = organisation-wide
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")  # draft | approved | inactive
    approved_version_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    effective_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    system_managed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # shipped with HAN (platform guide)
    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint("status in ('draft','approved','inactive')", name="ck_knowledge_status"),
        CheckConstraint("category in ('institutional','guidelines','terminology','language_resources','platform','faq','doctrine')", name="ck_knowledge_category"),
    )


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[Optional[str]] = mapped_column(String(300))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(500))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_knowledge_version"),)


EMBEDDING_DIMENSIONS = 384  # multilingual-e5-small; changing the embedding model needs a migration


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_documents.id"), nullable=False, index=True)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_versions.id"), nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[Optional[str]] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[Any]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[Optional[Any]] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = _now()


class LanguageReview(Base):
    """One reviewer's scored judgement of one HAN draft in one direction (Stage-2 human evaluation evidence)."""

    __tablename__ = "language_reviews"
    id: Mapped[uuid.UUID] = _uuid_pk()
    source_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_code: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    version_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("translation_versions.id"))
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    adequacy: Mapped[int] = mapped_column(Integer, nullable=False)
    fluency: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(2000))
    created_at: Mapped[datetime] = _now()
    __table_args__ = (
        UniqueConstraint("reviewer_id", "source_code", "target_code", "text_hash", name="uq_language_review_once"),
        Index("ix_language_reviews_direction", "source_code", "target_code"),
        CheckConstraint("adequacy between 1 and 5 and fluency between 1 and 5", name="ck_review_scores"),
        CheckConstraint("severity in ('none','minor','major','critical')", name="ck_review_severity"),
        CheckConstraint("content_type in ('general','scripture','ministry','terminology','other')", name="ck_review_content"),
    )


class GlossaryEntry(Base):
    """A frequently translated word, expression or sentence with its TNI-approved translation in one language (English source)."""

    __tablename__ = "glossary_entries"
    id: Mapped[uuid.UUID] = _uuid_pk()
    language: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[str] = mapped_column(String(64), nullable=False)  # hash of the normalised source text: exact lookup and uniqueness
    target_text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="word")  # word | expression | sentence
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("language", "source_key", name="uq_glossary_language_source"),
        CheckConstraint("kind in ('word','expression','sentence')", name="ck_glossary_kind"),
    )


class GlossaryLead(Base):
    """Assigns a team leader to the language glossaries they maintain."""

    __tablename__ = "glossary_leads"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("user_id", "language", name="uq_glossary_lead"),)
