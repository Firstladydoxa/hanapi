"""TNI knowledge base: governed documents -> versions -> chunks, hybrid retrieval (pgvector + full-text), access filtering.

Governance: documents start as drafts; only an administrator-approved version is ever indexed or retrievable.
Deactivated or superseded content is removed from retrieval immediately. HAN never fabricates TNI knowledge: with no hit it says so.
"""
from __future__ import annotations

import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import delete, func, select, text as sql
from sqlalchemy.orm import Session

from .config import get_settings
from .errors import ApiError
from .han import assistant_client
from .models.db import KNOWLEDGE_CATEGORIES, KnowledgeChunk, KnowledgeDocument, KnowledgeVersion, User

ALLOWED_EXT = (".txt", ".md", ".markdown", ".docx", ".pdf")
STOP = set("the a an of to in on for and or is are was were be do does did how what when where why which who can could should would i you we it this that "
           "with from my your our about me please tell hi hello han tni definition define meaning according pastor chris teaching teachings explain".split())
HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][^\n.!?]{2,80})$")


@dataclass
class Hit:
    document_id: str
    title: str
    category: str
    version: int
    heading: Optional[str]
    text: str
    score: float


# ------------------------------------------------------------------ ingestion
def extract_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    if not name.endswith(ALLOWED_EXT):
        raise ApiError(415, "unsupported_file", "Upload a .txt, .md, .docx or .pdf file, or paste the text.")
    if len(data) > get_settings().knowledge_max_upload_bytes:
        raise ApiError(413, "file_too_large", "That file is too large.")
    try:
        if name.endswith(".docx"):
            import docx

            d = docx.Document(io.BytesIO(data))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                parts += [" | ".join(c.text for c in row.cells) for row in t.rows]
            text = "\n\n".join(parts)
        elif name.endswith(".pdf"):
            from pypdf import PdfReader

            text = "\n\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        else:
            text = data.decode("utf-8", errors="replace")
    except ApiError:
        raise
    except Exception:  # noqa: BLE001
        raise ApiError(422, "unreadable_file", "That file could not be read. Please check it or paste the text instead.")
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise ApiError(422, "empty_document", "No readable text was found in that document.")
    return text


def chunk_text(text: str, size: Optional[int] = None) -> List[Dict[str, Optional[str]]]:
    """Paragraph-aware chunks of about `size` characters, each remembering the nearest preceding heading."""
    size = size or get_settings().knowledge_chunk_chars
    heading: Optional[str] = None
    chunks: List[Dict[str, Optional[str]]] = []
    buf: List[str] = []
    cur = 0

    def flush() -> None:
        nonlocal buf, cur
        if buf:
            chunks.append({"heading": heading, "text": "\n".join(buf).strip()})
        buf, cur = [], 0

    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        para = para.strip()
        if not para:
            continue
        if "\n" not in para and len(para) <= 90 and HEADING.match(para) and not para.endswith((",", ";")):
            flush()
            heading = para.lstrip("# ").strip()
            continue
        pieces = [para] if len(para) <= size else re.findall(r".{1,%d}(?:[.!?]\s+|$)" % size, para, re.S)
        for piece in pieces:
            if cur + len(piece) > size and buf:
                flush()
            buf.append(piece.strip())
            cur += len(piece)
    flush()
    return [c for c in chunks if c["text"]]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def create_document(db: Session, actor: User, *, title: str, category: str, text: str, filename: Optional[str] = None,
                    languages: Optional[Sequence[str]] = None, audience_roles: Optional[Sequence[str]] = None,
                    project_id: Optional[uuid.UUID] = None, system_managed: bool = False, note: Optional[str] = None) -> KnowledgeDocument:
    if category not in KNOWLEDGE_CATEGORIES:
        raise ApiError(422, "invalid_category", "Unknown knowledge category.")
    doc = KnowledgeDocument(title=title.strip(), category=category, languages=list(languages or []), audience_roles=list(audience_roles or []),
                            project_id=project_id, status="draft", system_managed=system_managed, owner_id=getattr(actor, "id", None))
    db.add(doc)
    db.flush()
    add_version(db, doc, actor, text, filename, note)
    return doc


def add_version(db: Session, doc: KnowledgeDocument, actor: Optional[User], text: str, filename: Optional[str] = None,
                note: Optional[str] = None) -> KnowledgeVersion:
    last = db.execute(select(func.max(KnowledgeVersion.version_number)).where(KnowledgeVersion.document_id == doc.id)).scalar() or 0
    v = KnowledgeVersion(document_id=doc.id, version_number=last + 1, filename=filename, content_hash=_hash(text), text=text, note=note,
                         created_by=getattr(actor, "id", None))
    db.add(v)
    db.commit()
    return v


def approve_version(db: Session, doc: KnowledgeDocument, version: KnowledgeVersion, actor: Optional[User]) -> int:
    """Make `version` the only retrievable content of the document and index it. Returns the number of chunks."""
    if version.document_id != doc.id:
        raise ApiError(404, "not_found", "That version was not found.")
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    doc.approved_version_id, doc.status = version.id, "approved"
    version.approved_at, version.approved_by = datetime.now(timezone.utc), getattr(actor, "id", None)
    parts = chunk_text(version.text)
    vectors = assistant_client.embed([f"{p['heading'] or ''}\n{p['text']}".strip() for p in parts], "passage") if parts else None
    for i, p in enumerate(parts):
        db.add(KnowledgeChunk(document_id=doc.id, version_id=version.id, ordinal=i, heading=p["heading"], text=p["text"],
                              embedding=vectors[i] if vectors else None))
    db.flush()
    db.execute(sql("UPDATE knowledge_chunks SET tsv = to_tsvector('simple', coalesce(heading,'') || ' ' || text) WHERE document_id = :d"), {"d": doc.id})
    db.commit()
    return len(parts)


def deactivate(db: Session, doc: KnowledgeDocument) -> None:
    doc.status = "inactive"
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
    db.commit()


def reindex_missing_embeddings(db: Session, batch: int = 16) -> int:
    """Backfill vectors for chunks created while the assistant service was down. Returns how many were filled."""
    done = 0
    while True:
        rows = list(db.execute(select(KnowledgeChunk).where(KnowledgeChunk.embedding.is_(None)).limit(batch)).scalars())
        if not rows:
            return done
        vecs = assistant_client.embed([f"{r.heading or ''}\n{r.text}".strip() for r in rows], "passage")
        if not vecs:
            return done
        for r, v in zip(rows, vecs):
            r.embedding = v
        db.commit()
        done += len(rows)


# ------------------------------------------------------------------ retrieval
def _terms(query: str) -> List[str]:
    seen: List[str] = []
    for w in re.findall(r"\w+", query.lower()):
        if len(w) >= 3 and w not in STOP and w not in seen:
            seen.append(w)
    return seen[:12]


def _visible(doc: KnowledgeDocument, user: User, project_id: Optional[uuid.UUID], languages: Sequence[str]) -> bool:
    if doc.status != "approved":
        return False
    if doc.project_id is not None and doc.project_id != project_id:
        return False
    if doc.audience_roles and user.role not in doc.audience_roles:
        return False
    if languages and doc.languages and not ({l.lower() for l in doc.languages} & {l.lower() for l in languages}):
        return False
    return True


def retrieve(db: Session, user: User, query: str, project_id: Optional[uuid.UUID] = None, languages: Sequence[str] = (),
             categories: Optional[Sequence[str]] = None, k: Optional[int] = None) -> List[Hit]:
    """Hybrid search over APPROVED versions only, filtered by project, audience role and language."""
    s = get_settings()
    k = k or s.knowledge_top_k
    terms = _terms(query)
    base = (select(KnowledgeChunk, KnowledgeDocument, KnowledgeVersion.version_number)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(KnowledgeVersion, KnowledgeVersion.id == KnowledgeChunk.version_id)
            .where(KnowledgeDocument.status == "approved", KnowledgeChunk.version_id == KnowledgeDocument.approved_version_id))
    if categories:
        base = base.where(KnowledgeDocument.category.in_(list(categories)))
    scored: Dict[uuid.UUID, Dict[str, Any]] = {}

    def keep(chunk, doc, ver, rank: int, weight: float) -> None:
        if not _visible(doc, user, project_id, languages):
            return
        e = scored.setdefault(chunk.id, {"chunk": chunk, "doc": doc, "ver": ver, "score": 0.0})
        if not e.get("titled") and chunk.heading and any(t in chunk.heading.lower() for t in terms):
            e["titled"] = True
            e["score"] += 0.03  # a passage whose heading names the concept is the best answer to "what is X?"
        e["score"] += weight / (60 + rank)

    if terms:
        q = " | ".join(terms)
        stmt = base.add_columns(func.ts_rank(KnowledgeChunk.tsv, func.to_tsquery("simple", q)).label("r")).where(
            KnowledgeChunk.tsv.op("@@")(func.to_tsquery("simple", q))).order_by(sql("r DESC")).limit(24)
        for rank, (chunk, doc, ver, _r) in enumerate(db.execute(stmt).all()):
            lower = (chunk.text + " " + (chunk.heading or "")).lower()
            if sum(1 for t in terms if t in lower) >= min(2, len(terms)):  # one stray common word is not evidence
                keep(chunk, doc, ver, rank, 1.0)
    vec = assistant_client.embed([query], "query")
    if vec:
        dist = KnowledgeChunk.embedding.cosine_distance(vec[0])
        stmt = base.add_columns(dist.label("d")).where(KnowledgeChunk.embedding.is_not(None)).order_by(dist).limit(24)
        for rank, (chunk, doc, ver, d) in enumerate(db.execute(stmt).all()):
            if 1.0 - float(d) >= s.knowledge_min_similarity:
                keep(chunk, doc, ver, rank, 1.0)
    ranked = sorted(scored.values(), key=lambda e: -e["score"])[:k]
    return [Hit(str(e["doc"].id), e["doc"].title, e["doc"].category, e["ver"], e["chunk"].heading, e["chunk"].text, e["score"]) for e in ranked]


# ------------------------------------------------------------------ the shipped platform guide
PLATFORM_GUIDE_TITLE = "Using HAN"
PLATFORM_GUIDE = """# Using HAN

HAN is TNI's translation assistant. HAN prepares suggested translation drafts; translators review, edit and approve them. HAN never approves a translation.

## Projects
After signing in you see the projects you belong to. Open a project to work in it. Everything you do in a project follows that project's instructions, terminology and Translation Memory.

## HAN Chat
HAN Chat is a conversation with HAN inside a project. You can ask HAN to translate text, ask for help with grammar, tone or wording, ask about terminology, or ask how to use the platform. Your conversations are saved. Use the history panel to search, rename, archive or delete earlier conversations and to continue one where you stopped.

## Quick translate
Quick translate is for short texts. Choose the From and To languages, paste your text and press Translate. The result is a draft for you to review. Use Open in workspace to continue working on it.

## Translation workspace
The workspace is for longer work. Choose the languages, enter the source text and create a draft. You can edit the draft, save new versions, compare versions, and see quality warnings and matches from the project's Translation Memory and terminology.

## Reviewing a draft
Read the draft carefully against the source. Warnings flag possible problems such as terminology, numbers or formatting; they are prompts to check, not final judgements. Every saved edit becomes a new version, and earlier versions are kept.

## Approving a translation
Only a person can approve. When you are satisfied, use the Approve button in the review panel. Approval is recorded under your name. Only users with approval permission in the project see the Approve button. Approved translations are added to the project's Translation Memory.

## Translation Memory and terminology
The Translation Memory holds approved translations from the project and suggests matches for new text. Terminology holds approved terms; HAN checks drafts against them. If a term has no approved entry, ask an administrator to add one.

## Language availability
Language pairs are opened in stages. A pair can be Validated, Assisted, or in Controlled testing (labelled Experimental). Experimental drafts have not yet been evaluated by TNI translators, so review them with extra care. The Languages page lists every language and its status.

## Getting help
If something does not work, note what you were doing and tell your project manager or a TNI administrator.
"""


def seed_platform_guide(db: Session) -> str:
    """Create/refresh the shipped guide (approved, system-managed). Only truthful HAN feature descriptions: no TNI policy."""
    doc = db.execute(select(KnowledgeDocument).where(KnowledgeDocument.system_managed.is_(True), KnowledgeDocument.title == PLATFORM_GUIDE_TITLE)).scalar_one_or_none()
    if doc is None:
        doc = create_document(db, None, title=PLATFORM_GUIDE_TITLE, category="platform", text=PLATFORM_GUIDE, system_managed=True,  # type: ignore[arg-type]
                              note="Shipped with HAN")
        approve_version(db, doc, db.get(KnowledgeVersion, db.execute(select(KnowledgeVersion.id).where(KnowledgeVersion.document_id == doc.id)).scalar()), None)
        return "platform guide created"
    current = db.get(KnowledgeVersion, doc.approved_version_id) if doc.approved_version_id else None
    if current is None or current.content_hash != _hash(PLATFORM_GUIDE) or doc.status != "approved":
        v = add_version(db, doc, None, PLATFORM_GUIDE, note="Updated with HAN release")
        approve_version(db, doc, v, None)
        return "platform guide updated"
    return "platform guide up to date"


# ------------------------------------------------------------------ the shipped doctrine reference
DOCTRINE_TITLE = "Pastor Chris Oyakhilome: Doctrinal Terminology and Teaching Reference (v0.1, approved)"
DOCTRINE_FILE = Path(__file__).parent / "kb_content" / "pastor-chris-doctrine-reference-v0.1.md"


def seed_doctrine_reference(db: Session) -> str:
    """Load the first TNI doctrine reference once. Later versions are managed by administrators in the Knowledge base page."""
    if db.execute(select(KnowledgeDocument.id).where(KnowledgeDocument.title == DOCTRINE_TITLE)).first() is not None:
        return "doctrine reference already present"
    text = DOCTRINE_FILE.read_text(encoding="utf-8")
    doc = create_document(db, None, title=DOCTRINE_TITLE, category="doctrine", text=text, filename=DOCTRINE_FILE.name,  # type: ignore[arg-type]
                          note="v0.1 approved by TNI for use by HAN")
    version = db.execute(select(KnowledgeVersion).where(KnowledgeVersion.document_id == doc.id)).scalar_one()
    return f"doctrine reference loaded ({approve_version(db, doc, version, None)} passages)"
