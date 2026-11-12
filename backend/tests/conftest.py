import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings

TEST_DB = "kontrul_test"
_base = make_url(settings.database_url)
settings.database_url = _base.set(database=TEST_DB).render_as_string(hide_password=False)

import app.db as appdb  # noqa: E402

admin = create_engine(_base.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
with admin.connect() as c:
    if not c.scalar(text("select 1 from pg_database where datname=:n"), {"n": TEST_DB}):
        c.execute(text(f"create database {TEST_DB}"))
appdb.engine.dispose()
appdb.engine = create_engine(settings.database_url)
appdb.SessionLocal.configure(bind=appdb.engine)

from app import models  # noqa: E402,F401
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def schema(tmp_path, monkeypatch):
    settings.data_dir = tmp_path / "data"
    appdb.Base.metadata.drop_all(appdb.engine)
    appdb.Base.metadata.create_all(appdb.engine)
    for fn in ("enqueue_ingest", "enqueue_transcribe", "enqueue_analyze", "enqueue_render"):
        monkeypatch.setattr(f"app.api.routes.{fn}", lambda job_id: None)  # nada vai para a fila real
    monkeypatch.setattr(settings, "final_preset", "ultrafast")
    yield


@pytest.fixture
def client():
    return TestClient(app, headers={"Authorization": f"Bearer {settings.api_token}"})


@pytest.fixture
def sample_video(tmp_path):
    p = tmp_path / "amostra.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25:duration=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac",
                    "-shortest", str(p)], check=True)
    return p


@pytest.fixture
def sample_image(tmp_path):
    p = tmp_path / "img.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240", "-frames:v", "1",
                    str(p)], check=True)
    return p


@pytest.fixture
def ready(client, sample_video, sample_image):
    """Projeto com vídeo principal (3 s, 640x360@25, com áudio) e imagem auxiliar já ingeridos."""
    from app.services.ingest import run_ingest
    pid = client.post("/v1/projects", json={"title": "render"}).json()["id"]
    ids = {}
    for name, path, role in (("main", sample_video, "main"), ("img", sample_image, "auxiliary")):
        with open(path, "rb") as f:
            out = client.post(f"/v1/projects/{pid}/assets", files={"file": (path.name, f)}, data={"role": role}).json()
        run_ingest(out["job"]["job_id"])
        ids[name] = out["asset"]["id"]
    return pid, ids
