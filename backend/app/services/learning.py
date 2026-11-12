"""Memória de feedback (RF06): exemplos aceitos/rejeitados por projeto, recuperáveis e auditáveis.
Não há treinamento do modelo: o feedback só (1) anota novas sugestões com exemplos parecidos, ajustando o nível
qualitativo, e (2) gera propostas de regras que o usuário pode aceitar, editar ou apagar."""
import re
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EditingRule, Feedback, Suggestion
from app.services.placement import STOP
from app.services.rules import CUE_RE
from app.services.scriptalign import norm, tokenize

LEVELS = ["baixa", "media", "alta"]
SIM_MIN, MIN_EXAMPLES = 0.5, 2


def _toks(text: str) -> set[str]:
    return {t for t, *_ in tokenize(text) if len(t) >= 3 and t not in STOP}


def example_text(ev: dict | None) -> str:
    ev = ev or {}
    return ev.get("removed_text") or ev.get("text") or ""


def load_examples(db: Session, project_id) -> list[dict]:
    rows = db.execute(select(Feedback, Suggestion).join(Suggestion, Suggestion.id == Feedback.suggestion_id)
                      .where(Feedback.project_id == project_id)).all()
    out = []
    for fb, sg in rows:
        ev = sg.evidence or {}
        out.append({"suggestion_id": str(sg.id), "rule": ev.get("rule"), "category": sg.category, "text": example_text(ev),
                    "decision": fb.decision, "level": ev.get("level")})
    return out


def annotate(suggestions: list[dict], examples: list[dict]) -> None:
    """Anota (in-place) cada sugestão nova com exemplos parecidos e ajusta o nível. Nunca muda categoria/estado."""
    for s in suggestions:
        ev = s["evidence"]
        a = _toks(example_text(ev))
        if not a:
            continue
        sim = []
        for e in examples:
            b = _toks(e["text"])
            if e["rule"] == ev.get("rule") and b and len(a & b) / len(a | b) >= SIM_MIN:
                sim.append(e)
        if not sim:
            continue
        acc = sum(e["decision"] in ("accept", "adjust") for e in sim)
        rej = sum(e["decision"] == "reject" for e in sim)
        mem = {"similar": len(sim), "accepted": acc, "rejected": rej, "example_ids": [e["suggestion_id"] for e in sim[:5]]}
        cur = LEVELS.index(ev.get("level", "baixa")) if ev.get("level") in LEVELS else 0
        if rej >= MIN_EXAMPLES and acc == 0:
            ev["level"] = LEVELS[max(0, cur - 1)]
            mem["note"] = f"Você rejeitou {rej} sugestões parecidas antes."
        elif acc >= MIN_EXAMPLES and rej == 0:
            ev["level"] = LEVELS[min(2, cur + 1)]
            mem["note"] = f"Você aceitou {acc} sugestões parecidas antes."
        ev["memory"] = mem


def _key(ev: dict) -> str | None:
    text = example_text(ev)
    m = CUE_RE.search(norm(re.sub(r"[^\w\s]", " ", text)))
    if m:
        return m.group(0)
    toks = [t for t, *_ in tokenize(text)][:3]
    return " ".join(toks) if len(toks) >= 2 else None


def suggest_rules(db: Session, project_id) -> list[dict]:
    """Propostas de regra a partir de rejeições repetidas (≥2) com o mesmo padrão."""
    rows = db.execute(select(Feedback, Suggestion).join(Suggestion, Suggestion.id == Feedback.suggestion_id)
                      .where(Feedback.project_id == project_id, Feedback.decision == "reject")).all()
    groups: dict[tuple, list[str]] = defaultdict(list)
    for _fb, sg in rows:
        k = _key(sg.evidence or {})
        if k:
            groups[((sg.evidence or {}).get("rule"), k)].append(str(sg.id))
    have = {ph for r in db.scalars(select(EditingRule).where(EditingRule.kind == "protect_phrase", EditingRule.enabled.is_(True),
                                                             (EditingRule.project_id == project_id) | EditingRule.project_id.is_(None)))
            for ph in (r.params or {}).get("phrases", [])}
    out = []
    for (rule, key), ids in groups.items():
        if len(ids) >= MIN_EXAMPLES and key not in have:
            out.append({"kind": "protect_phrase", "params": {"phrases": [key]},
                        "text": f"Não sugerir cortes em trechos com «{key}» (você rejeitou {len(ids)} sugestões assim).",
                        "provenance": {"source": "feedback", "rule": rule, "suggestion_ids": ids}})
    return out
