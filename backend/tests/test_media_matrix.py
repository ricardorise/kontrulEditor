"""Robustez de mídia: cada caso passa por ingestão → corte → render; mede duração, áudio e geometria."""
import subprocess

import pytest

from app import media, storage
from app.services.ingest import run_ingest
from app.services.render import run_render

SINE = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]


def V(size, rate):
    return ["-f", "lavfi", "-i", f"testsrc=size={size}:rate={rate}:duration=3"]


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def mk_vfr(p):
    # 25 fps no primeiro segundo, 10 fps depois (taxa variável de verdade)
    ff(*V("640x360", 50), *SINE, "-vf", "setpts='if(lt(N,50),N/50,1+(N-50)/20)/TB'",
       "-fps_mode", "vfr", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p))


def mk_hevc10(p):
    ff(*V("640x360", 25), *SINE, "-c:v", "libx265", "-pix_fmt", "yuv420p10le",
       "-x265-params", "log-level=none", "-c:a", "aac", "-shortest", str(p))


def mk_vp9_opus(p):
    ff(*V("640x360", 25), *SINE, "-c:v", "libvpx-vp9", "-deadline", "realtime",
       "-cpu-used", "8", "-c:a", "libopus", "-shortest", str(p))


def mk_mkv_mpeg4_mp3(p):
    ff(*V("640x360", 25), *SINE, "-c:v", "mpeg4", "-c:a", "libmp3lame", "-shortest", str(p))


def mk_surround(p):
    ff(*V("640x360", 25), "-f", "lavfi", "-i",
       "sine=frequency=440:duration=3,aformat=channel_layouts=5.1", "-c:v", "libx264", "-c:a", "ac3", "-shortest", str(p))


def mk_mono(p):
    ff(*V("640x360", 25), *SINE, "-ac", "1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p))


def mk_noaudio(p):
    ff(*V("640x360", 25), "-c:v", "libx264", str(p))


def mk_portrait(p):
    ff(*V("360x640", 25), *SINE, "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p))


def mk_anamorphic(p):
    # armazenado 320x360 com SAR 2:1 → exibe como 640x360
    ff(*V("320x360", 25), *SINE, "-vf", "setsar=2/1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p))


def mk_rotated(p, tmp):
    base = tmp / "base_rot.mp4"
    ff(*V("640x360", 25), *SINE, "-c:v", "libx264", "-c:a", "aac", "-shortest", str(base))
    ff("-display_rotation", "90", "-i", str(base), "-c", "copy", str(p))


CASES = {
    "vfr_h264": ("vfr.mp4", mk_vfr), "hevc_10bit": ("hevc.mp4", mk_hevc10), "vp9_opus_webm": ("v.webm", mk_vp9_opus),
    "mkv_mpeg4_mp3": ("m.mkv", mk_mkv_mpeg4_mp3), "surround_5_1": ("s.mp4", mk_surround), "mono": ("mono.mp4", mk_mono),
    "no_audio": ("na.mp4", mk_noaudio), "portrait": ("port.mp4", mk_portrait),
}


def pipeline(client, path, pid):
    with open(path, "rb") as f:
        up = client.post(f"/v1/projects/{pid}/assets", files={"file": (path.name, f)}).json()
    run_ingest(up["job"]["job_id"])
    a = client.get(f"/v1/projects/{pid}/assets").json()[-1]
    return a


def render_cut(client, pid, asset, profile="preview", **kw):
    ok = client.post(f"/v1/projects/{pid}/timeline/operations",
                     json={"expected_revision": 0, "operations": [{"type": "init_main", "asset_id": asset["id"]},
                                                                  {"type": "remove_range", "start_ms": 500, "end_ms": 1000}]})
    assert ok.status_code == 200, ok.text
    r = client.post(f"/v1/projects/{pid}/renders", json={"profile": profile, **kw}).json()
    run_render(r["job_id"])
    job = client.get(f"/v1/jobs/{r['job_id']}").json()
    return job, ok.json()["document"]["duration_ms"]


def streams(job):
    info = media.probe(storage.resolve(job["result"]["artifact_uri"]))
    s = {x["codec_type"]: x for x in info["raw"]["streams"]}
    return info, s


@pytest.mark.parametrize("name", list(CASES))
def test_media_case_full_pipeline(client, tmp_path, name):
    fname, maker = CASES[name]
    p = tmp_path / fname
    maker(p)
    pid = client.post("/v1/projects", json={"title": name}).json()["id"]
    a = pipeline(client, p, pid)
    assert a["status"] == "ready" and a["kind"] == "video", a
    job, expected = render_cut(client, pid, a)
    assert job["state"] == "succeeded", job["error"]
    info, s = streams(job)
    assert (info["width"], info["height"]) == (1280, 720)
    assert abs(info["duration_ms"] - expected) <= 150, (info["duration_ms"], expected)
    assert s["audio"]["channels"] == 2 and s["audio"]["codec_name"] == "aac"  # sempre estéreo, mesmo p/ mono/5.1/sem áudio
    assert abs(float(s["audio"]["duration"]) - float(s["video"]["duration"])) < 0.15  # sincronia
    assert 24.9 < eval(s["video"]["avg_frame_rate"]) < 60.1 if name != "vfr_h264" else True


def test_surround_downmix_is_not_silent(client, tmp_path):
    p = tmp_path / "s.mp4"
    mk_surround(p)
    pid = client.post("/v1/projects", json={"title": "s"}).json()["id"]
    a = pipeline(client, p, pid)
    job, _ = render_cut(client, pid, a)
    out = storage.resolve(job["result"]["artifact_uri"])
    vol = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mean = float(vol.split("mean_volume:")[1].split("dB")[0])
    assert mean > -40, vol[-300:]  # downmix 5.1→estéreo mantém sinal


def test_anamorphic_sar_is_respected(client, tmp_path):
    p = tmp_path / "ana.mp4"
    mk_anamorphic(p)
    pid = client.post("/v1/projects", json={"title": "ana"}).json()["id"]
    a = pipeline(client, p, pid)
    job, _ = render_cut(client, pid, a)
    assert job["state"] == "succeeded", job["error"]
    out = storage.resolve(job["result"]["artifact_uri"])
    px = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(out), "-frames:v", "1", "-vf", "crop=4:4:2:360,scale=1:1",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert sum(px[:3]) > 60, px[:3]  # borda esquerda tem imagem (sem barras laterais): SAR 2:1 → 16:9 cheio


def test_rotation_metadata_is_applied(client, tmp_path):
    p = tmp_path / "rot.mp4"
    mk_rotated(p, tmp_path)
    pid = client.post("/v1/projects", json={"title": "rot"}).json()["id"]
    a = pipeline(client, p, pid)
    job, _ = render_cut(client, pid, a)
    assert job["state"] == "succeeded", job["error"]
    out = storage.resolve(job["result"]["artifact_uri"])
    def px(x):
        return subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(out), "-frames:v", "1", "-vf",
                               f"crop=4:4:{x}:360,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout[:3]
    assert sum(px(2)) < 30      # vídeo girado vira retrato → barras pretas laterais em 16:9
    assert sum(px(640)) > 60    # centro tem imagem


def test_portrait_crop_fills_frame_letterbox_does_not(client, tmp_path):
    p = tmp_path / "port.mp4"
    mk_portrait(p)
    pid = client.post("/v1/projects", json={"title": "port"}).json()["id"]
    a = pipeline(client, p, pid)
    job, _ = render_cut(client, pid, a, fit="crop")
    out = storage.resolve(job["result"]["artifact_uri"])
    px = subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.2", "-i", str(out), "-frames:v", "1", "-vf", "crop=4:4:2:360,scale=1:1",
                         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout[:3]
    assert sum(px) > 60  # crop preenche o quadro (sem barras)


@pytest.mark.parametrize("kind", ["zero", "garbage", "truncated"])
def test_broken_files_fail_cleanly(client, tmp_path, kind):
    p = tmp_path / "x.mp4"
    if kind == "zero":
        p.write_bytes(b"")
    elif kind == "garbage":
        p.write_bytes(bytes(range(256)) * 100)
    else:
        full = tmp_path / "full.mp4"
        ff(*V("320x180", 25), "-c:v", "libx264", "-movflags", "+faststart", str(full))
        b = full.read_bytes()
        p.write_bytes(b[: len(b) // 3])
    pid = client.post("/v1/projects", json={"title": kind}).json()["id"]
    a = pipeline(client, p, pid)
    assert a["status"] == "failed" and a["error"]
    assert client.get(f"/v1/projects/{pid}").status_code == 200


def test_audio_only_main_renders_with_clear_error(client, tmp_path):
    p = tmp_path / "a.mp3"
    ff(*SINE, "-c:a", "libmp3lame", str(p))
    pid = client.post("/v1/projects", json={"title": "audio"}).json()["id"]
    a = pipeline(client, p, pid)
    assert a["kind"] == "audio" and a["status"] == "ready"
    ok = client.post(f"/v1/projects/{pid}/timeline/operations", json={"expected_revision": 0, "operations": [{"type": "init_main", "asset_id": a["id"]}]})
    assert ok.status_code == 200
    r = client.post(f"/v1/projects/{pid}/renders", json={"profile": "preview"}).json()
    run_render(r["job_id"])
    job = client.get(f"/v1/jobs/{r['job_id']}").json()
    assert job["state"] == "failed" and "vídeo" in job["error"]["message"]
