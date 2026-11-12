import uuid

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas, storage
from app.api.deps import get_session, require_auth
from app.config import settings
from app.models import (Asset, EditingRule, Feedback, Job, Project, Script, ScriptAlignment, Suggestion,
                        Transcript, Word)
from app import observability, signing
from app.llm import client as llm
from app.models import EditOperation, TimelineRevision
from app.services import jobs as J
from app.services import timeline as T
from app.services import timeline_service as TS
from app.services import assistant, learning, placement

router = APIRouter(prefix="/v1", dependencies=[Depends(require_auth)])


def _project(db: Session, pid: uuid.UUID) -> Project:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "projeto não encontrado")
    return p


def _asset(db: Session, pid: uuid.UUID, aid: uuid.UUID) -> Asset:
    a = db.get(Asset, aid)
    if not a or a.project_id != pid:
        raise HTTPException(404, "asset não encontrado")
    return a


def _asset_out(a: Asset) -> schemas.AssetOut:
    out = schemas.AssetOut.model_validate(a)
    out.has_proxy, out.has_thumbnail = bool(a.proxy_uri), bool(a.thumbnail_uri)
    return out


def enqueue_ingest(job_id: uuid.UUID) -> None:
    from app.workers.tasks import ingest_asset
    ingest_asset.send(str(job_id))


def enqueue_transcribe(job_id: uuid.UUID) -> None:
    from app.workers.tasks import transcribe_asset
    transcribe_asset.send(str(job_id))


def enqueue_analyze(job_id: uuid.UUID) -> None:
    from app.workers.tasks import analyze_project
    analyze_project.send(str(job_id))


# ---- projetos
@router.post("/projects", response_model=schemas.ProjectOut, status_code=201)
def create_project(body: schemas.ProjectCreate, db: Session = Depends(get_session)):
    p = Project(title=body.title)
    db.add(p)
    db.commit()
    return p


@router.get("/projects", response_model=list[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_session)):
    return db.scalars(select(Project).order_by(Project.created_at.desc())).all()


@router.get("/projects/{pid}", response_model=schemas.ProjectOut)
def get_project(pid: uuid.UUID, db: Session = Depends(get_session)):
    return _project(db, pid)


@router.patch("/projects/{pid}", response_model=schemas.ProjectOut)
def patch_project(pid: uuid.UUID, body: schemas.ProjectPatch, db: Session = Depends(get_session)):
    p = _project(db, pid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return p


# ---- assets
@router.post("/projects/{pid}/assets", response_model=dict, status_code=202)
def upload_asset(pid: uuid.UUID, file: UploadFile = File(...), role: str = Form("main"),
                 tags: str = Form(""), description: str | None = Form(None),
                 idempotency_key: str | None = Header(default=None),
                 db: Session = Depends(get_session)):
    _project(db, pid)
    if role not in ("main", "auxiliary"):
        raise HTTPException(422, "role deve ser main ou auxiliary")
    if idempotency_key:
        prev = db.scalar(select(Job).where(Job.project_id == pid, Job.idempotency_key == idempotency_key))
        if prev:
            return {"asset": _asset_out(db.get(Asset, uuid.UUID(prev.params["asset_id"]))).model_dump(mode="json"),
                    "job": schemas.JobOut.model_validate(prev).model_dump(mode="json")}
    aid = uuid.uuid4()
    name = storage.safe_filename(file.filename or "arquivo")
    uri = f"{storage.asset_dir(pid, aid)}/original/{name}"
    try:
        sha, size = storage.save_upload(uri, file.file, settings.max_upload_bytes)
    except storage.UploadTooLarge:
        raise HTTPException(413, "arquivo excede o limite de upload")
    a = Asset(id=aid, project_id=pid, role=role, filename=name, uri=uri, sha256=sha, size_bytes=size,
              tags=[t.strip() for t in tags.split(",") if t.strip()], description=description)
    db.add(a)
    db.flush()
    job = J.create_job(db, pid, "ingest", {"asset_id": str(aid)}, idempotency_key)
    db.commit()
    enqueue_ingest(job.id)
    return {"asset": _asset_out(a).model_dump(mode="json"),
            "job": schemas.JobOut.model_validate(job).model_dump(mode="json")}


@router.get("/projects/{pid}/assets", response_model=list[schemas.AssetOut])
def list_assets(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    rows = db.scalars(select(Asset).where(Asset.project_id == pid).order_by(Asset.created_at)).all()
    return [_asset_out(a) for a in rows]


@router.patch("/projects/{pid}/assets/{aid}", response_model=schemas.AssetOut)
def patch_asset(pid: uuid.UUID, aid: uuid.UUID, body: schemas.AssetPatch, db: Session = Depends(get_session)):
    a = _asset(db, pid, aid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.commit()
    return _asset_out(a)


@router.get("/projects/{pid}/assets/{aid}/file")
def asset_file(pid: uuid.UUID, aid: uuid.UUID, variant: str = "proxy", db: Session = Depends(get_session)):
    a = _asset(db, pid, aid)
    uri = {"original": a.uri, "proxy": a.proxy_uri or a.uri, "thumbnail": a.thumbnail_uri}.get(variant)
    if not uri:
        raise HTTPException(404, "variante indisponível")
    return FileResponse(storage.resolve(uri))  # suporta Range para o player


@router.get("/projects/{pid}/assets/{aid}/file-url")
def asset_file_url(pid: uuid.UUID, aid: uuid.UUID, variant: str = "proxy", db: Session = Depends(get_session)):
    """URL assinada e temporária para o player/miniaturas (o <video> não envia Bearer)."""
    a = _asset(db, pid, aid)
    if variant not in ("original", "proxy", "thumbnail") or (variant == "thumbnail" and not a.thumbnail_uri):
        raise HTTPException(404, "variante indisponível")
    token, exp = signing.sign(f"asset:{a.id}:{variant}")
    return {"url": f"/v1/dl/{token}", "expires_at": exp}


@router.get("/projects/{pid}/assets/{aid}/waveform")
def asset_waveform(pid: uuid.UUID, aid: uuid.UUID, db: Session = Depends(get_session)):
    import json
    from app import media
    a = _asset(db, pid, aid)
    if a.status != "ready" or not a.audio_info:
        raise HTTPException(404, "asset sem áudio")
    cache = storage.resolve(f"{storage.asset_dir(pid, aid)}/waveform.json")
    if not cache.exists():
        try:
            cache.write_text(json.dumps(media.waveform(storage.resolve(a.uri))))
        except media.MediaError as e:
            raise HTTPException(422, f"não foi possível gerar a forma de onda: {e}")
    return FileResponse(cache, media_type="application/json")


# ---- jobs
@router.get("/jobs/{jid}", response_model=schemas.JobOut)
def get_job(jid: uuid.UUID, db: Session = Depends(get_session)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404, "job não encontrado")
    return j


ENQUEUE = {"ingest": "enqueue_ingest", "transcribe": "enqueue_transcribe", "analyze": "enqueue_analyze",
           "render_preview": "enqueue_render", "render_final": "enqueue_render"}


@router.post("/jobs/{jid}/retry", response_model=schemas.JobOut, status_code=202)
def retry_job(jid: uuid.UUID, db: Session = Depends(get_session)):
    """Cria um novo job com os mesmos parâmetros a partir de um job que falhou ou foi cancelado."""
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404, "job não encontrado")
    if j.state not in ("failed", "cancelled"):
        raise HTTPException(409, f"só é possível tentar de novo jobs falhos/cancelados (estado: {j.state})")
    if j.kind not in ENQUEUE:
        raise HTTPException(422, "tipo de job não suporta retry")
    new = J.create_job(db, j.project_id, j.kind, dict(j.params))
    new.timeline_revision = j.timeline_revision
    if j.kind == "ingest":
        a = db.get(Asset, uuid.UUID(j.params["asset_id"]))
        if a:
            a.status, a.error = "uploaded", None
    db.commit()
    globals()[ENQUEUE[j.kind]](new.id)
    return new


@router.get("/llm/status")
def llm_status():
    """Provedor/modelo ativos (sem chaves) e se a transcrição sai da máquina. Padrão: LLM desativado."""
    return llm.status()


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_session)):
    rows = db.execute(select(Job.kind, Job.state, func.count()).group_by(Job.kind, Job.state)).all()
    return observability.render_metrics([(k, s, n) for k, s, n in rows])


def _quota(db: Session, pid: uuid.UUID, kinds: tuple[str, ...], limit: int) -> None:
    n = db.scalar(select(func.count()).select_from(Job).where(Job.project_id == pid, Job.kind.in_(kinds),
                                                               Job.state.in_(("queued", "running"))))
    if (n or 0) >= limit:
        raise HTTPException(429, f"limite de {limit} jobs simultâneos deste tipo no projeto; aguarde terminar ou cancele",
                            headers={"Retry-After": "30"})


@router.post("/jobs/{jid}/cancel", response_model=schemas.JobOut)
def cancel_job(jid: uuid.UUID, db: Session = Depends(get_session)):
    j = db.get(Job, jid)
    if not j:
        raise HTTPException(404, "job não encontrado")
    if j.state not in J.TERMINAL:
        j.cancel_requested = True
        if j.state == "queued":
            j.state = "cancelled"
        db.commit()
    return j


@router.get("/projects/{pid}/jobs", response_model=list[schemas.JobOut])
def list_jobs(pid: uuid.UUID, db: Session = Depends(get_session)):
    return db.scalars(select(Job).where(Job.project_id == pid).order_by(Job.created_at.desc())).all()


# ---- transcrição
def _job_resp(job: Job) -> dict:
    return schemas.JobOut.model_validate(job).model_dump(mode="json")


@router.post("/projects/{pid}/transcriptions", response_model=schemas.JobOut, status_code=202)
def start_transcription(pid: uuid.UUID, body: schemas.TranscriptionCreate,
                        idempotency_key: str | None = Header(default=None), db: Session = Depends(get_session)):
    _project(db, pid)
    a = _asset(db, pid, body.asset_id)
    if a.status != "ready" or a.kind not in ("video", "audio"):
        raise HTTPException(409, "asset precisa estar pronto e conter áudio")
    if idempotency_key:
        prev = db.scalar(select(Job).where(Job.project_id == pid, Job.idempotency_key == idempotency_key))
        if prev:
            return prev
    _quota(db, pid, ("transcribe",), settings.max_active_asr_jobs)
    job = J.create_job(db, pid, "transcribe", {"asset_id": str(a.id), "language": body.language,
                                                "diarize": body.diarize}, idempotency_key)
    db.commit()
    enqueue_transcribe(job.id)
    return job


def _transcript(db: Session, pid: uuid.UUID, tid: uuid.UUID) -> Transcript:
    t = db.get(Transcript, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404, "transcrição não encontrada")
    return t


@router.get("/projects/{pid}/transcriptions", response_model=list[schemas.TranscriptOut])
def list_transcriptions(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    return db.scalars(select(Transcript).where(Transcript.project_id == pid).order_by(Transcript.created_at)).all()


@router.get("/projects/{pid}/transcriptions/{tid}", response_model=schemas.TranscriptFull)
def get_transcription(pid: uuid.UUID, tid: uuid.UUID, db: Session = Depends(get_session)):
    t = _transcript(db, pid, tid)
    ws = db.scalars(select(Word).where(Word.transcript_id == tid).order_by(Word.idx)).all()
    out = schemas.TranscriptFull.model_validate({**{c: getattr(t, c) for c in
                                                   ("id", "asset_id", "model_version", "language", "revision",
                                                    "diarized", "created_at", "segments")}, "words": [
        {"idx": w.idx, "text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms, "confidence": w.confidence,
         "speaker_id": str(w.speaker_id) if w.speaker_id else None} for w in ws]})
    return out


@router.patch("/projects/{pid}/transcriptions/{tid}/words/{idx}")
def correct_word(pid: uuid.UUID, tid: uuid.UUID, idx: int, body: schemas.WordPatch, db: Session = Depends(get_session)):
    _transcript(db, pid, tid)
    w = db.scalar(select(Word).where(Word.transcript_id == tid, Word.idx == idx))
    if not w:
        raise HTTPException(404, "palavra não encontrada")
    w.text = body.text  # correção manual; o áudio original não é tocado
    db.commit()
    return {"idx": idx, "text": w.text}


# ---- roteiro (RF10)
@router.post("/projects/{pid}/scripts", response_model=schemas.ScriptOut, status_code=201)
async def create_script(pid: uuid.UUID, request: Request, db: Session = Depends(get_session)):
    """JSON {text} ou multipart com arquivo .txt/.md."""
    _project(db, pid)
    fmt, text = "txt", ""
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            raise HTTPException(422, "campo 'file' ausente")
        name = (f.filename or "").lower()
        if not name.endswith((".txt", ".md")):
            raise HTTPException(415, "formato não suportado (use .txt ou .md)")
        fmt = "md" if name.endswith(".md") else "txt"
        raw = await f.read()
        if len(raw) > 2_000_000:
            raise HTTPException(413, "roteiro grande demais")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        try:
            body = schemas.ScriptCreate.model_validate(await request.json())
        except Exception:
            raise HTTPException(422, "corpo inválido: esperado {text}")
        text = body.text
    if not text.strip():
        raise HTTPException(422, "roteiro vazio")
    version = (db.scalar(select(func.max(Script.version)).where(Script.project_id == pid)) or 0) + 1
    sc = Script(project_id=pid, version=version, format=fmt, text=text)
    db.add(sc)
    db.commit()
    return sc


@router.get("/projects/{pid}/scripts", response_model=list[schemas.ScriptFull])
def list_scripts(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    return db.scalars(select(Script).where(Script.project_id == pid).order_by(Script.version)).all()


def _script(db: Session, pid: uuid.UUID, sid: uuid.UUID) -> Script:
    sc = db.get(Script, sid)
    if not sc or sc.project_id != pid:
        raise HTTPException(404, "roteiro não encontrado")
    return sc


@router.delete("/projects/{pid}/scripts/{sid}", status_code=204)
def delete_script(pid: uuid.UUID, sid: uuid.UUID, db: Session = Depends(get_session)):
    db.delete(_script(db, pid, sid))
    db.commit()


@router.get("/projects/{pid}/scripts/{sid}/alignment", response_model=list[schemas.AlignmentOut])
def get_alignment(pid: uuid.UUID, sid: uuid.UUID, db: Session = Depends(get_session)):
    _script(db, pid, sid)
    return db.scalars(select(ScriptAlignment).where(ScriptAlignment.script_id == sid)
                      .order_by(ScriptAlignment.word_start_idx.nulls_last(), ScriptAlignment.script_start)).all()


@router.patch("/projects/{pid}/scripts/{sid}/alignment/{aid}", response_model=schemas.AlignmentOut)
def patch_alignment(pid: uuid.UUID, sid: uuid.UUID, aid: uuid.UUID, body: schemas.AlignmentPatch,
                    db: Session = Depends(get_session)):
    _script(db, pid, sid)
    al = db.get(ScriptAlignment, aid)
    if not al or al.script_id != sid:
        raise HTTPException(404, "item de alinhamento não encontrado")
    al.kind = body.kind
    db.commit()
    return al


# ---- análise e sugestões
@router.post("/projects/{pid}/analyses", response_model=schemas.JobOut, status_code=202)
def start_analysis(pid: uuid.UUID, body: schemas.AnalysisCreate, idempotency_key: str | None = Header(default=None),
                   db: Session = Depends(get_session)):
    _project(db, pid)
    _transcript(db, pid, body.transcript_id)
    if body.script_id:
        _script(db, pid, body.script_id)
    if idempotency_key:
        prev = db.scalar(select(Job).where(Job.project_id == pid, Job.idempotency_key == idempotency_key))
        if prev:
            return prev
    if body.use_llm and llm.get_client() is None:
        raise HTTPException(409, f"LLM não está disponível: {llm.status()['message']}")
    job = J.create_job(db, pid, "analyze", {"transcript_id": str(body.transcript_id),
                                             "script_id": str(body.script_id) if body.script_id else None,
                                             "use_llm": body.use_llm},
                       idempotency_key)
    db.commit()
    enqueue_analyze(job.id)
    return job


@router.get("/projects/{pid}/suggestions", response_model=list[schemas.SuggestionOut])
def list_suggestions(pid: uuid.UUID, category: str | None = None, status: str | None = None,
                     db: Session = Depends(get_session)):
    _project(db, pid)
    q = select(Suggestion).where(Suggestion.project_id == pid)
    if category:
        q = q.where(Suggestion.category == category)
    if status:
        q = q.where(Suggestion.status == status)
    return db.scalars(q.order_by(Suggestion.start_ms)).all()


@router.post("/projects/{pid}/suggestions", response_model=schemas.SuggestionOut, status_code=201)
def create_manual_suggestion(pid: uuid.UUID, body: schemas.ManualSuggestionIn, db: Session = Depends(get_session)):
    """Corte marcado à mão pelo usuário: entra na lista de ocorrências já aceito (nada é cortado até aplicar)."""
    _project(db, pid)
    if body.end_ms <= body.start_ms:
        raise HTTPException(422, "end_ms deve ser maior que start_ms")
    if body.asset_id:
        a = db.get(Asset, body.asset_id)
        if not a or a.project_id != pid:
            raise HTTPException(404, "asset não encontrado")
    else:
        a = db.scalar(select(Asset).where(Asset.project_id == pid, Asset.role == "main", Asset.status == "ready")
                      .order_by(Asset.created_at))
        if not a:
            raise HTTPException(409, "projeto sem vídeo principal pronto")
    if a.duration_ms and body.end_ms > a.duration_ms:
        raise HTTPException(422, "intervalo além da duração do vídeo")
    s = Suggestion(project_id=pid, asset_id=a.id, start_ms=body.start_ms, end_ms=body.end_ms, category="manual",
                   rationale=body.note or "Corte marcado manualmente.", evidence=None, confidence=None,
                   status="accepted", origin="manual")
    db.add(s)
    db.commit()
    return s


@router.post("/projects/{pid}/suggestions/{sid}/decision", response_model=schemas.SuggestionOut)
def decide(pid: uuid.UUID, sid: uuid.UUID, body: schemas.DecisionIn, db: Session = Depends(get_session)):
    return _decide(db, pid, sid, body)


@router.post("/projects/{pid}/feedback", response_model=schemas.SuggestionOut, status_code=201)
def record_feedback(pid: uuid.UUID, body: schemas.FeedbackIn, db: Session = Depends(get_session)):
    """Registra feedback do usuário/agente sobre uma sugestão (mesma fonte de verdade da decisão)."""
    return _decide(db, pid, body.suggestion_id, schemas.DecisionIn(decision=body.decision, reason=body.reason,
                                                                  start_ms=body.start_ms, end_ms=body.end_ms))


def _decide(db: Session, pid: uuid.UUID, sid: uuid.UUID, body: schemas.DecisionIn):
    s = db.get(Suggestion, sid)
    if not s or s.project_id != pid:
        raise HTTPException(404, "sugestão não encontrada")
    fb = Feedback(project_id=pid, suggestion_id=sid, decision=body.decision, reason=body.reason, actor="default")
    if body.decision == "adjust":
        if body.start_ms is None or body.end_ms is None or body.end_ms <= body.start_ms:
            raise HTTPException(422, "adjust exige start_ms < end_ms")
        fb.corrected_start_ms, fb.corrected_end_ms = s.start_ms, s.end_ms  # guarda o original p/ aprendizagem
        s.start_ms, s.end_ms = body.start_ms, body.end_ms
        s.status = "adjusted"
    else:
        s.status = "accepted" if body.decision == "accept" else "rejected"
    db.add(fb)
    db.commit()
    return s


# ---- timeline
def _timeline_out(rev: TimelineRevision) -> schemas.TimelineOut:
    return schemas.TimelineOut(project_id=rev.project_id, revision=rev.revision, parent_revision=rev.parent_revision,
                               created_by=rev.created_by, created_at=rev.created_at, document=rev.document_json)


@router.get("/projects/{pid}/timeline", response_model=schemas.TimelineOut)
def get_timeline(pid: uuid.UUID, revision: int | None = None, db: Session = Depends(get_session)):
    p = _project(db, pid)
    rev = TS.get_revision(db, pid, revision if revision is not None else p.current_revision)
    if not rev:
        raise HTTPException(404, "timeline ainda não criada (use a operação init_main)")
    return _timeline_out(rev)


@router.get("/projects/{pid}/timeline/revisions", response_model=list[dict])
def list_revisions(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    rows = db.scalars(select(TimelineRevision).where(TimelineRevision.project_id == pid)
                      .order_by(TimelineRevision.revision)).all()
    return [{"revision": r.revision, "parent_revision": r.parent_revision, "created_by": r.created_by,
             "created_at": r.created_at.isoformat(), "duration_ms": r.document_json["duration_ms"]} for r in rows]


@router.post("/projects/{pid}/timeline/operations", response_model=schemas.TimelineOut)
def apply_operations(pid: uuid.UUID, body: schemas.OperationsIn, db: Session = Depends(get_session)):
    _project(db, pid)
    try:
        rev = TS.apply_operations(db, pid, body.expected_revision, body.operations)
    except TS.RevisionConflict as e:
        db.rollback()
        return JSONResponse(status_code=409, content={"detail": str(e), "code": "revision_conflict",
                                                      "current_revision": e.current})
    except T.TimelineError as e:
        db.rollback()
        return JSONResponse(status_code=422, content={"detail": e.message, "code": e.code})
    return _timeline_out(rev)


@router.get("/projects/{pid}/history", response_model=list[dict])
def history(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    rows = db.scalars(select(EditOperation).where(EditOperation.project_id == pid)
                      .order_by(EditOperation.timestamp, EditOperation.result_revision)).all()
    return [{"id": str(o.id), "base_revision": o.base_revision, "result_revision": o.result_revision, "type": o.type,
             "payload": o.payload, "actor": o.actor, "timestamp": o.timestamp.isoformat()} for o in rows]


# ---- render (preview e final independentes)
def enqueue_render(job_id: uuid.UUID) -> None:
    from app.workers.tasks import render_timeline
    render_timeline.send(str(job_id))


def _render_out(j: Job, current: int) -> schemas.RenderOut:
    return schemas.RenderOut(job_id=j.id, profile=j.params.get("profile", ""), state=j.state, progress=j.progress,
                             timeline_revision=j.timeline_revision, stale=(j.timeline_revision or 0) < current,
                             result=j.result, error=j.error, created_at=j.created_at)


@router.post("/projects/{pid}/renders", response_model=schemas.RenderOut, status_code=202)
def create_render(pid: uuid.UUID, body: schemas.RenderCreate, idempotency_key: str | None = Header(default=None),
                  db: Session = Depends(get_session)):
    """`final` NÃO exige preview anterior. Congela a revisão (snapshot) no momento do pedido."""
    p = _project(db, pid)
    rev_no = body.timeline_revision or p.current_revision
    if not rev_no or not TS.get_revision(db, pid, rev_no):
        raise HTTPException(409, "não há timeline para renderizar")
    if idempotency_key:
        prev = db.scalar(select(Job).where(Job.project_id == pid, Job.idempotency_key == idempotency_key))
        if prev:
            return _render_out(prev, p.current_revision)
    _quota(db, pid, ("render_preview", "render_final"), settings.max_active_render_jobs)
    job = J.create_job(db, pid, f"render_{body.profile}", {"profile": body.profile, "fit": body.fit}, idempotency_key)
    job.timeline_revision = rev_no
    db.commit()
    enqueue_render(job.id)
    return _render_out(job, p.current_revision)


@router.get("/projects/{pid}/renders", response_model=list[schemas.RenderOut])
def list_renders(pid: uuid.UUID, db: Session = Depends(get_session)):
    p = _project(db, pid)
    rows = db.scalars(select(Job).where(Job.project_id == pid, Job.kind.like("render_%"))
                      .order_by(Job.created_at.desc())).all()
    return [_render_out(j, p.current_revision) for j in rows]


@router.get("/renders/{jid}/artifact")
def render_artifact(jid: uuid.UUID, db: Session = Depends(get_session)):
    j = db.get(Job, jid)
    if not j or not j.kind.startswith("render_"):
        raise HTTPException(404, "render não encontrado")
    if j.state != "succeeded":
        raise HTTPException(409, f"render ainda não concluído (estado: {j.state})")
    token, exp = signing.sign(f"render:{j.id}")
    return {"url": f"/v1/dl/{token}", "expires_at": exp, "profile": j.result["profile"],
            "timeline_revision": j.timeline_revision}


public_router = APIRouter(prefix="/v1")


@public_router.get("/dl/{token}")
def download(token: str, db: Session = Depends(get_session)):
    """Download por URL assinada e temporária (sem Bearer, para <video>/<a download>)."""
    res = signing.verify(token)
    if not res:
        raise HTTPException(403, "link inválido ou expirado")
    kind, _, ident = res.partition(":")
    if kind == "render":
        j = db.get(Job, uuid.UUID(ident))
        if j and j.result and j.result.get("artifact_uri"):
            return FileResponse(storage.resolve(j.result["artifact_uri"]), media_type="video/mp4",
                                filename=f"{j.result['profile']}_r{j.timeline_revision}.mp4")
    if kind == "asset":
        aid, _, variant = ident.partition(":")
        a = db.get(Asset, uuid.UUID(aid))
        uri = a and {"original": a.uri, "proxy": a.proxy_uri or a.uri, "thumbnail": a.thumbnail_uri}.get(variant)
        if uri:
            return FileResponse(storage.resolve(uri))
    raise HTTPException(404, "arquivo não encontrado")


# ---- mídias: propostas de posicionamento (RF05) — só propõe, nunca aplica
def _aux_assets(db: Session, pid: uuid.UUID, only: list[uuid.UUID] | None) -> list[dict]:
    rows = db.scalars(select(Asset).where(Asset.project_id == pid, Asset.role == "auxiliary", Asset.status == "ready")).all()
    return [{"id": str(a.id), "filename": a.filename, "kind": a.kind, "tags": a.tags or [], "description": a.description,
             "duration_ms": a.duration_ms, "priority": a.priority, "intended_use": a.intended_use,
             "suggested_duration_ms": a.suggested_duration_ms} for a in rows if not only or a.id in only]


def _main_context(db: Session, pid: uuid.UUID):
    p = _project(db, pid)
    main = db.scalar(select(Asset).where(Asset.project_id == pid, Asset.role == "main", Asset.status == "ready")
                     .order_by(Asset.created_at))
    t = db.scalar(select(Transcript).where(Transcript.project_id == pid, Transcript.asset_id == main.id)
                  .order_by(Transcript.created_at.desc())) if main else None
    words = []
    if t:
        words = [{"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in
                 db.scalars(select(Word).where(Word.transcript_id == t.id).order_by(Word.idx))]
    rev = TS.get_revision(db, pid, p.current_revision) if p.current_revision else None
    return main, t, words, rev.document_json if rev else None


@router.post("/projects/{pid}/media/proposals")
def media_proposals(pid: uuid.UUID, body: schemas.ProposalsIn, db: Session = Depends(get_session)):
    main, t, words, doc = _main_context(db, pid)
    if not main or not t:
        raise HTTPException(409, "é preciso um vídeo principal transcrito para associar mídias à fala")
    assets = _aux_assets(db, pid, body.asset_ids)
    sem, rep = [], {"status": "disabled"}
    client = None if body.use_llm is False else llm.get_client()
    if body.use_llm and client is None:
        raise HTTPException(409, f"LLM não está disponível: {llm.status()['message']}")
    if client is not None:
        from app.services import llm_placement
        segs = [dict(s) for s in t.segments]
        sem, rep = llm_placement.semantic_candidates(client, words, segs, assets)
    out = placement.propose(words, t.segments, assets, doc, str(main.id), body.max_per_asset, semantic=sem)
    return {**out, "needs_timeline": doc is None, "applied": False, "llm": rep}


# ---- assistente por prompt (planner por regras; sem LLM)
@router.post("/projects/{pid}/assistant/plan")
def assistant_plan(pid: uuid.UUID, body: schemas.PlanIn, db: Session = Depends(get_session)):
    """Converte o prompt em operações estruturadas validadas por dry-run. Não aplica nada."""
    main, t, words, doc = _main_context(db, pid)
    sugg = [{"id": str(s.id), "status": s.status, "evidence": s.evidence} for s in
            db.scalars(select(Suggestion).where(Suggestion.project_id == pid))]
    client = None if body.use_llm is False else llm.get_client()
    if body.use_llm and client is None:
        raise HTTPException(409, f"LLM não está disponível: {llm.status()['message']}")
    return assistant.plan(body.prompt, {"doc": doc, "main_id": str(main.id) if main else None, "assets": _aux_assets(db, pid, None),
                                         "assets_map": TS.asset_map(db, pid), "words": words, "suggestions": sugg, "llm": client})


# ---- regras e memória (RF06)
def _rule(db: Session, pid: uuid.UUID, rid: uuid.UUID) -> EditingRule:
    r = db.get(EditingRule, rid)
    if not r or (r.project_id is not None and r.project_id != pid):
        raise HTTPException(404, "regra não encontrada")
    return r


@router.get("/projects/{pid}/rules", response_model=list[schemas.RuleOut])
def list_rules(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    return db.scalars(select(EditingRule).where((EditingRule.project_id == pid) | EditingRule.project_id.is_(None))
                      .order_by(EditingRule.created_at)).all()


@router.post("/projects/{pid}/rules", response_model=schemas.RuleOut, status_code=201)
def create_rule(pid: uuid.UUID, body: schemas.RuleIn, db: Session = Depends(get_session)):
    _project(db, pid)
    if body.kind != "note":
        ph = body.params.get("phrases")
        if not isinstance(ph, list) or not ph or not all(isinstance(x, str) and x.strip() for x in ph):
            raise HTTPException(422, "regras estruturadas exigem params.phrases (lista de frases)")
    prov = {"source": "manual", "created_by": "default", **(body.provenance or {})}
    r = EditingRule(project_id=None if body.scope == "user" else pid, scope=body.scope, kind=body.kind, text=body.text,
                    params=body.params, provenance=prov)
    db.add(r)
    db.commit()
    return r


@router.patch("/projects/{pid}/rules/{rid}", response_model=schemas.RuleOut)
def patch_rule(pid: uuid.UUID, rid: uuid.UUID, body: schemas.RulePatch, db: Session = Depends(get_session)):
    r = _rule(db, pid, rid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    return r


@router.delete("/projects/{pid}/rules/{rid}", status_code=204)
def delete_rule(pid: uuid.UUID, rid: uuid.UUID, db: Session = Depends(get_session)):
    db.delete(_rule(db, pid, rid))
    db.commit()


@router.get("/projects/{pid}/rules/suggested")
def suggested_rules(pid: uuid.UUID, db: Session = Depends(get_session)):
    _project(db, pid)
    return learning.suggest_rules(db, pid)


@router.get("/projects/{pid}/memory")
def memory(pid: uuid.UUID, db: Session = Depends(get_session)):
    """Auditoria da memória: exemplos de decisões do projeto e totais por regra."""
    _project(db, pid)
    ex = learning.load_examples(db, pid)
    totals: dict[str, dict[str, int]] = {}
    for e in ex:
        totals.setdefault(e["rule"] or "?", {}).setdefault(e["decision"], 0)
        totals[e["rule"] or "?"][e["decision"]] += 1
    return {"examples": ex, "totals": totals}
