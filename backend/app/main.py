import asyncio
import contextlib
import logging
import os
import shutil

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from app import observability
from app.api.routes import public_router, router
from app.config import settings
from app.db import engine
from app.services import jobs

DEFAULT_TOKEN = "dev-token-change-me"
log = logging.getLogger("kontrul")


def check_config() -> None:
    """Em produção, recusa subir com token padrão/fraco: o token também assina as URLs de download."""
    if settings.env == "production" and (settings.api_token == DEFAULT_TOKEN or len(settings.api_token) < 24):
        raise RuntimeError("KONTRUL_API_TOKEN fraco/padrão em produção: defina um token com 24+ caracteres")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    check_config()
    observability.setup_logging()
    stop = jobs.start_reaper()
    log.info("api iniciada", extra={"env": settings.env})
    yield
    stop.set()


app = FastAPI(title="KontrulEditor API", version="0.1.0", lifespan=lifespan)
observability.install(app)
app.include_router(router)
app.include_router(public_router)


@app.exception_handler(sa_exc.TimeoutError)
async def pool_exhausted(request, exc):
    """Pool de conexões esgotado: falha rápida e explícita (o cliente pode tentar de novo) em vez de travar."""
    log.error("pool de conexões esgotado", extra={"path": request.url.path})
    return JSONResponse(status_code=503, content={"detail": "servidor sobrecarregado; tente novamente", "code": "overloaded"},
                        headers={"Retry-After": "2"})


@app.get("/health", tags=["infra"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["infra"])
def ready():
    """Prontidão real: banco, Redis, FFmpeg, storage gravável e GPU (informativo)."""
    checks: dict[str, object] = {}
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        checks["database"] = True
    except Exception as e:
        checks["database"] = f"erro: {type(e).__name__}"
    try:
        import redis
        checks["redis"] = bool(redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping())
    except Exception as e:
        checks["redis"] = f"erro: {type(e).__name__}"
    checks["ffmpeg"] = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    if checks["ffmpeg"]:  # o render usa `-/filter_complex`, que exige FFmpeg >= 7
        import re
        import subprocess
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout
        m = re.search(r"version\s+n?(\d+)", out)
        checks["ffmpeg_version"] = m.group(0).split()[-1] if m else "?"
        checks["ffmpeg"] = bool(m and int(m.group(1)) >= 7)
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        checks["storage_writable"] = os.access(settings.data_dir, os.W_OK)
    except Exception:
        checks["storage_writable"] = False
    # Informativo: /proc/driver/nvidia aparece em qualquer contêiner. O acesso real à GPU é do worker-asr (veja o log dele).
    checks["nvidia_driver_visible"] = os.path.exists("/proc/driver/nvidia/version")
    ok = all(checks[k] is True for k in ("database", "redis", "ffmpeg", "storage_writable"))
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)
