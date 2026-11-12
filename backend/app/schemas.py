import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: str | None = None


class ProjectOut(ORM):
    id: uuid.UUID
    title: str
    status: str
    current_revision: int
    created_at: datetime


class AssetOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    role: str
    kind: str
    filename: str
    sha256: str | None
    size_bytes: int
    duration_ms: int | None
    width: int | None
    height: int | None
    fps_num: int | None
    fps_den: int | None
    audio_info: dict | None
    tags: list
    description: str | None
    priority: int = 1
    intended_use: str | None = None
    suggested_duration_ms: int | None = None
    status: str
    error: str | None
    has_proxy: bool = False
    has_thumbnail: bool = False
    created_at: datetime


class AssetPatch(BaseModel):
    tags: list[str] | None = None
    description: str | None = None
    priority: int | None = Field(default=None, ge=0, le=2)
    intended_use: str | None = Field(default=None, max_length=200)
    suggested_duration_ms: int | None = Field(default=None, ge=500, le=600_000)


class JobOut(ORM):
    job_id: uuid.UUID = Field(validation_alias="id")
    project_id: uuid.UUID
    kind: str
    state: str
    progress: float
    timeline_revision: int | None
    result: dict | None
    error: dict | None
    created_at: datetime


class TranscriptionCreate(BaseModel):
    asset_id: uuid.UUID
    language: str | None = Field(default=None, max_length=10)
    diarize: bool = False


class TranscriptOut(ORM):
    id: uuid.UUID
    asset_id: uuid.UUID
    model_version: str
    language: str | None
    revision: int
    diarized: bool
    created_at: datetime


class TranscriptFull(TranscriptOut):
    segments: list
    words: list


class WordPatch(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class ScriptCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    asset_id: uuid.UUID | None = None


class ScriptOut(ORM):
    id: uuid.UUID
    version: int
    format: str
    created_at: datetime


class ScriptFull(ScriptOut):
    text: str


class AlignmentOut(ORM):
    id: uuid.UUID
    transcript_id: uuid.UUID | None
    script_start: int
    script_end: int
    word_start_idx: int | None
    word_end_idx: int | None
    adherence: float | None
    kind: str


class AlignmentPatch(BaseModel):
    kind: str = Field(pattern="^(matched|unspoken|off_script)$")


class AnalysisCreate(BaseModel):
    transcript_id: uuid.UUID
    script_id: uuid.UUID | None = None
    use_llm: bool | None = None  # None = usa o LLM se estiver configurado; False = só regras; True = exige LLM


class SuggestionOut(ORM):
    id: uuid.UUID
    asset_id: uuid.UUID | None
    script_id: uuid.UUID | None
    start_ms: int
    end_ms: int
    category: str
    rationale: str
    evidence: dict | None
    confidence: float | None
    status: str
    origin: str
    created_at: datetime


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(accept|reject|adjust)$")
    reason: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)


class OperationsIn(BaseModel):
    expected_revision: int = Field(ge=0)
    operations: list[dict] = Field(min_length=1, max_length=500)


class TimelineOut(BaseModel):
    project_id: uuid.UUID
    revision: int
    parent_revision: int | None
    created_by: str
    created_at: datetime
    document: dict


class RenderCreate(BaseModel):
    profile: str = Field(pattern="^(preview|final)$")
    timeline_revision: int | None = Field(default=None, ge=1)
    fit: str = Field(default="letterbox", pattern="^(letterbox|crop)$")


class RenderOut(BaseModel):
    job_id: uuid.UUID
    profile: str
    state: str
    progress: float
    timeline_revision: int | None
    stale: bool
    result: dict | None
    error: dict | None
    created_at: datetime


RULE_KINDS = "^(note|ignore_erro_context|protect_phrase|extra_cue)$"


class RuleIn(BaseModel):
    kind: str = Field(default="note", pattern=RULE_KINDS)
    text: str = Field(min_length=1, max_length=500)
    params: dict = Field(default_factory=dict)
    scope: str = Field(default="project", pattern="^(project|user)$")
    provenance: dict | None = None


class RulePatch(BaseModel):
    enabled: bool | None = None
    text: str | None = Field(default=None, min_length=1, max_length=500)
    params: dict | None = None


class RuleOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID | None
    scope: str
    kind: str
    text: str
    params: dict
    enabled: bool
    provenance: dict | None
    created_at: datetime


class ProposalsIn(BaseModel):
    use_llm: bool | None = None  # None = usa se configurado
    asset_ids: list[uuid.UUID] | None = None
    max_per_asset: int = Field(default=1, ge=1, le=5)


class PlanIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    use_llm: bool | None = None


class FeedbackIn(BaseModel):
    suggestion_id: uuid.UUID
    decision: str = Field(pattern="^(accept|reject|adjust)$")
    reason: str | None = Field(default=None, max_length=1000)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
