"""Motor de timeline não destrutivo (puro, sem I/O).

Documento = {"schema":1, "tracks":[...], "clips":[...], "duration_ms":N}.
- Trilha `main` é contígua (ripple): clips em sequência, sem buracos. Duração da saída = duração da main.
- Trilhas `overlay-N` guardam B-roll/PiP posicionados em tempo de SAÍDA.
- Cada clip guarda tempo de ORIGEM (source_in/out) e de SAÍDA (timeline_start/duration) separadamente.
Intervalos são [início, fim). Todas as operações devolvem um documento novo; o original nunca é alterado.
"""
import copy
import uuid

MAIN = "main"
MODES = {"main", "b_roll", "pip"}
AUDIO_POLICIES = {"original", "keep_primary"}


class TimelineError(Exception):
    def __init__(self, message: str, code: str = "invalid_operation"):
        super().__init__(message)
        self.code, self.message = code, message


def empty_doc() -> dict:
    return {"schema": 1, "tracks": [{"id": MAIN, "kind": "video", "order": 0}], "clips": [], "duration_ms": 0}


def _id() -> str:
    return str(uuid.uuid4())


def main_clips(doc: dict) -> list[dict]:
    return sorted((c for c in doc["clips"] if c["track_id"] == MAIN), key=lambda c: c["timeline_start_ms"])


def overlay_clips(doc: dict) -> list[dict]:
    return sorted((c for c in doc["clips"] if c["track_id"] != MAIN), key=lambda c: (c["track_id"], c["timeline_start_ms"]))


def main_duration(doc: dict) -> int:
    return sum(c["duration_ms"] for c in doc["clips"] if c["track_id"] == MAIN)


def _clip(asset_id: str, track: str, s_in: int, s_out: int, start: int, mode: str, audio: str) -> dict:
    return {"id": _id(), "asset_id": asset_id, "track_id": track, "source_in_ms": s_in, "source_out_ms": s_out,
            "timeline_start_ms": start, "duration_ms": s_out - s_in, "mode": mode, "audio_policy": audio,
            "transforms": {}}


def _int(op: dict, key: str, minimum: int | None = None, default: int | None = None) -> int:
    v = op.get(key, default)
    if v is None:
        raise TimelineError(f"campo '{key}' é obrigatório (inteiro, em ms)", "invalid_payload")
    # Agentes (MCP/Cursor) costumam enviar 5000.0 ou "5000": aceita número integral/fracionário (arredonda ao ms) e string numérica.
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            raise TimelineError(f"campo '{key}' deve ser inteiro (ms), recebido {v!r}", "invalid_payload") from None
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise TimelineError(f"campo '{key}' deve ser inteiro (ms)", "invalid_payload")
        v = round(v)
    if isinstance(v, bool) or not isinstance(v, int):
        raise TimelineError(f"campo '{key}' deve ser inteiro (ms)", "invalid_payload")
    if minimum is not None and v < minimum:
        raise TimelineError(f"campo '{key}' deve ser >= {minimum}", "invalid_payload")
    return v


def repack(doc: dict) -> None:
    """Mantém a main contígua e recalcula a duração total."""
    t = 0
    for c in main_clips(doc):
        c["timeline_start_ms"], c["duration_ms"] = t, c["source_out_ms"] - c["source_in_ms"]
        t += c["duration_ms"]
    doc["duration_ms"] = t


def _shift_overlays_removed(doc: dict, a: int, b: int) -> None:
    """Saída [a,b) removida da main: overlays depois sobem; os que começavam dentro vão para `a`."""
    for c in overlay_clips(doc):
        s = c["timeline_start_ms"]
        if s >= b:
            c["timeline_start_ms"] = s - (b - a)
        elif s > a:
            c["timeline_start_ms"] = a


def _shift_overlays_inserted(doc: dict, at: int, d: int) -> None:
    for c in overlay_clips(doc):
        if c["timeline_start_ms"] >= at:
            c["timeline_start_ms"] += d


def _merge_adjacent(doc: dict) -> None:
    out: list[dict] = []
    for c in main_clips(doc):
        p = out[-1] if out else None
        if p and p["asset_id"] == c["asset_id"] and p["source_out_ms"] == c["source_in_ms"] and p["mode"] == c["mode"]:
            p["source_out_ms"] = c["source_out_ms"]
            doc["clips"].remove(c)
        else:
            out.append(c)


def _find(doc: dict, clip_id: str) -> dict:
    c = next((c for c in doc["clips"] if c["id"] == clip_id), None)
    if not c:
        raise TimelineError(f"clip {clip_id} não existe", "clip_not_found")
    return c


def _default_asset(doc: dict, op: dict) -> str:
    if op.get("asset_id"):
        return str(op["asset_id"])
    mc = main_clips(doc)
    if not mc:
        raise TimelineError("timeline sem clips", "empty_timeline")
    return mc[0]["asset_id"]


# ---------- operações
def op_init_main(doc, op, assets):
    if doc["clips"]:
        raise TimelineError("timeline já inicializada", "already_initialized")
    aid = str(op.get("asset_id", ""))
    a = assets.get(aid)
    if not a or a["kind"] not in ("video", "audio") or not a.get("duration_ms"):
        raise TimelineError("asset principal inválido (precisa ser vídeo/áudio pronto com duração)", "invalid_asset")
    doc["clips"].append(_clip(aid, MAIN, 0, a["duration_ms"], 0, "main", "original"))
    repack(doc)


def op_remove_range(doc, op, assets):
    """Remove [start,end) em tempo de ORIGEM dos clips da main (ripple)."""
    aid = _default_asset(doc, op)
    start, end = _int(op, "start_ms", 0), _int(op, "end_ms", 1)
    if end <= start:
        raise TimelineError("end_ms deve ser maior que start_ms", "invalid_range")
    removed_out: list[tuple[int, int]] = []
    new_clips: list[dict] = []
    for c in doc["clips"]:
        if c["track_id"] != MAIN or c["asset_id"] != aid or c["source_out_ms"] <= start or c["source_in_ms"] >= end:
            new_clips.append(c)
            continue
        ix_in, ix_out = max(c["source_in_ms"], start), min(c["source_out_ms"], end)
        removed_out.append((c["timeline_start_ms"] + ix_in - c["source_in_ms"],
                            c["timeline_start_ms"] + ix_out - c["source_in_ms"]))
        if c["source_in_ms"] < ix_in:
            left = dict(copy.deepcopy(c), source_out_ms=ix_in)
            new_clips.append(left)
        if c["source_out_ms"] > ix_out:
            right = dict(copy.deepcopy(c), id=_id() if c["source_in_ms"] < ix_in else c["id"], source_in_ms=ix_out)
            new_clips.append(right)
    if not removed_out:
        raise TimelineError("intervalo não intersecta nenhum trecho atual da timeline", "no_effect")
    for a, b in sorted(removed_out, reverse=True):  # de trás para frente mantém os offsets válidos
        _shift_overlays_removed(doc, a, b)
    doc["clips"] = new_clips
    repack(doc)
    if not main_clips(doc):
        raise TimelineError("a remoção esvaziaria a timeline principal", "would_empty")


def op_restore_range(doc, op, assets):
    """Devolve um trecho de origem removido antes. Só em lacunas (não sobrepõe clips atuais)."""
    aid = _default_asset(doc, op)
    start, end = _int(op, "start_ms", 0), _int(op, "end_ms", 1)
    if end <= start:
        raise TimelineError("end_ms deve ser maior que start_ms", "invalid_range")
    a = assets.get(aid)
    if not a or end > (a.get("duration_ms") or 0):
        raise TimelineError("intervalo fora da duração do asset", "out_of_bounds")
    mc = main_clips(doc)
    for c in mc:
        if c["asset_id"] == aid and c["source_in_ms"] < end and c["source_out_ms"] > start:
            raise TimelineError("intervalo já presente na timeline", "overlaps_existing")
    pos = 0  # depois do último clip do mesmo asset que termina antes do início
    for k, c in enumerate(mc):
        if c["asset_id"] == aid and c["source_out_ms"] <= start:
            pos = k + 1
    at = mc[pos - 1]["timeline_start_ms"] + mc[pos - 1]["duration_ms"] if pos else 0
    new = _clip(aid, MAIN, start, end, at, "main", "original")
    _shift_overlays_inserted(doc, at, end - start)
    for c in mc[pos:]:
        c["timeline_start_ms"] += end - start
    doc["clips"].append(new)
    repack(doc)
    _merge_adjacent(doc)
    repack(doc)


def op_split(doc, op, assets):
    c = _find(doc, str(op.get("clip_id", "")))
    at = _int(op, "at_ms", 0)
    if not (c["timeline_start_ms"] < at < c["timeline_start_ms"] + c["duration_ms"]):
        raise TimelineError("at_ms deve estar estritamente dentro do clip (tempo de saída)", "invalid_split")
    cut = c["source_in_ms"] + (at - c["timeline_start_ms"])
    right = dict(copy.deepcopy(c), id=_id(), source_in_ms=cut, timeline_start_ms=at)
    c["source_out_ms"] = cut
    doc["clips"].append(right)
    repack(doc)


def op_trim_clip(doc, op, assets):
    c = _find(doc, str(op.get("clip_id", "")))
    if c["track_id"] == MAIN:
        raise TimelineError("na trilha principal use remove_range/restore_range", "use_range_ops")
    c["source_in_ms"] = _int(op, "source_in_ms", 0, c["source_in_ms"])
    c["source_out_ms"] = _int(op, "source_out_ms", 1, c["source_out_ms"])
    if c["source_out_ms"] <= c["source_in_ms"]:
        raise TimelineError("source_out_ms deve ser maior que source_in_ms", "invalid_range")
    c["duration_ms"] = c["source_out_ms"] - c["source_in_ms"]


def op_move_clip(doc, op, assets):
    c = _find(doc, str(op.get("clip_id", "")))
    if c["track_id"] == MAIN:
        raise TimelineError("clips da trilha principal são reordenados com reorder_main", "use_reorder")
    c["timeline_start_ms"] = _int(op, "timeline_start_ms", 0)
    if op.get("track_id"):
        c["track_id"] = _ensure_overlay_track(doc, str(op["track_id"]))


def op_reorder_main(doc, op, assets):
    ids = op.get("clip_ids")
    cur = main_clips(doc)
    if not isinstance(ids, list) or sorted(map(str, ids)) != sorted(c["id"] for c in cur):
        raise TimelineError("clip_ids deve ser uma permutação dos clips da trilha principal", "invalid_order")
    by = {c["id"]: c for c in cur}
    for k, cid in enumerate(ids):
        by[str(cid)]["timeline_start_ms"] = k  # ordena; repack define os tempos reais
    repack(doc)


def op_remove_clip(doc, op, assets):
    c = _find(doc, str(op.get("clip_id", "")))
    if c["track_id"] == MAIN:
        if len(main_clips(doc)) == 1:
            raise TimelineError("não é possível remover o único clip principal", "would_empty")
        a, b = c["timeline_start_ms"], c["timeline_start_ms"] + c["duration_ms"]
        doc["clips"].remove(c)
        _shift_overlays_removed(doc, a, b)
        repack(doc)
    else:
        doc["clips"].remove(c)


def _ensure_overlay_track(doc: dict, track_id: str) -> str:
    if not track_id.startswith("overlay-"):
        raise TimelineError("trilha de overlay deve se chamar overlay-N", "invalid_track")
    if not any(t["id"] == track_id for t in doc["tracks"]):
        doc["tracks"].append({"id": track_id, "kind": "overlay", "order": len(doc["tracks"])})
    return track_id


def _free_track(doc: dict, start: int, end: int) -> str:
    tracks = [t["id"] for t in doc["tracks"] if t["id"] != MAIN]
    for tid in tracks:
        if all(c["timeline_start_ms"] >= end or c["timeline_start_ms"] + c["duration_ms"] <= start
               for c in doc["clips"] if c["track_id"] == tid):
            return tid
    return _ensure_overlay_track(doc, f"overlay-{len(tracks) + 1}")


def _media_asset(assets: dict, aid: str) -> dict:
    a = assets.get(aid)
    if not a or a["kind"] not in ("video", "image"):
        raise TimelineError("asset de mídia inválido (precisa ser vídeo ou imagem pronto)", "invalid_asset")
    return a


def op_insert_overlay(doc, op, assets):
    aid = str(op.get("asset_id", ""))
    a = _media_asset(assets, aid)
    mode = op.get("mode", "b_roll")
    if mode not in ("b_roll", "pip"):
        raise TimelineError("mode deve ser b_roll ou pip", "invalid_mode")
    audio = op.get("audio_policy", "keep_primary")
    if audio != "keep_primary":
        raise TimelineError("audio_policy suportado: keep_primary", "invalid_audio_policy")
    if not main_clips(doc):
        raise TimelineError("timeline sem clips", "empty_timeline")
    start, dur = _int(op, "timeline_start_ms", 0), _int(op, "duration_ms", 1)
    s_in = _int(op, "source_in_ms", 0, 0)
    if start >= doc["duration_ms"]:
        raise TimelineError("overlay começa depois do fim da timeline", "out_of_bounds")
    if a["kind"] == "video" and s_in + dur > (a.get("duration_ms") or 0):
        raise TimelineError("trecho excede a duração do vídeo do overlay", "out_of_bounds")
    track = _ensure_overlay_track(doc, str(op["track_id"])) if op.get("track_id") else _free_track(doc, start, start + dur)
    doc["clips"].append(_clip(aid, track, s_in, s_in + dur, start, mode, audio))


def op_insert_sequential(doc, op, assets):
    """Insere mídia na trilha principal (ripple) no ponto de saída `at_ms`."""
    aid = str(op.get("asset_id", ""))
    a = _media_asset(assets, aid)
    at, dur = _int(op, "at_ms", 0), _int(op, "duration_ms", 1)
    s_in = _int(op, "source_in_ms", 0, 0)
    if at > doc["duration_ms"]:
        raise TimelineError("at_ms além do fim da timeline", "out_of_bounds")
    if a["kind"] == "video" and s_in + dur > (a.get("duration_ms") or 0):
        raise TimelineError("trecho excede a duração do vídeo", "out_of_bounds")
    inside = next((c for c in main_clips(doc) if c["timeline_start_ms"] < at < c["timeline_start_ms"] + c["duration_ms"]), None)
    if inside:
        op_split(doc, {"clip_id": inside["id"], "at_ms": at}, assets)
    for c in main_clips(doc):
        if c["timeline_start_ms"] >= at:
            c["timeline_start_ms"] += dur
    _shift_overlays_inserted(doc, at, dur)
    new = _clip(aid, MAIN, s_in, s_in + dur, at, "main", "original")
    doc["clips"].append(new)
    repack(doc)


HANDLERS = {
    "init_main": op_init_main, "remove_range": op_remove_range, "restore_range": op_restore_range,
    "split": op_split, "trim_clip": op_trim_clip, "move_clip": op_move_clip, "reorder_main": op_reorder_main,
    "remove_clip": op_remove_clip, "insert_overlay": op_insert_overlay, "insert_sequential": op_insert_sequential,
}
OP_TYPES = set(HANDLERS) | {"apply_suggestion", "revert_to"}


def apply_op(doc: dict, op: dict, assets: dict) -> dict:
    fn = HANDLERS.get(op.get("type"))
    if not fn:
        raise TimelineError(f"operação desconhecida: {op.get('type')!r}", "unknown_operation")
    new = copy.deepcopy(doc)
    fn(new, op, assets)
    return new


def validate(doc: dict, assets: dict) -> None:
    """Invariantes do doc 03. Levanta TimelineError."""
    seen: set[str] = set()
    tracks = {t["id"] for t in doc["tracks"]}
    for c in doc["clips"]:
        if c["id"] in seen:
            raise TimelineError("id de clip duplicado", "invariant")
        seen.add(c["id"])
        if c["track_id"] not in tracks:
            raise TimelineError("clip em trilha inexistente", "invariant")
        a = assets.get(c["asset_id"])
        if not a:
            raise TimelineError("clip referencia asset inexistente neste projeto", "invariant")
        if c["source_in_ms"] < 0 or c["source_out_ms"] <= c["source_in_ms"]:
            raise TimelineError("intervalo de origem inválido", "invariant")
        if a["kind"] != "image" and a.get("duration_ms") and c["source_out_ms"] > a["duration_ms"]:
            raise TimelineError("source_out excede a duração do asset", "invariant")
        if c["duration_ms"] != c["source_out_ms"] - c["source_in_ms"]:
            raise TimelineError("duration_ms inconsistente", "invariant")
        if c["mode"] not in MODES or c["audio_policy"] not in AUDIO_POLICIES:
            raise TimelineError("modo/política de áudio inválidos", "invariant")
    t = 0
    for c in main_clips(doc):
        if c["timeline_start_ms"] != t:
            raise TimelineError("trilha principal não contígua", "invariant")
        t += c["duration_ms"]
    if doc["duration_ms"] != t:
        raise TimelineError("duração total inconsistente", "invariant")
    by_track: dict[str, list[dict]] = {}
    for c in overlay_clips(doc):
        if c["timeline_start_ms"] < 0:
            raise TimelineError("overlay com início negativo", "invariant")
        by_track.setdefault(c["track_id"], []).append(c)
    for cs in by_track.values():
        for x, y in zip(cs, cs[1:]):
            if y["timeline_start_ms"] < x["timeline_start_ms"] + x["duration_ms"]:
                raise TimelineError("overlays sobrepostos na mesma trilha", "invariant")


# ---------- mapeamento de coordenadas (origem ↔ saída)
def source_to_output(doc: dict, asset_id: str, source_ms: int) -> int | None:
    for c in main_clips(doc):
        if c["asset_id"] == asset_id and c["source_in_ms"] <= source_ms < c["source_out_ms"]:
            return c["timeline_start_ms"] + source_ms - c["source_in_ms"]
    return None  # trecho removido


def output_to_source(doc: dict, output_ms: int) -> tuple[str, int] | None:
    for c in main_clips(doc):
        if c["timeline_start_ms"] <= output_ms < c["timeline_start_ms"] + c["duration_ms"]:
            return c["asset_id"], c["source_in_ms"] + output_ms - c["timeline_start_ms"]
    return None
