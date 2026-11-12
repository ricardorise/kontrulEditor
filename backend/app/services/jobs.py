import contextlib
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job

logger = logging.getLogger("kontrul.jobs")

TERMINAL = {"succeeded", "failed", "cancelled"}


def create_job(db: Session, project_id: uuid.UUID, kind: str, params: dict | None = None,
               idempotency_key: str | None = None) -> Job:
    job = Job(project_id=project_id, kind=kind, params=params or {}, idempotency_key=idempotency_key)
    db.add(job)
    db.flush()
    return job


def log(job: Job, msg: str) -> None:
    job.log = [*job.log, {"t": datetime.now(timezone.utc).isoformat(), "msg": msg[:500]}][-200:]


def set_state(db: Session, job: Job, state: str, progress: float | None = None, **kw) -> None:
    job.state = state
    if progress is not None:
        job.progress = progress
    for k, v in kw.items():
        setattr(job, k, v)
    db.commit()
    if state != "running" or (progress or 0) <= 0.05:  # transições, sem inundar com cada passo de progresso
        logger.info("job %s", state, extra={"job_id": str(job.id), "project_id": str(job.project_id), "kind": job.kind, "state": state})


@contextlib.contextmanager
def heartbeat(job_id: uuid.UUID, interval_s: float | None = None):
    """Toca `updated_at` de tempos em tempos enquanto o job roda, mesmo sem progresso visível (ex.: transcrição longa).
    Sem heartbeat o reaper trata o job como de worker perdido."""
    from app.db import engine
    stop = threading.Event()
    every = interval_s if interval_s is not None else settings.heartbeat_s

    def beat():
        while not stop.wait(every):
            try:
                with engine.begin() as c:
                    c.execute(text("UPDATE jobs SET updated_at = now() WHERE id = :i AND state = 'running'"), {"i": job_id})
            except Exception:  # heartbeat nunca derruba o job
                logger.warning("heartbeat falhou", exc_info=True)

    t = threading.Thread(target=beat, daemon=True, name=f"hb-{job_id}")
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join(timeout=2)


def reap_stale(db: Session, max_age_s: int | None = None) -> int:
    """Marca como falhos os jobs 'running' sem heartbeat (worker morto/reiniciado). O usuário pode usar retry."""
    limit = datetime.now(timezone.utc) - timedelta(seconds=max_age_s if max_age_s is not None else settings.job_stale_s)
    stale = db.scalars(select(Job).where(Job.state == "running", Job.updated_at < limit)).all()
    for j in stale:
        j.state = "failed"
        j.error = {"code": "worker_lost", "message": "O worker parou de responder durante este job. Use «tentar de novo»."}
        log(j, "reaper: worker perdido")
        logger.warning("job %s (%s) marcado como worker_lost", j.id, j.kind, extra={"job_id": str(j.id), "project_id": str(j.project_id)})
    db.commit()
    return len(stale)


def start_reaper(interval_s: float = 30.0) -> threading.Event:
    from app.db import SessionLocal
    stop = threading.Event()

    def loop():
        while not stop.wait(interval_s):
            try:
                with SessionLocal() as db:
                    reap_stale(db)
            except Exception:
                logger.warning("reaper falhou", exc_info=True)

    threading.Thread(target=loop, daemon=True, name="reaper").start()
    return stop
