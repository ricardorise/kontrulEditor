from app.services.rules import analyze
from app.services.scriptalign import align
from tests.helpers import build

ROTEIRO = """A nova versão chegou ao canal de testes públicos.
Ela traz uma gestão de janelas totalmente refeita.
Vamos direto ao ponto técnico da parada.
"""


def cats(out):
    return [(s["category"], s["evidence"]["level"]) for s in out["suggestions"]]


def test_erro_marker_removes_failed_attempt_until_erro():
    words, segs = build(["A nova versão chegou ao canal de testes públicos.",
                         "Ela traz uma gestão de janelas totalmente refeita, ih travou, erro.",
                         "Ela traz uma gestão de janelas totalmente refeita.",
                         "Vamos direto ao ponto técnico da parada."])
    out = analyze(words, segs)
    assert len(out["suggestions"]) == 1
    s = out["suggestions"][0]
    assert s["category"] == "speech_error"
    assert s["start_ms"] == segs[1]["start_ms"] and s["end_ms"] == words[segs[1]["w1"] - 1]["end_ms"]
    assert s["evidence"]["redo_text"].startswith("Ela traz")
    assert s["evidence"]["level"] == "media"


def test_erro_inside_normal_sentence_is_not_marker():
    words, segs = build(["Esse erro foi grave para a empresa inteira.", "Seguimos adiante com o plano normalmente."],
                        gap_ms=50)
    out = analyze(words, segs)
    assert out["suggestions"] == [] and len(out["ignored_erro"]) == 1


def test_script_confirms_level_alta():
    words, segs = build(["A nova versão chegou ao canal de testes públicos.",
                         "Ela traz uma gestão de janelas, ih, erro.",
                         "Ela traz uma gestão de janelas totalmente refeita."])
    out = analyze(words, segs, align(segs, ROTEIRO))
    erro = [s for s in out["suggestions"] if s["evidence"]["rule"] == "erro_marker"][0]
    assert erro["evidence"]["level"] == "alta" and erro["evidence"]["script_ref"]


def test_no_restart_match_falls_back_with_low_confidence():
    words, segs = build(["Alguma coisa totalmente diferente foi dita aqui, erro.", "Agora sim outra frase completa."])
    s = analyze(words, segs)["suggestions"][0]
    assert s["evidence"]["level"] == "baixa"


def test_off_script_grouped_and_yellow_category():
    words, segs = build(["A nova versão chegou ao canal de testes públicos.",
                         "Alguém pode me trazer um copo de água por favor.",
                         "Obrigado, pode deixar ali em cima da mesa mesmo.",
                         "Vamos direto ao ponto técnico da parada."], gap_ms=500, word_ms=250)
    out = analyze(words, segs, align(segs, ROTEIRO))
    off = [s for s in out["suggestions"] if s["category"] == "off_script"]
    assert len(off) == 1 and off[0]["start_ms"] == segs[1]["start_ms"] and off[0]["end_ms"] == segs[2]["end_ms"]
    assert off[0]["evidence"]["level"] == "baixa"  # nunca decidido sozinho


def test_repetition_flags_less_adherent_take_not_just_the_first():
    words, segs = build(["Ela traz uma gestão de janelas totalmente refeita.",
                         "Ela traz uma gestão de janelas.",
                         "Vamos direto ao ponto técnico da parada."])
    out = analyze(words, segs, align(segs, ROTEIRO))
    rep = [s for s in out["suggestions"] if s["category"] == "repetition"]
    assert len(rep) == 1 and rep[0]["start_ms"] == segs[1]["start_ms"]  # a mais curta/menos aderente


def test_alignment_unspoken_and_matched_in_order():
    _, segs = build(["A nova versão chegou ao canal de testes públicos.", "Vamos direto ao ponto técnico da parada."])
    al = align(segs, ROTEIRO)
    assert [i["kind"] for i in al["items"]] == ["matched", "matched"]
    assert len(al["unspoken"]) == 1  # "gestão de janelas..." nunca foi falada


def test_cue_phrase_is_low_confidence_suggestion():
    words, segs = build(["Primeira frase normal do episódio de hoje.", "Peraí, deixa eu falar de novo essa parte."])
    s = analyze(words, segs)["suggestions"]
    assert len(s) == 1 and s[0]["evidence"]["rule"] == "cue_phrase" and s[0]["evidence"]["level"] == "baixa"
