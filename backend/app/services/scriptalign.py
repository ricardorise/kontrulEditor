"""Alinhamento roteiro ↔ transcrição (puro, sem I/O). O roteiro é referência; nunca substitui a fala."""
import re
import unicodedata
from difflib import SequenceMatcher

MATCH_MIN = 0.55      # aderência mínima para considerar o segmento "do roteiro"
RESTART_MIN = 0.70    # exigida ao buscar fora da janela corrente (recomeço)
LOOKBACK_TOKENS = 80  # tolerância para recomeços logo atrás
TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def norm(token: str) -> str:
    t = unicodedata.normalize("NFD", token.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[tuple[str, int, int]]:
    return [(norm(m.group()), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def _count(seg: list[str], win: list[str]) -> tuple[int, int | None, int | None]:
    """Tokens da fala achados em ordem na janela (ignora acertos soltos de palavra curta)."""
    sm = SequenceMatcher(None, seg, win, autojunk=False)
    matched, first, last = 0, None, None
    for a, b, n in sm.get_matching_blocks():
        if n == 0:
            continue
        if n < 2 and len(seg[a]) < 5:
            continue
        matched += n
        first = b if first is None else first
        last = b + n
    return matched, first, last


def align(segments: list[dict], script_text: str) -> dict:
    """segments: [{'text', 'w0', 'w1'}]. Devolve {'items': [...], 'unspoken': [...]}.
    item = {'seg': i, 'kind': matched|off_script, 'adherence', 'script_start', 'script_end'} (offsets de caractere)."""
    stoks = tokenize(script_text)
    snorm = [t[0] for t in stoks]
    covered = [False] * len(stoks)
    items, ptr = [], 0
    for i, seg in enumerate(segments):
        toks = [t[0] for t in tokenize(seg["text"])]
        item = {"seg": i, "kind": "off_script", "adherence": 0.0, "matched_tokens": 0, "script_start": 0, "script_end": 0}
        items.append(item)
        if not toks or not snorm:
            continue
        lo = max(0, ptr - LOOKBACK_TOKENS)
        hi = min(len(snorm), ptr + 3 * len(toks) + 40)
        best = None
        for (a, b, need) in ((lo, hi, MATCH_MIN), (0, len(snorm), RESTART_MIN)):
            m, f, l = _count(toks, snorm[a:b])
            if f is not None and m / len(toks) >= need:
                best = (m / len(toks), a + f, a + l)
                break
        if not best:
            continue
        adh, f, l = best
        item.update(kind="matched", adherence=round(adh, 3), matched_tokens=l - f,
                    script_start=stoks[f][1], script_end=stoks[l - 1][2])
        for k in range(f, l):
            covered[k] = True
        ptr = l
    return {"items": items, "unspoken": _unspoken(script_text, stoks, covered)}


def _unspoken(text: str, stoks, covered) -> list[dict]:
    """Sentenças do roteiro com pouca cobertura (<30%) pela fala."""
    out = []
    for m in re.finditer(r"[^.!?…\n]+[.!?…]*", text):
        idx = [k for k, t in enumerate(stoks) if m.start() <= t[1] < m.end()]
        if len(idx) < 2:
            continue
        if sum(covered[k] for k in idx) / len(idx) < 0.30:
            out.append({"script_start": m.start(), "script_end": m.end(), "kind": "unspoken"})
    return out
