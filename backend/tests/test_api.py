from app.services.ingest import run_ingest
from app import storage


def _upload(client, pid, path, **data):
    with open(path, "rb") as f:
        r = client.post(f"/v1/projects/{pid}/assets", files={"file": (path.name, f)}, data=data)
    assert r.status_code == 202, r.text
    return r.json()


def test_auth_required(client):
    assert client.get("/v1/projects", headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/health").status_code == 200


def test_project_crud(client):
    r = client.post("/v1/projects", json={"title": "Ep 1"})
    assert r.status_code == 201
    pid = r.json()["id"]
    assert client.patch(f"/v1/projects/{pid}", json={"title": "Ep 1b"}).json()["title"] == "Ep 1b"
    assert client.get("/v1/projects/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.post("/v1/projects", json={"title": ""}).status_code == 422


def test_ingest_video(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    out = _upload(client, pid, sample_video, tags="a, b")
    assert out["job"]["state"] == "queued" and out["asset"]["tags"] == ["a", "b"]
    run_ingest(out["job"]["job_id"])
    job = client.get(f"/v1/jobs/{out['job']['job_id']}").json()
    assert job["state"] == "succeeded" and job["progress"] == 1.0
    a = client.get(f"/v1/projects/{pid}/assets").json()[0]
    assert a["status"] == "ready" and a["kind"] == "video"
    assert (a["width"], a["height"]) == (640, 360) and a["fps_num"] == 25
    assert 2800 <= a["duration_ms"] <= 3300 and a["has_proxy"] and a["has_thumbnail"]
    assert client.get(f"/v1/projects/{pid}/assets/{a['id']}/file?variant=proxy").status_code == 200
    # original preservado
    assert storage.resolve(f"projects/{pid}/assets/{a['id']}/original/amostra.mp4").exists()


def test_ingest_image(client, sample_image):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    out = _upload(client, pid, sample_image, role="auxiliary")
    run_ingest(out["job"]["job_id"])
    a = client.get(f"/v1/projects/{pid}/assets").json()[0]
    assert a["kind"] == "image" and a["status"] == "ready" and not a["has_proxy"] and a["has_thumbnail"]


def test_corrupt_file_fails_without_breaking_project(client, tmp_path):
    bad = tmp_path / "ruim.mp4"
    bad.write_bytes(b"nao sou um video")
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    out = _upload(client, pid, bad)
    run_ingest(out["job"]["job_id"])
    assert client.get(f"/v1/jobs/{out['job']['job_id']}").json()["state"] == "failed"
    assert client.get(f"/v1/projects/{pid}/assets").json()[0]["status"] == "failed"
    assert client.get(f"/v1/projects/{pid}").status_code == 200


def test_idempotent_upload(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    h = {"Idempotency-Key": "k1"}
    for _ in range(2):
        with open(sample_video, "rb") as f:
            client.post(f"/v1/projects/{pid}/assets", files={"file": ("a.mp4", f)}, headers=h)
    assert len(client.get(f"/v1/projects/{pid}/assets").json()) == 1


def test_cancel_queued_job(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    out = _upload(client, pid, sample_video)
    jid = out["job"]["job_id"]
    assert client.post(f"/v1/jobs/{jid}/cancel").json()["state"] == "cancelled"
    run_ingest(jid)  # worker não deve processar job cancelado
    assert client.get(f"/v1/jobs/{jid}").json()["state"] == "cancelled"


def test_path_traversal_filename(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    with open(sample_video, "rb") as f:
        r = client.post(f"/v1/projects/{pid}/assets", files={"file": ("../../evil.mp4", f)})
    assert r.status_code == 202 and r.json()["asset"]["filename"] == "evil.mp4"
    assert not (storage.root().parent / "evil.mp4").exists()


def test_signed_asset_url_range_and_waveform(client, sample_video):
    pid = client.post("/v1/projects", json={"title": "t"}).json()["id"]
    out = _upload(client, pid, sample_video)
    run_ingest(out["job"]["job_id"])
    aid = out["asset"]["id"]
    url = client.get(f"/v1/projects/{pid}/assets/{aid}/file-url?variant=proxy").json()["url"]
    full = client.get(url, headers={"Authorization": ""})
    assert full.status_code == 200
    part = client.get(url, headers={"Authorization": "", "Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100  # o player precisa de Range para seek
    assert client.get(f"/v1/projects/{pid}/assets/{aid}/file-url?variant=nada").status_code == 404
    wf = client.get(f"/v1/projects/{pid}/assets/{aid}/waveform").json()
    assert wf["peaks_per_second"] == 50 and 140 <= len(wf["peaks"]) <= 155 and max(wf["peaks"]) > 20
