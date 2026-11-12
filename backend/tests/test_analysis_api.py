import uuid

from app.db import SessionLocal
from app.models import Asset, Transcript, Word
from app.services.analysis import run_analysis
from tests.helpers import build

ROTEIRO = "A nova versão chegou ao canal de testes públicos.\nEla traz uma gestão de janelas totalmente refeita.\n"


def _project_with_transcript(client):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    words, segs = build(["A nova versão chegou ao canal de testes públicos.",
                         "Ela traz uma gestão de janelas, ih, erro.",
                         "Ela traz uma gestão de janelas totalmente refeita."])
    with SessionLocal() as db:
        a = Asset(project_id=uuid.UUID(pid), filename="x.mp4", uri="x", kind="video", status="ready")
        db.add(a)
        db.flush()
        t = Transcript(project_id=a.project_id, asset_id=a.id, model_version="test", language="pt", segments=segs)
        db.add(t)
        db.flush()
        for i, w in enumerate(words):
            db.add(Word(transcript_id=t.id, idx=i, start_ms=w["start_ms"], end_ms=w["end_ms"], text=w["text"]))
        db.commit()
        return pid, str(t.id)


def test_script_upload_json_and_file(client, tmp_path):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    r = client.post(f"/v1/projects/{pid}/scripts", json={"text": ROTEIRO})
    assert r.status_code == 201 and r.json()["version"] == 1
    f = tmp_path / "r.md"
    f.write_text("# Roteiro\nTexto.", encoding="utf-8")
    with open(f, "rb") as fh:
        r2 = client.post(f"/v1/projects/{pid}/scripts", files={"file": ("r.md", fh)})
    assert r2.status_code == 201 and r2.json()["version"] == 2 and r2.json()["format"] == "md"
    with open(f, "rb") as fh:
        assert client.post(f"/v1/projects/{pid}/scripts", files={"file": ("r.exe", fh)}).status_code == 415
    assert client.post(f"/v1/projects/{pid}/scripts", json={"text": "  "}).status_code == 422
    assert len(client.get(f"/v1/projects/{pid}/scripts").json()) == 2


def test_analysis_with_script_and_decisions(client):
    pid, tid = _project_with_transcript(client)
    sid = client.post(f"/v1/projects/{pid}/scripts", json={"text": ROTEIRO}).json()["id"]
    job = client.post(f"/v1/projects/{pid}/analyses", json={"transcript_id": tid, "script_id": sid}).json()
    assert job["state"] == "queued"
    run_analysis(job["job_id"])
    assert client.get(f"/v1/jobs/{job['job_id']}").json()["state"] == "succeeded"
    sug = client.get(f"/v1/projects/{pid}/suggestions").json()
    assert len(sug) == 1 and sug[0]["category"] == "speech_error" and sug[0]["confidence"] is None
    assert sug[0]["evidence"]["level"] == "alta" and sug[0]["status"] == "pending"
    al = client.get(f"/v1/projects/{pid}/scripts/{sid}/alignment").json()
    assert [a["kind"] for a in al].count("matched") == 3

    sg = sug[0]["id"]
    adj = client.post(f"/v1/projects/{pid}/suggestions/{sg}/decision",
                      json={"decision": "adjust", "start_ms": 1000, "end_ms": 2000}).json()
    assert adj["status"] == "adjusted" and (adj["start_ms"], adj["end_ms"]) == (1000, 2000)
    assert client.post(f"/v1/projects/{pid}/suggestions/{sg}/decision",
                       json={"decision": "adjust", "start_ms": 5, "end_ms": 5}).status_code == 422
    assert client.post(f"/v1/projects/{pid}/suggestions/{sg}/decision", json={"decision": "accept"}).json()["status"] == "accepted"

    # reanálise preserva decisões do usuário e não duplica
    job2 = client.post(f"/v1/projects/{pid}/analyses", json={"transcript_id": tid}).json()
    run_analysis(job2["job_id"])
    sug2 = client.get(f"/v1/projects/{pid}/suggestions").json()
    assert sorted(s["status"] for s in sug2) == ["accepted", "pending"]


def test_analysis_without_script_works_and_manual_mode_does_not_cut(client):
    pid, tid = _project_with_transcript(client)
    job = client.post(f"/v1/projects/{pid}/analyses", json={"transcript_id": tid}).json()
    run_analysis(job["job_id"])
    sug = client.get(f"/v1/projects/{pid}/suggestions?status=pending").json()
    assert len(sug) == 1 and sug[0]["script_id"] is None
    assert client.get(f"/v1/projects/{pid}/timeline").status_code == 404  # nada foi aplicado automaticamente


def test_transcription_requires_ready_asset(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    with open(sample_video, "rb") as f:
        aid = client.post(f"/v1/projects/{pid}/assets", files={"file": ("a.mp4", f)}).json()["asset"]["id"]
    r = client.post(f"/v1/projects/{pid}/transcriptions", json={"asset_id": aid})
    assert r.status_code == 409  # ainda não ingerido


def test_cross_project_isolation(client):
    pid, tid = _project_with_transcript(client)
    other = client.post("/v1/projects", json={"title": "o"}).json()["id"]
    assert client.get(f"/v1/projects/{other}/transcriptions/{tid}").status_code == 404
    assert client.post(f"/v1/projects/{other}/analyses", json={"transcript_id": tid}).status_code == 404
