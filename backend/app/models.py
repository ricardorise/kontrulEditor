"""Entidades do 03-modelo-de-dados.md. Tempos em ms; intervalos [início, fim)."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=_id)


def fk(table: str, nullable: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(f"{table}.id", ondelete="CASCADE"), nullable=nullable, index=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[str] = mapped_column(String(100), default="default")
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(30), default="active")
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    role: Mapped[str] = mapped_column(String(20), default="main")  # main | auxiliary
    kind: Mapped[str] = mapped_column(String(20), default="unknown")  # video | image | audio | unknown
    filename: Mapped[str] = mapped_column(String(500))
    uri: Mapped[str] = mapped_column(String(1000))  # relativo a data_dir
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps_num: Mapped[int | None] = mapped_column(Integer)
    fps_den: Mapped[int | None] = mapped_column(Integer)
    audio_info: Mapped[dict | None] = mapped_column(JSONB)
    probe: Mapped[dict | None] = mapped_column(JSONB)
    proxy_uri: Mapped[str | None] = mapped_column(String(1000))
    thumbnail_uri: Mapped[str | None] = mapped_column(String(1000))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=1)  # 0 baixa, 1 normal, 2 alta (RF05)
    intended_use: Mapped[str | None] = mapped_column(String(200))  # ex.: "b-roll", "pip", "logo"
    suggested_duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded|processing|ready|failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    kind: Mapped[str] = mapped_column(String(30))  # ingest|transcribe|analyze|render_preview|render_final
    state: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    timeline_revision: Mapped[int | None] = mapped_column(Integer)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    log: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    __table_args__ = (UniqueConstraint("project_id", "idempotency_key", name="uq_job_idem"),)


class Speaker(Base):
    __tablename__ = "speakers"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    label: Mapped[str] = mapped_column(String(100))


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    asset_id: Mapped[uuid.UUID] = fk("assets")
    model_version: Mapped[str] = mapped_column(String(100))
    language: Mapped[str | None] = mapped_column(String(10))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    segments: Mapped[list] = mapped_column(JSONB, default=list)  # [{start_ms,end_ms,text,w0,w1,speaker}] w1 exclusivo
    diarized: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Word(Base):
    __tablename__ = "words"
    id: Mapped[uuid.UUID] = uuid_pk()
    transcript_id: Mapped[uuid.UUID] = fk("transcripts")
    speaker_id: Mapped[uuid.UUID | None] = fk("speakers", nullable=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float | None] = mapped_column(Float)


class Script(Base):
    __tablename__ = "scripts"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    asset_id: Mapped[uuid.UUID | None] = fk("assets", nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    format: Mapped[str] = mapped_column(String(10), default="txt")
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ScriptAlignment(Base):
    __tablename__ = "script_alignments"
    id: Mapped[uuid.UUID] = uuid_pk()
    script_id: Mapped[uuid.UUID] = fk("scripts")
    transcript_id: Mapped[uuid.UUID | None] = fk("transcripts", nullable=True)
    script_start: Mapped[int] = mapped_column(Integer)  # offsets de caractere [ini, fim)
    script_end: Mapped[int] = mapped_column(Integer)
    word_start_idx: Mapped[int | None] = mapped_column(Integer)
    word_end_idx: Mapped[int | None] = mapped_column(Integer)
    adherence: Mapped[float | None] = mapped_column(Float)
    kind: Mapped[str] = mapped_column(String(20))  # matched | unspoken | off_script


class Suggestion(Base):
    __tablename__ = "suggestions"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    script_id: Mapped[uuid.UUID | None] = fk("scripts", nullable=True)
    asset_id: Mapped[uuid.UUID | None] = fk("assets", nullable=True)
    start_ms: Mapped[int] = mapped_column(BigInteger)
    end_ms: Mapped[int] = mapped_column(BigInteger)
    category: Mapped[str] = mapped_column(String(30))  # speech_error|off_script|repetition|valid
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)  # None = sem score calibrado
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|accepted|rejected|adjusted
    origin: Mapped[str] = mapped_column(String(20), default="rules")
    model_version: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TimelineRevision(Base):
    __tablename__ = "timeline_revisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    revision: Mapped[int] = mapped_column(Integer)
    parent_revision: Mapped[int | None] = mapped_column(Integer)
    document_json: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("project_id", "revision", name="uq_timeline_rev"),)


class EditOperation(Base):
    __tablename__ = "edit_operations"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    base_revision: Mapped[int] = mapped_column(Integer)
    result_revision: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSONB)
    actor: Mapped[str] = mapped_column(String(100))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects")
    suggestion_id: Mapped[uuid.UUID] = fk("suggestions")
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text)
    corrected_start_ms: Mapped[int | None] = mapped_column(BigInteger)
    corrected_end_ms: Mapped[int | None] = mapped_column(BigInteger)
    actor: Mapped[str] = mapped_column(String(100))


class EditingRule(Base):
    __tablename__ = "editing_rules"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID | None] = fk("projects", nullable=True)
    scope: Mapped[str] = mapped_column(String(20), default="project")
    text: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    provenance: Mapped[dict | None] = mapped_column(JSONB)  # {source: manual|feedback, suggestion_ids, created_by}
    kind: Mapped[str] = mapped_column(String(30), default="note")  # note|ignore_erro_context|protect_phrase|extra_cue
    params: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"phrases": [...]}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
