"""Regras determinísticas de análise (puras). «erro» é pista, não ordem de corte."""
import re

from app.services.scriptalign import norm, tokenize

ERRO_FORMS = {"erro", "erroo", "errou", "erros"}
DETERMINERS = {"o", "um", "uma", "esse", "essa", "este", "esta", "aquele", "do", "no", "pelo", "seu", "meu",
               "nosso", "outro", "grave", "pequeno", "grande", "algum", "qualquer", "por", "com", "sem", "tal"}
CUE_RE = re.compile(r"\b(pera ai|perai|deixa eu falar de novo|vou repetir|vou falar de novo|corta essa parte|"
                    r"como eu ia dizendo|errei|volta aqui|vamos de novo|de novo)\b")
TERMINAL = (".", "!", "?", "…")
GAP_AFTER_MS, GAP_BEFORE_MS, EXTEND_GAP_MS, LONG_RANGE_MS = 400, 300, 2000, 25_000
OFFSCRIPT_MIN_MS, OFFSCRIPT_GROUP_GAP_MS = 1500, 3000


def _clean(text: str) -> str:
    return norm(re.sub(r"[^\w]", "", text))


def _seg_of(segments: list[dict], widx: int) -> int:
    return next(i for i, s in enumerate(segments) if s["w0"] <= widx < s["w1"])


def is_marker(words: list[dict], segments: list[dict], i: int) -> bool:
    w = words[i]
    if _clean(w["text"]) not in ERRO_FORMS:
        return False
    seg = segments[_seg_of(segments, i)]
    last_in_seg = i == seg["w1"] - 1
    gap_after = words[i + 1]["start_ms"] - w["end_ms"] if i + 1 < len(words) else 10**9
    gap_before = w["start_ms"] - words[i - 1]["end_ms"] if i > 0 else 10**9
    punct = w["text"].rstrip().endswith(TERMINAL + (",",)) or w["text"].lstrip().isupper() and len(w["text"].strip()) > 2
    prev = _clean(words[i - 1]["text"]) if i > 0 else ""
    inside_phrase = prev in DETERMINERS and not last_in_seg and gap_after < GAP_AFTER_MS
    return (last_in_seg or gap_after >= GAP_AFTER_MS or gap_before >= GAP_BEFORE_MS or punct) and not inside_phrase


def _sentence_start(words, segments, i, si) -> tuple[int, int]:
    """Início (ms) e índice de segmento da frase interrompida que contém a palavra i."""
    seg = segments[si]
    start_w = seg["w0"]
    for k in range(i - 1, seg["w0"] - 1, -1):
        if words[k]["text"].rstrip().endswith(TERMINAL):
            start_w = k + 1
            break
    start = words[start_w]["start_ms"]
    # frase sem pontuação final no segmento anterior continua neste: estende para trás
    while start_w == seg["w0"] and si > 0:
        prev = segments[si - 1]
        if (seg["start_ms"] - prev["end_ms"] > EXTEND_GAP_MS or prev["text"].rstrip().endswith(TERMINAL)
                or prev.get("speaker") != seg.get("speaker")):
            break
        si -= 1
        seg = segments[si]
        start_w, start = seg["w0"], seg["start_ms"]
    return start, si


RESTART_PREFIX = (4, 3)   # tamanhos de prefixo tentados, do mais ao menos seletivo
RESTART_WINDOW_MS = 60_000


def _restart_index(words: list[dict], i: int, redo: list[int]) -> int | None:
    """Índice da palavra onde a tentativa descartada começou: a ocorrência mais próxima, antes do «erro»,
    do início do recomeço (o falante retoma a frase do começo)."""
    toks = [_clean(words[k]["text"]) for k in redo]
    toks = [t for t in toks if t]
    for n in RESTART_PREFIX:
        if len(toks) < n:
            continue
        pre = toks[:n]
        for k in range(i - n, -1, -1):
            if words[i]["end_ms"] - words[k]["start_ms"] > RESTART_WINDOW_MS:
                break
            if [_clean(words[k + j]["text"]) for j in range(n)] == pre:
                return k
    return None


def phrases_of(rules: list[dict] | None, kind: str) -> list[tuple[int | str, str]]:
    """(id, frase normalizada) das regras ativas de um tipo."""
    out = []
    for r in rules or []:
        if r.get("kind") == kind:
            for ph in (r.get("params") or {}).get("phrases", []):
                n = " ".join(t for t, *_ in tokenize(ph))
                if n:
                    out.append((r.get("id"), n))
    return out


def contains_phrase(text: str, phrases: list[tuple[int | str, str]]):
    """Primeira regra cuja frase aparece em `text` (por tokens, sem acento/caixa)."""
    hay = " " + " ".join(t for t, *_ in tokenize(text)) + " "
    return next((rid for rid, ph in phrases if f" {ph} " in hay), None)


def analyze(words: list[dict], segments: list[dict], align: dict | None = None, rules: list[dict] | None = None) -> dict:
    """words: [{'text','start_ms','end_ms','speaker'}]; segments: [{'w0','w1','text','start_ms','end_ms','speaker'}].
    align: saída de scriptalign.align ou None. Devolve {'suggestions': [...], 'ignored_erro': [...]}."""
    ai = {it["seg"]: it for it in (align or {}).get("items", [])}
    sugg: list[dict] = []
    ignored: list[dict] = []
    erro_ranges: list[tuple[int, int]] = []
    ignore_ctx = phrases_of(rules, "ignore_erro_context")
    extra_cues = phrases_of(rules, "extra_cue")

    for i, w in enumerate(words):
        if _clean(w["text"]) not in ERRO_FORMS:
            continue
        si = _seg_of(segments, i)
        ctx_rule = contains_phrase(segments[si]["text"], ignore_ctx)
        if ctx_rule is not None or not is_marker(words, segments, i):
            ignored.append({"word_idx": i, "start_ms": w["start_ms"], "context": segments[si]["text"][:120],
                            "rule_id": ctx_rule})
            continue
        end = w["end_ms"]
        seg = segments[si]
        if i == seg["w1"] - 1:
            redo_si = si + 1 if si + 1 < len(segments) else None
            redo_text = segments[redo_si]["text"] if redo_si is not None else ""
        else:
            redo_si, redo_text = si, " ".join(x["text"] for x in words[i + 1:seg["w1"]])
        if redo_si is None:
            redo_idx: list[int] = []
        elif redo_si == si:
            redo_idx = list(range(i + 1, seg["w1"]))
        else:
            redo_idx = list(range(segments[redo_si]["w0"], segments[redo_si]["w1"]))
        k = _restart_index(words, i, redo_idx)
        if k is not None:
            start, first_si = words[k]["start_ms"], _seg_of(segments, k)
            start_how = "recomeço repete o início da tentativa descartada"
        else:
            start, first_si = _sentence_start(words, segments, i, si)
            start_how = "início estimado pela pontuação (recomeço não repete o trecho anterior)"
        removed = " ".join(x["text"] for x in words if start <= x["start_ms"] and x["end_ms"] <= end)
        speakers = {x.get("speaker") for x in words if start <= x["start_ms"] and x["end_ms"] <= end} - {None}
        level, why = ("media" if k is not None else "baixa"), [start_how]
        script_ref = None
        if align:
            a_first = ai.get(first_si)
            a_redo = ai.get(redo_si) if redo_si is not None and redo_si != si else None
            if a_redo and a_redo["kind"] == "matched":
                script_ref = [a_redo["script_start"], a_redo["script_end"]]
                if a_first and a_first["kind"] == "matched" and abs(a_first["script_start"] - a_redo["script_start"]) <= 40:
                    level = "alta" if k is not None else "media"
                    why = why + ["o recomeço retoma o mesmo ponto do roteiro da tentativa descartada"]
                else:
                    why = why + ["recomeço aderente ao roteiro, mas o início da tentativa não confere"]
            else:
                why = why + ["roteiro não ajuda a localizar o recomeço"]
        if end - start > LONG_RANGE_MS:
            level, why = "baixa", why + [f"intervalo longo ({(end - start) / 1000:.0f}s)"]
        if len(speakers) > 1:
            level, why = "baixa", why + ["intervalo passa por mais de um falante"]
        erro_ranges.append((start, end))
        sugg.append({"start_ms": start, "end_ms": end, "category": "speech_error",
                     "rationale": f"Palavra «erro» marca tentativa descartada; {why[0]}.",
                     "evidence": {"rule": "erro_marker", "level": level, "reasons": why, "removed_text": removed,
                                  "redo_text": redo_text, "erro_word_idx": i, "script_ref": script_ref,
                                  "speakers": sorted(speakers)}})

    def covered(s: int, e: int) -> bool:
        return any(s < b and e > a for a, b in erro_ranges)

    # pistas verbais de correção (sem «erro»)
    for si, seg in enumerate(segments):
        cue = CUE_RE.search(norm(re.sub(r"[^\w\s]", " ", seg["text"]))) or contains_phrase(seg["text"], extra_cues) is not None
        if cue and not covered(seg["start_ms"], seg["end_ms"]):
            sugg.append({"start_ms": seg["start_ms"], "end_ms": seg["end_ms"], "category": "speech_error",
                         "rationale": "Fala contém pista de correção/regravação; revisar.",
                         "evidence": {"rule": "cue_phrase", "level": "baixa", "text": seg["text"]}})

    if align:
        sugg += _repetitions(segments, ai, covered)
        sugg += _off_script(segments, ai, covered)
    protect = phrases_of(rules, "protect_phrase")
    suppressed: list[dict] = []
    if protect:
        kept = []
        for sg in sugg:
            txt = " ".join(x["text"] for x in words if x["end_ms"] > sg["start_ms"] and x["start_ms"] < sg["end_ms"])
            rid = contains_phrase(txt, protect)
            (suppressed if rid is not None else kept).append({**sg, "rule_id": rid} if rid is not None else sg)
        sugg = kept
    sugg.sort(key=lambda s: s["start_ms"])
    return {"suggestions": sugg, "ignored_erro": ignored, "suppressed_by_rules": suppressed}


def _repetitions(segments, ai, covered) -> list[dict]:
    """Segmentos vizinhos aderentes ao mesmo ponto do roteiro = tomadas repetidas. Sugere revisar a menos
    aderente (nunca presume que a última é a melhor)."""
    out = []
    for i in range(len(segments) - 1):
        a, b = ai.get(i), ai.get(i + 1)
        if not (a and b and a["kind"] == b["kind"] == "matched"):
            continue
        if abs(a["script_start"] - b["script_start"]) > 40 or segments[i + 1]["start_ms"] - segments[i]["end_ms"] > 15_000:
            continue
        # completude = quanto do roteiro a tomada cobre; empate: menor aderência, depois a mais antiga
        ka, kb = (a["matched_tokens"], a["adherence"]), (b["matched_tokens"], b["adherence"])
        worse = i if ka <= kb else i + 1
        s = segments[worse]
        if covered(s["start_ms"], s["end_ms"]):
            continue
        out.append({"start_ms": s["start_ms"], "end_ms": s["end_ms"], "category": "repetition",
                    "rationale": "Mesmo trecho do roteiro falado mais de uma vez; esta tomada cobre menos do roteiro.",
                    "evidence": {"rule": "repeated_take", "level": "baixa",
                                 "script_tokens": {"this": ai[worse]["matched_tokens"], "other": ai[1 + 2 * i - worse]["matched_tokens"]},
                                 "text": s["text"]}})
    return out


def _off_script(segments, ai, covered) -> list[dict]:
    groups, cur = [], []
    for i, seg in enumerate(segments):
        if ai.get(i, {}).get("kind") == "off_script" and not covered(seg["start_ms"], seg["end_ms"]):
            if cur and seg["start_ms"] - segments[cur[-1]]["end_ms"] > OFFSCRIPT_GROUP_GAP_MS:
                groups.append(cur)
                cur = []
            cur.append(i)
        elif cur:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        s, e = segments[g[0]]["start_ms"], segments[g[-1]]["end_ms"]
        if e - s < OFFSCRIPT_MIN_MS:
            continue
        out.append({"start_ms": s, "end_ms": e, "category": "off_script",
                    "rationale": "Fala fora do roteiro: pode ser bastidor ou improviso do tema; revisar.",
                    "evidence": {"rule": "off_script", "level": "baixa",
                                 "text": " ".join(segments[k]["text"] for k in g)}})
    return out
