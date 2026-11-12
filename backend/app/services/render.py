"""Compilador timeline → FFmpeg e execução do render.

Preview e final usam EXATAMENTE a mesma montagem (mesma revisão, mesmos cortes e overlays); só o perfil
(resolução/qualidade) muda. Argumentos vão como lista (sem shell); o filtergraph só contém números e rótulos
gerados aqui, nunca texto vindo do usuário/LLM, e é passado por arquivo.
"""
import subprocess
import threading
import time
import uuid
from fractions import Fraction
from pathlib import Path

from app import media, storage
from app.media import SAFE_IN, die_with_parent
from app.config import settings
from app.db import SessionLocal
from app.models import Job
from app.services import jobs as J
from app.services import timeline as T
from app.services.timeline_service import asset_map, get_revision

FITS = ("letterbox", "crop")


class RenderError(Exception):
    pass


def profile_spec(profile: str) -> dict:
    if profile == "final":
        return {"w": 1920, "h": 1080, "preset": settings.final_preset, "crf": settings.final_crf, "abr": "192k"}
    if profile == "preview":
        h = settings.preview_height // 2 * 2
        return {"w": round(h * 16 / 9 / 2) * 2, "h": h, "preset": settings.preview_preset,
                "crf": settings.preview_crf, "abr": "128k"}
    raise RenderError(f"perfil desconhecido: {profile}")


def _fps(doc: dict, assets: dict) -> str:
    main = T.main_clips(doc)
    a = assets[main[0]["asset_id"]]
    fr = Fraction(a["fps_num"], a["fps_den"]) if a.get("fps_num") and a.get("fps_den") else Fraction(30)
    if fr > settings.max_fps or fr <= 0:
        fr = Fraction(settings.max_fps) if fr > 0 else Fraction(30)
    return f"{fr.numerator}/{fr.denominator}"


def _s(ms: int) -> str:
    return f"{ms / 1000:.3f}"


# Normaliza pixels não quadrados (anamórfico, SAR≠1) para a proporção de exibição antes de ajustar ao quadro.
SAR_FIX = "scale=trunc(iw*sar/2)*2:ih,setsar=1"


def _fit_chain(w: int, h: int, fit: str) -> str:
    if fit == "crop":
        return f"{SAR_FIX},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    return f"{SAR_FIX},scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"


def build_command(doc: dict, assets: dict, profile: str, fit: str, out_path: Path, graph_path: Path) -> tuple[list[str], int]:
    if fit not in FITS:
        raise RenderError(f"fit inválido: {fit}")
    mains = T.main_clips(doc)
    if not mains:
        raise RenderError("timeline vazia")
    spec, fps = profile_spec(profile), _fps(doc, assets)
    W, H = spec["w"], spec["h"]
    total = doc["duration_ms"]
    inputs: list[str] = []
    parts: list[str] = []

    def add_input(c: dict) -> int:
        a = assets[c["asset_id"]]
        path = str(storage.resolve(a["uri"]))
        d = _s(c["duration_ms"])
        if a["kind"] == "image":
            inputs.extend([*SAFE_IN, "-loop", "1", "-framerate", fps, "-t", d, "-i", path])
        elif a["kind"] == "video":
            inputs.extend([*SAFE_IN, "-ss", _s(c["source_in_ms"]), "-t", d, "-i", path])
        else:
            raise RenderError("clip de vídeo precisa referenciar vídeo ou imagem")
        return inputs.count("-i") - 1

    vlabels = []
    for i, c in enumerate(mains):
        k = add_input(c)
        d = _s(c["duration_ms"])
        parts.append(f"[{k}:v:0]{_fit_chain(W, H, fit)},setsar=1,fps={fps},format=yuv420p,"
                     f"trim=duration={d},setpts=PTS-STARTPTS[v{i}]")
        a = assets[c["asset_id"]]
        if a["kind"] == "video" and a.get("audio_info"):
            parts.append(f"[{k}:a:0]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"apad=whole_dur={d},atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]")
        else:  # sem áudio de origem: silêncio, para não perder a sincronia na concatenação
            parts.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d},asetpts=PTS-STARTPTS[a{i}]")
        vlabels.append(f"[v{i}][a{i}]")
    ovs = T.overlay_clips(doc)
    vm = "[vout]" if not ovs else "[vm]"
    parts.append(f"{''.join(vlabels)}concat=n={len(mains)}:v=1:a=1{vm}[am]")

    prev = "[vm]"
    for j, c in enumerate(ovs):
        k = add_input(c)
        d, start, end = _s(c["duration_ms"]), _s(c["timeline_start_ms"]), _s(c["timeline_start_ms"] + c["duration_ms"])
        if c["mode"] == "pip":
            pw = W // 4 // 2 * 2
            scale, x, y = f"{SAR_FIX},scale={pw}:-2", f"main_w-overlay_w-{round(W * 0.03)}", f"main_h-overlay_h-{round(H * 0.03)}"
        else:
            scale, x, y = _fit_chain(W, H, fit), "0", "0"
        parts.append(f"[{k}:v:0]{scale},setsar=1,fps={fps},format=yuv420p,trim=duration={d},"
                     f"setpts=PTS-STARTPTS+{start}/TB[ov{j}]")
        nxt = "[vout]" if j == len(ovs) - 1 else f"[vo{j}]"
        parts.append(f"{prev}[ov{j}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{start},{end})'{nxt}")
        prev = nxt
    graph_path.write_text(";\n".join(parts), encoding="utf-8")
    args = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-v", "error", *inputs, "-/filter_complex", str(graph_path),
            "-map", "[vout]", "-map", "[am]", "-c:v", "libx264", "-preset", spec["preset"], "-crf", str(spec["crf"]),
            "-pix_fmt", "yuv420p", "-r", fps, "-c:a", "aac", "-b:a", spec["abr"], "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-t", _s(total), "-progress", "pipe:1", "-nostats", str(out_path)]
    return args, total


def run_ffmpeg(args: list[str], total_ms: int, stderr_path: Path, on_progress, is_cancelled,
               timeout_s: float | None = None) -> str:
    """Devolve 'ok' | 'cancelled' | 'failed' | 'timeout'. O watchdog mata o FFmpeg mesmo que ele pare de emitir progresso."""
    with open(stderr_path, "wb") as err:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, text=True, preexec_fn=die_with_parent)
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            proc.kill()

        watchdog = threading.Timer(timeout_s if timeout_s is not None else settings.render_timeout_s, _kill)
        watchdog.daemon = True
        watchdog.start()
        try:
            return _pump(proc, total_ms, on_progress, is_cancelled, timed_out)
        finally:
            watchdog.cancel()


def _pump(proc, total_ms: int, on_progress, is_cancelled, timed_out) -> str:
    last = 0.0
    for line in proc.stdout:
        if line.startswith("out_time_us=") and line.strip().split("=")[1].lstrip("-").isdigit():
            now = time.monotonic()
            if now - last >= 1.0:
                last = now
                on_progress(min(0.99, int(line.split("=")[1]) / 1000 / max(total_ms, 1)))
                if is_cancelled():
                    proc.terminate()
                    try:
                        proc.wait(10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return "cancelled"
    rc = proc.wait()
    return "timeout" if timed_out.is_set() else "ok" if rc == 0 else "failed"


def _clean_log(text: str) -> str:
    return text.replace(str(storage.root()), "<data>")[-800:]


def run_render(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.state in J.TERMINAL:
            return
        out_dir = storage.resolve(f"projects/{job.project_id}/renders/{job.id}")
        try:
            profile, fit = job.params["profile"], job.params.get("fit", "letterbox")
            rev = get_revision(db, job.project_id, job.timeline_revision)  # snapshot imutável
            if not rev:
                raise RenderError("revisão da timeline não existe")
            assets = asset_map(db, job.project_id)
            doc = rev.document_json
            T.validate(doc, assets)
            out_dir.mkdir(parents=True, exist_ok=True)
            partial, final = out_dir / f"{profile}.partial.mp4", out_dir / f"{profile}.mp4"
            args, total = build_command(doc, assets, profile, fit, partial, out_dir / "graph.txt")
            J.set_state(db, job, "running", 0.02)

            def progress(p: float) -> None:
                job.progress = p
                db.commit()

            def cancelled() -> bool:
                db.refresh(job)
                return job.cancel_requested

            with J.heartbeat(job.id):
                status = run_ffmpeg(args, total, out_dir / "ffmpeg.log", progress, cancelled)
            if status == "cancelled":
                partial.unlink(missing_ok=True)
                J.set_state(db, job, "cancelled")
                return
            if status == "timeout":
                partial.unlink(missing_ok=True)
                raise RenderError(f"render excedeu o tempo limite ({settings.render_timeout_s}s) e foi interrompido")
            if status == "failed":
                partial.unlink(missing_ok=True)
                tail = (out_dir / "ffmpeg.log").read_text(errors="replace")
                raise RenderError(_clean_log(tail) or "ffmpeg falhou")
            partial.replace(final)
            info = media.probe(final)
            spec = profile_spec(profile)
            J.set_state(db, job, "succeeded", 1.0, result={
                "artifact_uri": f"projects/{job.project_id}/renders/{job.id}/{profile}.mp4", "profile": profile,
                "timeline_revision": job.timeline_revision, "expected_ms": total, "duration_ms": info["duration_ms"],
                "width": spec["w"], "height": spec["h"], "size_bytes": final.stat().st_size})
        except Exception as e:  # falha de render não toca no projeto nem na timeline
            db.rollback()
            job = db.get(Job, job.id)
            J.set_state(db, job, "failed", error={"code": "render_failed", "message": _clean_log(str(e))})
