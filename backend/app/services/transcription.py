"""Transcrição WhisperX (GPU) com alinhamento por palavra. Roda no worker `transcribe`."""
import logging
import subprocess
import uuid

from app import storage
from app.media import SAFE_IN, die_with_parent
from app.config import settings
from app.db import SessionLocal
from app.models import Asset, Job, Speaker, Transcript, Word
from app.services import jobs as J

_models: dict = {}


def _device() -> tuple[str, str]:
    """KONTRUL_ASR_DEVICE: auto = GPU se houver, senão CPU/int8 (mais lento, avisa no log);
    cuda = exige GPU e falha com mensagem clara (o compose com GPU usa este modo, para não degradar em silêncio); cpu = força CPU."""
    import torch
    mode = settings.asr_device.lower()
    if mode == "cpu":
        return "cpu", "int8"
    if torch.cuda.is_available():
        logging.getLogger("kontrul.asr").info("GPU: %s", torch.cuda.get_device_name(0))
        return "cuda", "float16"
    if mode == "cuda":
        raise RuntimeError("KONTRUL_ASR_DEVICE=cuda, mas o PyTorch não enxerga nenhuma GPU. Verifique o driver NVIDIA e o "
                           "nvidia-container-toolkit (make gpu-check) ou use KONTRUL_ASR_DEVICE=auto para cair para CPU.")
    logging.getLogger("kontrul.asr").warning("GPU indisponível: transcrição em CPU (mais lenta)")
    return "cpu", "int8"


def extract_audio(src, dest) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", *SAFE_IN, "-i", str(src), "-vn", "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", str(dest)], check=True, capture_output=True, timeout=3600,
                       preexec_fn=die_with_parent)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"extração de áudio falhou: {(e.stderr or b'')[-300:]!r}")


def _asr(language: str):
    import whisperx
    device, ctype = _device()
    key = ("asr", language)
    if key not in _models:
        _models[key] = whisperx.load_model(settings.whisper_model, device, compute_type=ctype, language=language)
    return _models[key], device


def _align_model(language: str, device: str):
    import whisperx
    key = ("align", language)
    if key not in _models:
        _models[key] = whisperx.load_align_model(language, device)
    return _models[key]


def transcribe_file(wav_path: str, language: str, diarize: bool = False) -> dict:
    """Devolve {'segments': [...], 'words': [...], 'language', 'diarized'}; tempos em ms.
    Não normaliza o texto: «erro», «ERRO!» etc. são preservados."""
    import whisperx
    model, device = _asr(language)
    audio = whisperx.load_audio(wav_path)
    res = model.transcribe(audio, batch_size=16, language=language)
    am, meta = _align_model(language, device)
    res = whisperx.align(res["segments"], am, meta, audio, device)
    diarized = False
    if diarize and settings.hf_token:
        from whisperx.diarize import DiarizationPipeline
        dia = DiarizationPipeline(token=settings.hf_token, device=device)
        res = whisperx.assign_word_speakers(dia(audio), res)
        diarized = True

    words: list[dict] = []
    segments: list[dict] = []
    for seg in res["segments"]:
        w0 = len(words)
        for w in seg.get("words", []):
            words.append({"text": w["word"], "start": w.get("start"), "end": w.get("end"),
                          "confidence": w.get("score"), "speaker": w.get("speaker")})
        if len(words) > w0:
            segments.append({"w0": w0, "w1": len(words), "text": seg["text"].strip(), "speaker": seg.get("speaker"),
                             "seg_start": seg["start"], "seg_end": seg["end"]})
    _fill_missing_times(words)
    out_words = [{"text": w["text"], "start_ms": round(w["start"] * 1000), "end_ms": round(w["end"] * 1000),
                  "confidence": None if w["confidence"] is None else float(w["confidence"]), "speaker": w["speaker"]}
                 for w in words]
    out_segs = []
    for s in segments:
        ws = out_words[s["w0"]:s["w1"]]
        out_segs.append({"w0": s["w0"], "w1": s["w1"], "text": s["text"], "speaker": s["speaker"],
                         "start_ms": ws[0]["start_ms"], "end_ms": ws[-1]["end_ms"]})
    return {"segments": out_segs, "words": out_words, "language": res.get("language", language), "diarized": diarized}


def _fill_missing_times(words: list[dict]) -> None:
    """Palavras sem tempo (números/símbolos) herdam dos vizinhos."""
    last_end = 0.0
    for i, w in enumerate(words):
        if w["start"] is None or w["end"] is None:
            nxt = next((x["start"] for x in words[i + 1:] if x["start"] is not None), last_end)
            w["start"], w["end"] = last_end, max(last_end, nxt)
        last_end = float(w["end"])


def run_transcribe(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, uuid.UUID(job_id))
        if job is None or job.state in J.TERMINAL:
            return
        try:
            asset = db.get(Asset, uuid.UUID(job.params["asset_id"]))
            language = job.params.get("language") or settings.whisper_language
            J.set_state(db, job, "running", 0.05)
            wav = storage.resolve(f"{storage.asset_dir(asset.project_id, asset.id)}/audio16k.wav")
            if not wav.exists():
                extract_audio(storage.resolve(asset.uri), wav)
            J.log(job, "áudio extraído")
            J.set_state(db, job, "running", 0.15)
            with J.heartbeat(job.id):
                r = transcribe_file(str(wav), language, bool(job.params.get("diarize")))
            db.refresh(job)
            if job.cancel_requested:
                J.set_state(db, job, "cancelled")
                return
            rev = (db.query(Transcript).filter_by(asset_id=asset.id).count()) + 1
            t = Transcript(project_id=asset.project_id, asset_id=asset.id, language=r["language"],
                           model_version=f"whisperx/{settings.whisper_model} ({_device()[0]})", revision=rev,
                           segments=r["segments"], diarized=r["diarized"])
            db.add(t)
            db.flush()
            speakers: dict[str, uuid.UUID] = {}
            for i, w in enumerate(r["words"]):
                sp = None
                if w["speaker"]:
                    if w["speaker"] not in speakers:
                        s = Speaker(project_id=asset.project_id, label=w["speaker"])
                        db.add(s)
                        db.flush()
                        speakers[w["speaker"]] = s.id
                    sp = speakers[w["speaker"]]
                db.add(Word(transcript_id=t.id, speaker_id=sp, idx=i, start_ms=w["start_ms"], end_ms=w["end_ms"],
                            text=w["text"], confidence=w["confidence"]))
            db.commit()
            J.set_state(db, job, "succeeded", 1.0,
                        result={"transcript_id": str(t.id), "words": len(r["words"]), "segments": len(r["segments"])})
        except Exception as e:
            db.rollback()
            job = db.get(Job, job.id)
            J.set_state(db, job, "failed", error={"code": "transcribe_failed", "message": str(e)[:500]})
