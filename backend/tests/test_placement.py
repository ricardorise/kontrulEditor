from app.services import timeline as T
from app.services.placement import asset_terms, propose, terms
from tests.helpers import build

MAIN = "main-asset"


def A(id, filename, kind="image", tags=(), **kw):
    return {"id": id, "filename": filename, "kind": kind, "tags": list(tags), "description": None, "duration_ms": None, **kw}


WORDS, SEGS = build(["Hoje vamos falar do novo headset da Meta.", "O sistema de janelas ficou muito melhor agora.",
                     "No final deixe o seu like e se inscreva no canal."], gap_ms=1500, word_ms=300)


def test_terms_normalize_stem_and_drop_stopwords():
    assert terms("Os Headsets da META, número 3") == ["headset", "meta", "numero"]
    assert "de" not in terms("de do da") and terms("janelas") == ["janela"]
    w = asset_terms(A("1", "logo_meta.png", tags=["Headset"], description="ícone azul", intended_use="b-roll"))
    assert w == {"headset": 3.0, "icone": 1.5, "azul": 1.5, "logo": 1.0, "meta": 1.0}  # "b-roll" é modo, não assunto


def test_tag_match_places_at_the_spoken_word_and_explains():
    r = propose(WORDS, SEGS, [A("img1", "foto.png", tags=["headset"])])
    p = r["proposals"][0]
    word = next(w for w in WORDS if w["text"].lower() == "headset")
    assert p["source_start_ms"] == word["start_ms"] and p["timeline_start_ms"] == word["start_ms"]
    assert p["mode"] == "b_roll" and p["duration_ms"] == 4000 and p["matched_terms"] == ["headset"]
    assert "headset" in p["rationale"] and p["operation"]["type"] == "insert_overlay" and p["level"] == "media"


def test_media_without_match_is_reported_not_forced():
    r = propose(WORDS, SEGS, [A("x", "gato.png", tags=["gato", "pet"])])
    assert r["proposals"] == [] and r["unmatched"][0]["reason"] == "no_match"


def test_pip_by_intended_use_and_suggested_duration_and_video_cap():
    r = propose(WORDS, SEGS, [A("v", "like.mp4", kind="video", tags=["like", "inscreva"], intended_use="pip canto",
                                duration_ms=2500, suggested_duration_ms=9000)])
    p = r["proposals"][0]
    assert p["mode"] == "pip" and p["duration_ms"] == 2500 and p["level"] == "alta"  # duas tags: score 6


def test_description_alone_is_low_level():
    r = propose(WORDS, SEGS, [A("d", "img1.png", description="janelas sistema")])
    assert r["proposals"][0]["level"] == "media" and r["proposals"][0]["score"] == 3.0


def test_respects_cuts_and_existing_overlays():
    doc = T.apply_op(T.empty_doc(), {"type": "init_main", "asset_id": MAIN}, {MAIN: {"kind": "video", "duration_ms": 60_000}})
    word = next(w for w in WORDS if w["text"].lower() == "headset")
    cut = T.apply_op(doc, {"type": "remove_range", "start_ms": word["start_ms"] - 100, "end_ms": word["end_ms"] + 100}, {MAIN: {}})
    r = propose(WORDS, SEGS, [A("img1", "foto.png", tags=["headset"])], doc=cut, main_id=MAIN)
    assert r["proposals"] == [] and r["unmatched"][0]["reason"] == "no_slot"  # a fala foi cortada
    r2 = propose(WORDS, SEGS, [A("img1", "foto.png", tags=["headset"]), A("img2", "outra.png", tags=["headset"])], doc=doc, main_id=MAIN)
    assert len(r2["proposals"]) == 1 and r2["unmatched"][0]["reason"] == "no_slot"  # sem sobrepor propostas


def test_priority_wins_the_contested_slot():
    r = propose(WORDS, SEGS, [A("low", "a.png", tags=["headset"], priority=0), A("high", "b.png", tags=["headset"], priority=2)])
    assert [p["asset_id"] for p in r["proposals"]] == ["high"]


def test_already_inserted_media_is_not_proposed_again():
    doc = T.apply_op(T.empty_doc(), {"type": "init_main", "asset_id": MAIN}, {MAIN: {"kind": "video", "duration_ms": 60_000}})
    doc = T.apply_op(doc, {"type": "insert_overlay", "asset_id": "img1", "timeline_start_ms": 40_000, "duration_ms": 2000},
                     {"img1": {"kind": "image", "duration_ms": None}})
    r = propose(WORDS, SEGS, [A("img1", "foto.png", tags=["headset"])], doc=doc, main_id=MAIN)
    assert r["proposals"] == [] and r["unmatched"][0]["reason"] == "already_used"
    r2 = propose(WORDS, SEGS, [A("img1", "foto.png", tags=["headset"])], doc=doc, main_id=MAIN, max_per_asset=2)
    assert len(r2["proposals"]) == 1
