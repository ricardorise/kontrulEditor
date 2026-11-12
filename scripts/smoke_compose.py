"""Teste ponta a ponta contra o stack em execução (passa pelo nginx, como o navegador).

Uso: python scripts/smoke_compose.py [--url http://localhost:8080] [--video caminho.mp4] [--keep]
O token da API é injetado pelo nginx: este script não precisa dele. Deixa o projeto de demonstração pronto na UI.
"""
import argparse
import sys
import time

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080")
    ap.add_argument("--video", required=True, help="vídeo com fala (um trecho curto basta)")
    ap.add_argument("--title", default="Demo (smoke test)")
    ap.add_argument("--wait-asr", type=int, default=1800, help="tempo máximo da transcrição em segundos")
    a = ap.parse_args()
    c = httpx.Client(base_url=a.url, timeout=600)
    T0 = time.time()

    def step(msg: str) -> None:
        print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)

    def wait(job_id: str, limit: int = 600) -> dict:
        end = time.time() + limit
        while time.time() < end:
            j = c.get(f"/v1/jobs/{job_id}").json()
            if j["state"] in ("succeeded", "failed", "cancelled"):
                return j
            time.sleep(2)
        raise SystemExit(f"timeout aguardando job {job_id}")

    def ok(r: httpx.Response) -> dict:
        if r.status_code >= 400:
            raise SystemExit(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    html = c.get("/").text
    assert "Kontrul Editor" in html, "a UI não foi servida pelo nginx"
    ready = c.get("/health/ready").json()
    step(f"UI servida; readiness: {ready['status']} {ready['checks']}")
    assert ready["status"] == "ready", ready

    pid = ok(c.post("/v1/projects", json={"title": a.title}))["id"]
    with open(a.video, "rb") as f:
        up = ok(c.post(f"/v1/projects/{pid}/assets", files={"file": ("demo.mp4", f)}, data={"role": "main"}))
    j = wait(up["job"]["job_id"], 300)
    assert j["state"] == "succeeded", j
    aid = up["asset"]["id"]
    step("ingestão ok (probe, proxy, miniatura)")

    ok(c.post(f"/v1/projects/{pid}/timeline/operations", json={"expected_revision": 0, "operations": [{"type": "init_main", "asset_id": aid}]}))
    tj = ok(c.post(f"/v1/projects/{pid}/transcriptions", json={"asset_id": aid}))
    j = wait(tj["job_id"], a.wait_asr)
    assert j["state"] == "succeeded", j
    step(f"transcrição ok: {j['result']['words']} palavras")
    aj = ok(c.post(f"/v1/projects/{pid}/analyses", json={"transcript_id": j["result"]["transcript_id"]}))
    j2 = wait(aj["job_id"], 120)
    assert j2["state"] == "succeeded", j2
    sug = ok(c.get(f"/v1/projects/{pid}/suggestions"))
    step(f"análise ok: {len(sug)} sugestão(ões) {[(s['category'], s['start_ms'], s['end_ms']) for s in sug]}")

    errs = [s for s in sug if s["category"] == "speech_error"]
    for s in errs:
        ok(c.post(f"/v1/projects/{pid}/suggestions/{s['id']}/decision", json={"decision": "accept"}))
    rev = ok(c.get(f"/v1/projects/{pid}"))["current_revision"]
    if errs:
        t = ok(c.post(f"/v1/projects/{pid}/timeline/operations", json={"expected_revision": rev, "operations": [
            {"type": "apply_suggestion", "suggestion_id": s["id"]} for s in errs]}))
        step(f"{len(errs)} corte(s) aplicado(s): saída {t['document']['duration_ms'] / 1000:.1f}s (r{t['revision']})")

    rj = ok(c.post(f"/v1/projects/{pid}/renders", json={"profile": "preview"}))
    r = wait(rj["job_id"], 900)
    assert r["state"] == "succeeded", r
    res = r["result"]
    art = ok(c.get(f"/v1/renders/{rj['job_id']}/artifact"))
    dl = c.get(art["url"])
    assert dl.status_code == 200 and dl.content[4:8] == b"ftyp", "download do render não é um MP4"
    step(f"render preview ok: {res['width']}x{res['height']} {res['duration_ms'] / 1000:.1f}s, baixado {len(dl.content) / 1e6:.1f} MB via nginx")

    m = c.get("/v1/metrics").text
    assert "kontrul_jobs" in m
    print(f"\nSMOKE OK em {time.time() - T0:.0f}s — projeto {pid} ({a.title}) disponível em {a.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
