"""Wrappers FFmpeg/FFprobe. Sempre lista de argumentos, nunca shell."""
import json
import subprocess
from fractions import Fraction
from pathlib import Path

# Segurança: arquivos enviados pelo usuário nunca podem fazer o FFmpeg abrir rede, playlists (HLS/DASH), listas
# `concat`, SDP etc. (SSRF / leitura de arquivos locais). Só protocolos file/pipe e demuxers de mídia conhecidos.
SAFE_IN = ["-protocol_whitelist", "file,pipe"]
ALLOWED_FORMATS = {"mov", "mp4", "m4a", "3gp", "matroska", "webm", "avi", "mpegts", "mpeg", "mpegvideo", "flv", "asf", "ogg",
                   "wav", "mp3", "flac", "aac", "ac3", "opus", "image2", "png_pipe", "jpeg_pipe", "webp_pipe", "bmp_pipe",
                   "tiff_pipe", "gif", "mxf", "rm", "ivf"}
DENIED_FORMATS = {"hls", "applehttp", "dash", "concat", "sdp", "rtsp", "rtp", "tee", "lavfi", "ffmetadata", "data", "image2pipe"}
IMAGE_CODECS = {"mjpeg", "png", "webp", "bmp", "gif", "tiff", "jpeg2000"}


class MediaError(Exception):
    pass


def die_with_parent() -> None:
    """preexec_fn: o filho recebe SIGKILL se o processo pai morrer (kill -9 no worker não deixa FFmpeg órfão)."""
    try:
        import ctypes
        import signal
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)  # PR_SET_PDEATHSIG
    except Exception:  # fora do Linux: segue sem a proteção
        pass


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True, preexec_fn=die_with_parent)
    except subprocess.CalledProcessError as e:
        raise MediaError((e.stderr or "")[-500:] or "ffmpeg falhou") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError("timeout") from e
    except FileNotFoundError as e:
        raise MediaError("ffmpeg/ffprobe não encontrado") from e


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", *SAFE_IN, "-print_format", "json", "-show_format", "-show_streams", str(path)], 60)
    data = json.loads(out.stdout)
    fmts = set((data.get("format", {}).get("format_name") or "").split(","))
    if fmts & DENIED_FORMATS or not fmts & ALLOWED_FORMATS:
        raise MediaError(f"formato de arquivo não permitido: {sorted(fmts)}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video and not audio:
        raise MediaError("arquivo sem fluxo de vídeo/áudio")
    info: dict = {"kind": "unknown", "raw": data}
    dur = data.get("format", {}).get("duration")
    info["duration_ms"] = int(float(dur) * 1000) if dur else None
    if video:
        is_image = video.get("codec_name") in IMAGE_CODECS and (info["duration_ms"] or 0) < 500
        info["kind"] = "image" if is_image else "video"
        info["width"], info["height"] = video.get("width"), video.get("height")
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/0"
        fr = Fraction(rate) if rate not in ("0/0", "") else None
        if fr:
            info["fps_num"], info["fps_den"] = fr.numerator, fr.denominator
    else:
        info["kind"] = "audio"
    if audio:
        info["audio_info"] = {k: audio.get(k) for k in ("codec_name", "sample_rate", "channels", "channel_layout")}
    return info


def make_thumbnail(src: Path, dest: Path, at_ms: int = 0) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at_ms / 1000:.3f}", *SAFE_IN, "-i", str(src), "-frames:v", "1",
          "-vf", "scale=320:-2", str(dest)], 120)


def make_proxy(src: Path, dest: Path, height: int = 480) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-v", "error", *SAFE_IN, "-i", str(src), "-vf", f"scale=-2:{height}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", "30",
          "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest)], 3600)


def waveform(src: Path, pps: int = 50) -> dict:
    """Picos de amplitude (0-255) por 1/pps s, para desenhar a forma de onda na timeline."""
    import numpy as np
    rate = 8000
    try:
        raw = subprocess.run(["ffmpeg", "-v", "error", *SAFE_IN, "-i", str(src), "-vn", "-ac", "1", "-ar", str(rate),
                              "-f", "s16le", "-"], capture_output=True, timeout=3600, check=True,
                             preexec_fn=die_with_parent).stdout
    except subprocess.CalledProcessError as e:
        raise MediaError((e.stderr or b"").decode(errors="replace")[-300:] or "ffmpeg falhou") from e
    a = np.abs(np.frombuffer(raw, dtype=np.int16).astype(np.int32))
    step = rate // pps
    n = len(a) // step
    peaks = (a[: n * step].reshape(n, step).max(axis=1) / 32768 * 255).astype(int) if n else np.array([], dtype=int)
    return {"peaks_per_second": pps, "peaks": peaks.tolist()}
