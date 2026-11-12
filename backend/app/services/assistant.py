"""Assistente por prompt (RF06). Planner determinístico (sem LLM): interpreta comandos em português e devolve
OPERAÇÕES ESTRUTURADAS validadas por dry-run. Nunca gera nem executa FFmpeg/shell/SQL.
Ponto de extensão: um provedor LLM pode implementar `plan(prompt, ctx) -> dict` com o mesmo contrato; a saída dele
também passaria pela mesma validação (`_validate`). O texto do prompt e da fala é dado, nunca instrução privilegiada."""
import re

from app.services import timeline as T
from app.services.placement import asset_terms, terms
from app.services.scriptalign import norm, tokenize

TIME = r"(?:\d+:\d{1,2}(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*(?:s|seg|segundos?|min|minutos?)?)"
INSERT_VERBS = r"(?:insira|inserir|coloque|colocar|adicione|adicionar|ponha|inclua|incluir)"
DEFAULT_MS = 4000


def parse_time(s: str) -> int | None:
    s = s.strip().lower().replace(",", ".")
    m = re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)", s)
    if m:
        return round((int(m.group(1)) * 60 + float(m.group(2))) * 1000)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(min\w*|s|seg\w*)?", s)
    if not m:
        return None
    v = float(m.group(1))
    return round(v * (60000 if (m.group(2) or "").startswith("min") else 1000))


def _plain(text: str) -> str:
    return " ".join(t for t, *_ in tokenize(text))


def _find_asset(ref: str, assets: list[dict]) -> dict | None:
    ref = re.sub(r"\b(?:no |na |em )?(?:canto|pip|picture in picture)\b.*", "", ref)  # posição não faz parte do nome
    rt = set(terms(ref)) or {t for t, *_ in tokenize(ref)}
    best, score = None, 0.0
    for a in assets:
        w = asset_terms(a)
        sc = sum(w.get(t, 0) for t in rt)
        if sc > score:
            best, score = a, sc
    return best


def _find_phrase(phrase: str, words: list[dict], doc: dict | None, main_id: str | None) -> tuple[int, int] | None:
    """(origem_ms, saída_ms) da primeira ocorrência da frase na fala que ainda está na timeline."""
    pt = [t for t, *_ in tokenize(phrase)]
    wt = [" ".join(t for t, *_ in tokenize(w["text"])) for w in words]
    for i in range(len(wt) - len(pt) + 1):
        if wt[i:i + len(pt)] == pt:
            src = words[i]["start_ms"]
            out = T.source_to_output(doc, main_id, src) if doc and main_id else src
            if out is not None:
                return src, out
    return None


def plan(prompt: str, ctx: dict) -> dict:
    """ctx: doc, main_id, assets (list[dict] auxiliares prontas), assets_map (p/ validar), words, suggestions (list[dict])."""
    steps = []
    for raw in [p.strip() for p in re.split(r"[;\n]+|\s+depois\s+", prompt) if p.strip()]:
        steps.append(_step(raw, ctx))
    llm_rep = None
    if ctx.get("llm") is not None:
        from app.services import llm_assistant
        llm_rep = llm_assistant.fill(steps, ctx, ctx["llm"])
    ops: list[dict] = []
    decisions: list[dict] = []
    doc = ctx.get("doc")
    for st in steps:
        st["errors"] = list(st.get("errors", []))
        st["decisions"] = st.get("decisions", [])
        valid = []
        for op in st.get("operations", []):
            err, doc = _validate(op, doc, ctx)
            (st["errors"].append(err) if err else valid.append(op))
        st["operations"] = valid
        ops += valid
        decisions += st["decisions"]
    used = bool(llm_rep and llm_rep["status"] in ("ok",))
    return {"prompt": prompt, "provider": "rules+llm" if used else "rules", "llm": llm_rep, "steps": steps, "operations": ops, "decisions": decisions,
            "recognized": any(s["recognized"] for s in steps), "applied": False}


def _validate(op: dict, doc: dict | None, ctx: dict):
    if op["type"] == "apply_suggestion":  # valida no momento de aplicar (exige decisão aceita)
        return None, doc
    if doc is None:
        return "a timeline ainda não foi criada (inicie a edição)", doc
    try:
        new = T.apply_op(doc, op, ctx["assets_map"])
        T.validate(new, ctx["assets_map"])
        return None, new
    except T.TimelineError as e:
        return e.message, doc


def _step(raw: str, ctx: dict) -> dict:
    p = norm(raw)
    base = {"text": raw, "recognized": False, "summary": "", "operations": [], "decisions": [], "errors": []}

    m = re.search(r"\b(aceite|aprove|corte|aplique|remova)\s+tod[oa]s\s+(?:as|os)?\s*(?:sugest\w+|ocorrenc\w+)\s+(?:de|com)\s+confianca\s+(alta|media)", p)
    if m:
        verb, level = m.group(1), m.group(2)
        pend = [s for s in ctx["suggestions"] if s["status"] == "pending" and (s.get("evidence") or {}).get("level") == level]
        base.update(recognized=True, summary=f"{'Aceitar e cortar' if verb != 'aceite' and verb != 'aprove' else 'Aceitar'} {len(pend)} sugestão(ões) de confiança {level}")
        base["decisions"] = [{"suggestion_id": s["id"], "decision": "accept"} for s in pend]
        if verb in ("corte", "aplique", "remova"):
            base["operations"] = [{"type": "apply_suggestion", "suggestion_id": s["id"]} for s in pend]
        if not pend:
            base["errors"].append(f"nenhuma sugestão pendente com confiança {level}")
        return base

    m = re.search(rf"\b(?:corte|remova|tire|apague|elimine)\s+(?:o\s+)?(?:trecho\s+)?(?:de|entre|do)\s+(?P<a>{TIME})\s+(?:ate|a|e)\s+(?P<b>{TIME})", p)
    if m:
        a, b = parse_time(m["a"]), parse_time(m["b"])
        base.update(recognized=True, summary=f"Remover {m['a']} → {m['b']} (tempo do vídeo original)")
        if a is None or b is None or b <= a:
            base["errors"].append("intervalo de tempo inválido")
        else:
            base["operations"] = [{"type": "remove_range", "asset_id": ctx.get("main_id"), "start_ms": a, "end_ms": b}]
        return base

    m = re.search(rf"\b{INSERT_VERBS}\s+(?:a |o |as |os |uma? )?(?:midia |imagem |video |foto )?(?P<ref>.+?)\s+(?:quando|na hora que|no momento em que|assim que)\s+(?:eu |ele |ela |alguem )?(?:falar|falo|citar|cito|mencionar|menciono|disser|digo)\s+(?:sobre |de |do |da |dos |das )?(?P<phrase>.+?)(?:\s+(?:por|durante)\s+(?P<dur>{TIME}))?$", p)
    if m:
        asset = _find_asset(m["ref"], ctx["assets"])
        base.update(recognized=True, summary=f"Inserir «{m['ref']}» quando falar «{m['phrase']}»")
        if not asset:
            base["errors"].append(f"não encontrei mídia para «{m['ref']}» (confira nome/tags)")
            return base
        hit = _find_phrase(m["phrase"], ctx["words"], ctx.get("doc"), ctx.get("main_id"))
        if not hit:
            base["errors"].append(f"não encontrei «{m['phrase']}» na fala que continua na timeline")
            return base
        base["operations"] = [_insert(asset, hit[1], parse_time(m["dur"]) if m["dur"] else None, p)]
        base["summary"] += f" → {asset['filename']} em {hit[1] / 1000:.1f}s"
        return base

    m = re.search(rf"\b{INSERT_VERBS}\s+(?:a |o |as |os |uma? )?(?:midia |imagem |video |foto )?(?P<ref>.+?)\s+(?:em|aos?|no tempo|no minuto|no segundo)\s+(?P<t>{TIME})(?:\s+(?:por|durante)\s+(?P<dur>{TIME}))?(?P<rest>.*)$", p)
    if m:
        asset = _find_asset(m["ref"], ctx["assets"])
        at = parse_time(m["t"])
        base.update(recognized=True, summary=f"Inserir «{m['ref']}» em {m['t']} (tempo da saída)")
        if not asset:
            base["errors"].append(f"não encontrei mídia para «{m['ref']}» (confira nome/tags)")
        elif at is None:
            base["errors"].append("tempo inválido")
        else:
            base["operations"] = [_insert(asset, at, parse_time(m["dur"]) if m["dur"] else None, p)]
        return base

    base["errors"].append("não entendi o comando. Exemplos: «insira o logo quando eu falar sobre headset»; "
                          "«corte de 1:20 até 1:35»; «aceite todas as sugestões de confiança alta».")
    return base


def _insert(asset: dict, at_ms: int, dur: int | None, p: str) -> dict:
    d = dur or asset.get("suggested_duration_ms") or (DEFAULT_MS if asset["kind"] == "image" else min(5000, asset.get("duration_ms") or 5000))
    if "sequencial" in p or "empurr" in p:
        return {"type": "insert_sequential", "asset_id": asset["id"], "at_ms": at_ms, "duration_ms": d}
    mode = "pip" if re.search(r"\b(pip|canto|picture)\b", p) else "b_roll"
    return {"type": "insert_overlay", "asset_id": asset["id"], "timeline_start_ms": at_ms, "duration_ms": d,
            "mode": mode, "audio_policy": "keep_primary"}
