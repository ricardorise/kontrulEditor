import subprocess

import pytest

from app import media, storage
from app.services.render import run_ffmpeg, run_render


def ops(client, pid, rev, *operations):
    r = client.post(f"/v1/projects/{pid}/timeline/operations", json={"expected_revision": rev, "operations": list(operations)})
    return r


def render(client, pid, profile, **kw):
    r = client.post(f"/v1/projects/{pid}/renders", json={"profile": profile, **kw})
    assert r.status_code == 202, r.text
    run_render(r.json()["job_id"])
    return client.get(f"/v1/jobs/{r.json()['job_id']}").json(), r.json()["job_id"]


def probe_out(job):
    return media.probe(storage.resolve(job["result"]["artifact_uri"]))


def center_pixel(path, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf",
                          "crop=8:8:(iw-8)/2:(ih-8)/2,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return tuple(raw[:3])


def test_timeline_api_flow_conflict_and_errors(client, ready):
    pid, ids = ready
    assert client.get(f"/v1/projects/{pid}/timeline").status_code == 404
    r = ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    assert r.status_code == 200 and r.json()["revision"] == 1 and r.json()["document"]["duration_ms"] > 2800
    # conflito de concorrência: expected_revision defasado
    c = ops(client, pid, 0, {"type": "remove_range", "start_ms": 500, "end_ms": 1000})
    assert c.status_code == 409 and c.json()["current_revision"] == 1
    # operação inválida não cria revisão
    assert ops(client, pid, 1, {"type": "remove_range", "start_ms": 900, "end_ms": 100}).status_code == 422
    assert ops(client, pid, 1, {"type": "nope"}).status_code == 422
    assert client.get(f"/v1/projects/{pid}").json()["current_revision"] == 1
    # lote atômico: se uma falha, nenhuma é aplicada
    bad = ops(client, pid, 1, {"type": "remove_range", "start_ms": 500, "end_ms": 1000}, {"type": "split", "clip_id": "x", "at_ms": 1})
    assert bad.status_code == 422 and client.get(f"/v1/projects/{pid}").json()["current_revision"] == 1
    ok = ops(client, pid, 1, {"type": "remove_range", "start_ms": 500, "end_ms": 1000})
    assert ok.json()["revision"] == 2
    # revisões são imutáveis e consultáveis; undo = revert_to cria nova revisão
    assert client.get(f"/v1/projects/{pid}/timeline?revision=1").json()["document"]["duration_ms"] > 2800
    undo = ops(client, pid, 2, {"type": "revert_to", "revision": 1})
    assert undo.json()["revision"] == 3 and undo.json()["document"]["duration_ms"] > 2800
    assert [h["type"] for h in client.get(f"/v1/projects/{pid}/history").json()] == ["init_main", "remove_range", "revert_to"]
    assert len(client.get(f"/v1/projects/{pid}/timeline/revisions").json()) == 3


def test_suggestion_must_be_accepted_before_cut(client, ready):
    import uuid
    from app.db import SessionLocal
    from app.models import Suggestion
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    with SessionLocal() as db:
        s = Suggestion(project_id=uuid.UUID(pid), asset_id=uuid.UUID(ids["main"]), start_ms=1000, end_ms=2000,
                       category="speech_error", rationale="t")
        db.add(s)
        db.commit()
        sid = str(s.id)
    # modo manual: sugestão pendente nunca vira corte
    assert ops(client, pid, 1, {"type": "apply_suggestion", "suggestion_id": sid}).json()["code"] == "suggestion_not_accepted"
    client.post(f"/v1/projects/{pid}/suggestions/{sid}/decision", json={"decision": "accept"})
    r = ops(client, pid, 1, {"type": "apply_suggestion", "suggestion_id": sid, "handle_ms": 100})
    assert r.status_code == 200
    d = r.json()["document"]
    assert 2100 <= d["duration_ms"] <= 2300  # ~800 ms removidos ([1100,1900) com margem de 100 ms)


def test_preview_and_final_same_cuts_different_quality_and_final_without_preview(client, ready):
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    ops(client, pid, 1, {"type": "remove_range", "start_ms": 1000, "end_ms": 2000})
    final, fid = render(client, pid, "final")  # SEM preview anterior
    assert final["state"] == "succeeded", final
    prev, _ = render(client, pid, "preview")
    assert prev["state"] == "succeeded", prev
    pf, pp = probe_out(final), probe_out(prev)
    assert (pf["width"], pf["height"]) == (1920, 1080) and (pp["width"], pp["height"]) == (1280, 720)
    expected = 3000 - 1000  # fonte ~3 s menos 1 s cortado
    for p in (pf, pp):
        assert abs(p["duration_ms"] - expected) <= 120, p["duration_ms"]
    assert abs(pf["duration_ms"] - pp["duration_ms"]) <= 40  # montagem equivalente
    assert pf["audio_info"] and abs(pf["fps_num"] / pf["fps_den"] - 25) < 0.1
    # sincronia: duração de áudio ≈ duração de vídeo
    a = {s["codec_type"]: float(s.get("duration", 0)) for s in pf["raw"]["streams"]}
    assert abs(a["audio"] - a["video"]) < 0.12


def test_stale_flag_and_signed_download(client, ready):
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    prev, jid = render(client, pid, "preview")
    assert client.get(f"/v1/projects/{pid}/renders").json()[0]["stale"] is False
    ops(client, pid, 1, {"type": "remove_range", "start_ms": 0, "end_ms": 500})
    assert client.get(f"/v1/projects/{pid}/renders").json()[0]["stale"] is True  # aviso, sem bloquear
    url = client.get(f"/v1/renders/{jid}/artifact").json()["url"]
    r = client.get(url, headers={"Authorization": ""})  # sem Bearer
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) > 1000
    assert client.get(url[:-3] + "xxx").status_code == 403
    assert client.get("/v1/renders/" + jid + "/artifact", headers={"Authorization": "Bearer x"}).status_code == 401


def test_overlay_b_roll_and_pip_are_composited(client, ready):
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    r = ops(client, pid, 1, {"type": "insert_overlay", "asset_id": ids["img"], "timeline_start_ms": 1000,
                             "duration_ms": 1000, "mode": "b_roll"})
    assert r.status_code == 200
    job, _ = render(client, pid, "preview")
    assert job["state"] == "succeeded", job
    out = storage.resolve(job["result"]["artifact_uri"])
    red = center_pixel(out, 1.5)   # dentro do overlay: imagem vermelha no centro
    base = center_pixel(out, 0.3)  # fora: padrão de teste do vídeo
    assert red[0] > 180 and red[1] < 90 and red[2] < 90, red
    assert base != red
    # PiP: imagem pequena no canto; centro continua sendo o vídeo
    r = ops(client, pid, 2, {"type": "insert_overlay", "asset_id": ids["img"], "timeline_start_ms": 0, "duration_ms": 800,
                             "mode": "pip", "track_id": "overlay-2"})
    assert r.status_code == 200
    job2, _ = render(client, pid, "preview")
    assert job2["state"] == "succeeded", job2


def test_crop_fit_policy(client, ready):
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    job, _ = render(client, pid, "preview", fit="crop")
    assert job["state"] == "succeeded"
    assert client.post(f"/v1/projects/{pid}/renders", json={"profile": "preview", "fit": "stretch"}).status_code == 422


def test_render_requires_timeline_and_failure_does_not_corrupt_project(client, ready):
    pid, ids = ready
    assert client.post(f"/v1/projects/{pid}/renders", json={"profile": "final"}).status_code == 409
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    from app.db import SessionLocal
    from app.models import Asset
    import uuid
    with SessionLocal() as db:
        storage.resolve(db.get(Asset, uuid.UUID(ids["main"])).uri).write_bytes(b"corrompido")  # arquivo quebra
    job, _ = render(client, pid, "preview")
    assert job["state"] == "failed" and job["error"]["code"] == "render_failed"
    assert str(storage.root()) not in job["error"]["message"]  # log sanitizado
    assert client.get(f"/v1/projects/{pid}/timeline").json()["revision"] == 1  # timeline intacta


def test_cancel_during_ffmpeg(tmp_path):
    args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc=d=120:r=25", "-f", "null",
            "-progress", "pipe:1", "-nostats", "-"]
    import time
    t = time.time()
    assert run_ffmpeg(args, 120_000, tmp_path / "err.log", lambda p: None, lambda: True) == "cancelled"
    assert time.time() - t < 8


def test_idempotent_render_request(client, ready):
    pid, ids = ready
    ops(client, pid, 0, {"type": "init_main", "asset_id": ids["main"]})
    h = {"Idempotency-Key": "r1"}
    a = client.post(f"/v1/projects/{pid}/renders", json={"profile": "preview"}, headers=h).json()
    b = client.post(f"/v1/projects/{pid}/renders", json={"profile": "preview"}, headers=h).json()
    assert a["job_id"] == b["job_id"] and len(client.get(f"/v1/projects/{pid}/renders").json()) == 1
