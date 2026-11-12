"""Constrói transcrições sintéticas: lista de (texto, pausa_antes_ms) por segmento."""


def build(segs: list[str], gap_ms: int = 700, word_ms: int = 300):
    words, segments, t = [], [], 0
    for text in segs:
        w0, t = len(words), t + gap_ms
        s_start = t
        for tok in text.split():
            words.append({"text": tok, "start_ms": t, "end_ms": t + word_ms, "speaker": None})
            t += word_ms + 20
        segments.append({"w0": w0, "w1": len(words), "text": text, "start_ms": s_start, "end_ms": t, "speaker": None})
    return words, segments
