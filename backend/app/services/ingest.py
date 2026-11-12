"""Ingestão: ffprobe, thumbnail e proxy. Executado no worker (ou direto nos testes)."""
import uuid

from app import media, storage
from app.db import SessionLocal
from app.models import Asset, Job
from app.services import jobs as J


def _ingest(db, job: Job, asset: Asset) -> None:
    src = storage.resolve(asset.uri)
    info = media.probe(src)
    asset.kind = info["kind"]
    for f in ("duration_ms", "width", "height", "fps_num", "fps_den", "audio_info"):
        setattr(asset, f, info.get(f))
    asset.probe = info["raw"]
    J.log(job, f"probe ok: {asset.kind}")
    J.set_state(db, job, "running", 0.3)

    base = storage.asset_dir(asset.project_id, asset.id)
    if asset.kind in ("video", "image"):
        at = min((asset.duration_ms or 0) // 10, 5000) if asset.kind == "video" else 0
        media.make_thumbnail(src, storage.resolve(f"{base}/thumb.jpg"), at)
        asset.thumbnail_uri = f"{base}/thumb.jpg"
    J.set_state(db, job, "running", 0.5)
    if asset.kind == "video":
        media.make_proxy(src, storage.resolve(f"{base}/proxy.mp4"), 480)
        asset.proxy_uri = f"{base}/proxy.mp4"
    asset.status = "ready"
    asset.error = None
    J.set_state(db, job, "succeeded", 1.0, result={"asset_id": str(asset.id), "kind": asset.kind})


def run_ingest(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.state in J.TERMINAL:
            return
        asset = db.get(Asset, uuid.UUID(job.params["asset_id"]))
        if job.cancel_requested:
            J.set_state(db, job, "cancelled")
            return
        J.set_state(db, job, "running", 0.05)
        asset.status = "processing"
        db.commit()
        with J.heartbeat(job.id):
            try:
                _ingest(db, job, asset)
            except Exception as e:  # falha não corrompe o projeto: só marca asset/job
                db.rollback()
                asset = db.get(Asset, asset.id)
                asset.status, asset.error = "failed", str(e)[:500]
                job = db.get(Job, job.id)
                J.set_state(db, job, "failed", error={"code": "ingest_failed", "message": str(e)[:500]})
