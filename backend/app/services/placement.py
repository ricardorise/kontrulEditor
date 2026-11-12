"""Associação mídia ↔ fala (RF05, sem LLM): casa tags/descrição das mídias com os termos falados e
propõe ponto de entrada, duração, modo e trilha. Só PROPÕE: aplicar é decisão do usuário/agente.
Ponto de extensão: um provedor semântico (embeddings/LLM) pode substituir `score_terms` mantendo o contrato."""
import re

from app.services import timeline as T
from app.services.scriptalign import norm, tokenize

STOP = set("""a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sob sobre entre ate ao aos
e ou mas que se como mais menos muito muita muitos muitas ja nao sim tambem so ainda entao assim aqui ali la isso isto
esse essa esses essas este esta estes estas aquele aquela eu voce voces ele ela eles elas nos meu minha seu sua nosso
foi era ser sao esta estao tem ter tinha vai vamos pode podem fazer faz fez ficou ficar tudo todo toda todos todas
cada onde quando porque qual quais quem outro outra outros outras mesmo mesma tipo coisa gente tá né pois""".split())
THRESHOLD = 3.0
MODE_WORDS = {"roll", "broll", "pip", "canto", "tela", "sobreposicao"}
DEFAULT_IMAGE_MS, DEFAULT_VIDEO_MS, MIN_MS = 4000, 5000, 1500
W_TAG, W_USE, W_DESC, W_NAME = 3.0, 2.0, 1.5, 1.0


def stem(t: str) -> str:
    if len(t) > 4 and t.endswith("s"):
        t = t[:-1]
    return t


def terms(text: str) -> list[str]:
    return [stem(t) for t, *_ in tokenize(text) if len(t) >= 3 and t not in STOP and not t.isdigit()]


def asset_terms(a: dict) -> dict[str, float]:
    w: dict[str, float] = {}
    for tag in a.get("tags") or []:
        # tag de várias palavras ("tela dividida") vale por cada termo; mantém o peso cheio
        for t in terms(tag):
            w[t] = max(w.get(t, 0), W_TAG)
    for t in terms(a.get("intended_use") or ""):
        if t not in MODE_WORDS:  # "b-roll", "pip", "canto" definem o modo, não o assunto
            w[t] = max(w.get(t, 0), W_USE)
    for t in terms(a.get("description") or ""):
        w[t] = max(w.get(t, 0), W_DESC)
    stem_name = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", a.get("filename") or "").replace("_", " ").replace("-", " ")
    for t in terms(stem_name):
        w[t] = max(w.get(t, 0), W_NAME)
    return w


def _level(score: float) -> str:
    return "alta" if score >= 6 else "media" if score >= THRESHOLD else "baixa"


def propose(words: list[dict], segments: list[dict], assets: list[dict], doc: dict | None = None,
            main_id: str | None = None, max_per_asset: int = 1, semantic: list[dict] | None = None) -> dict:
    seg_terms: list[dict[str, int]] = []  # termo → índice da primeira palavra
    for s in segments:
        d: dict[str, int] = {}
        for i in range(s["w0"], s["w1"]):
            for t in terms(words[i]["text"]):
                d.setdefault(t, i)
        seg_terms.append(d)

    existing: list[tuple[int, int]] = []
    if doc:
        existing = [(c["timeline_start_ms"], c["timeline_start_ms"] + c["duration_ms"]) for c in T.overlay_clips(doc)]
    chosen: list[tuple[int, int]] = []

    scored = []
    for a in assets:
        w = asset_terms(a)
        cands = []
        for si, st in enumerate(seg_terms):
            hit = [t for t in w if t in st]
            score = sum(w[t] for t in hit)
            if score >= THRESHOLD:
                cands.append((score, si, hit, min(st[t] for t in hit)))
        for sm in (semantic or []):  # candidatos semânticos (LLM): mesmo contrato, com a justificativa do modelo
            if sm["asset_id"] == a["id"]:
                cands.append((sm["score"], sm["seg_idx"], ["(semântico)"], sm["word_idx"], sm["reason"]))
        cands.sort(key=lambda c: (-c[0], c[1]))
        scored.append((a, cands))
    scored.sort(key=lambda x: (-(x[0].get("priority") or 1), -(x[1][0][0] if x[1] else 0)))

    proposals, unmatched = [], []
    used: dict[str, int] = {}
    for c in (T.overlay_clips(doc) if doc else []):
        used[c["asset_id"]] = used.get(c["asset_id"], 0) + 1
    for a, cands in scored:
        n = used.get(a["id"], 0)  # mídia já inserida conta no limite
        already = n >= max_per_asset
        for score, si, hit, widx, *why in cands:
            if n >= max_per_asset:
                break
            src = words[widx]["start_ms"]
            if doc and main_id:
                out = T.source_to_output(doc, main_id, src)
                if out is None:  # a fala citada foi cortada
                    continue
                total = doc["duration_ms"]
            else:
                out, total = src, None
            dur = a.get("suggested_duration_ms") or (DEFAULT_IMAGE_MS if a["kind"] == "image" else DEFAULT_VIDEO_MS)
            if a["kind"] == "video" and a.get("duration_ms"):
                dur = min(dur, a["duration_ms"])
            if total is not None:
                dur = min(dur, total - out)
            if dur < MIN_MS:
                continue
            iv = (out, out + dur)
            if any(iv[0] < e and iv[1] > s for s, e in existing + chosen):
                continue
            chosen.append(iv)
            use = (a.get("intended_use") or "").lower()
            mode = "pip" if ("pip" in use or "canto" in use) else "b_roll"
            proposals.append({
                "asset_id": a["id"], "filename": a.get("filename"), "mode": mode, "source_start_ms": src,
                "timeline_start_ms": out, "duration_ms": dur, "score": score, "level": _level(score),
                "matched_terms": hit, "segment_text": segments[si]["text"],
                "rationale": why[0] if why else f"A fala cita {', '.join('«' + t + '»' for t in hit)}, que casa com as tags/descrição da mídia.",
                "source": "llm" if why else "tags",
                "operation": {"type": "insert_overlay", "asset_id": a["id"], "timeline_start_ms": out,
                              "duration_ms": dur, "mode": mode, "audio_policy": "keep_primary"},
            })
            n += 1
        if n == used.get(a["id"], 0):
            reason = "already_used" if already else "no_match" if not cands else "no_slot"
            unmatched.append({"asset_id": a["id"], "filename": a.get("filename"), "reason": reason, "message": {
                "already_used": "Esta mídia já está inserida na timeline.",
                "no_match": "Nenhuma tag/descrição aparece na fala.",
                "no_slot": "Há correspondência, mas o trecho foi cortado, não cabe ou já tem outra mídia."}[reason]})
    proposals.sort(key=lambda p: p["timeline_start_ms"])
    return {"proposals": proposals, "unmatched": unmatched}
