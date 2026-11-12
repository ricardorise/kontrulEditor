"""Persistência da timeline: revisões imutáveis + operações auditáveis, com lock otimista."""
import copy
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, EditOperation, Project, Suggestion, TimelineRevision
from app.services import timeline as T


class RevisionConflict(Exception):
    def __init__(self, current: int, expected: int):
        super().__init__(f"revisão atual é {current}, esperada {expected}")
        self.current, self.expected = current, expected


def asset_map(db: Session, project_id: uuid.UUID) -> dict:
    rows = db.scalars(select(Asset).where(Asset.project_id == project_id)).all()
    return {str(a.id): {"kind": a.kind, "duration_ms": a.duration_ms, "status": a.status, "width": a.width,
                        "height": a.height, "fps_num": a.fps_num, "fps_den": a.fps_den, "audio_info": a.audio_info,
                        "uri": a.uri, "role": a.role} for a in rows if a.status == "ready"}


def get_revision(db: Session, project_id: uuid.UUID, revision: int) -> TimelineRevision | None:
    return db.scalar(select(TimelineRevision).where(TimelineRevision.project_id == project_id,
                                                    TimelineRevision.revision == revision))


def _expand(db: Session, project_id: uuid.UUID, op: dict) -> list[dict]:
    """apply_suggestion → remove_range. Só sugestões aceitas/ajustadas pelo usuário viram corte."""
    if op.get("type") != "apply_suggestion":
        return [op]
    try:
        s = db.get(Suggestion, uuid.UUID(str(op.get("suggestion_id"))))
    except ValueError:
        s = None
    if not s or s.project_id != project_id:
        raise T.TimelineError("sugestão não encontrada", "suggestion_not_found")
    if s.status not in ("accepted", "adjusted"):
        raise T.TimelineError("a sugestão precisa ser aceita antes de ser aplicada", "suggestion_not_accepted")
    if not s.asset_id:
        raise T.TimelineError("sugestão sem asset de origem", "invalid_suggestion")
    h = int(op.get("handle_ms", 0) or 0)  # margem preservada em cada borda
    start, end = s.start_ms + h, s.end_ms - h
    if end <= start:
        raise T.TimelineError("margem maior que o trecho", "invalid_range")
    return [{"type": "remove_range", "asset_id": str(s.asset_id), "start_ms": start, "end_ms": end,
             "suggestion_id": str(s.id)}]


def apply_operations(db: Session, project_id: uuid.UUID, expected_revision: int, ops: list[dict],
                     actor: str = "default") -> TimelineRevision:
    if not ops:
        raise T.TimelineError("nenhuma operação informada", "invalid_payload")
    proj = db.execute(select(Project).where(Project.id == project_id).with_for_update()).scalar_one()
    if proj.current_revision != expected_revision:
        raise RevisionConflict(proj.current_revision, expected_revision)
    cur = get_revision(db, project_id, proj.current_revision)
    doc = copy.deepcopy(cur.document_json) if cur else T.empty_doc()
    assets = asset_map(db, project_id)
    applied: list[dict] = []
    for op in ops:
        if op.get("type") == "revert_to":
            target = get_revision(db, project_id, int(op.get("revision", -1)))
            if not target:
                raise T.TimelineError("revisão alvo não existe", "revision_not_found")
            doc = copy.deepcopy(target.document_json)
            applied.append(op)
            continue
        for e in _expand(db, project_id, op):
            doc = T.apply_op(doc, e, assets)
        applied.append(op)
    T.validate(doc, assets)
    new_rev = proj.current_revision + 1
    rev = TimelineRevision(project_id=project_id, revision=new_rev, parent_revision=proj.current_revision or None,
                           document_json=doc, created_by=actor)
    db.add(rev)
    for op in applied:
        db.add(EditOperation(project_id=project_id, base_revision=proj.current_revision, result_revision=new_rev,
                             type=op["type"], payload={k: v for k, v in op.items() if k != "type"}, actor=actor))
    proj.current_revision = new_rev
    db.commit()
    return rev
