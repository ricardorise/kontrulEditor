from types import SimpleNamespace as NS

from app.services import youtube as Y

TEXT = ("Vamos falar sobre energia solar fotovoltaica e como os painéis funcionam.\n\n"
        "Depois falamos sobre baterias de lítio e armazenamento residencial.\n\n"
        "Este parágrafo nunca foi falado em gravação alguma.\n\ncurto")


def _setup():
    pars = Y.split_paragraphs(TEXT)
    words = [NS(idx=i, start_ms=i * 1000, end_ms=i * 1000 + 900) for i in range(20)]
    al = [NS(kind="matched", script_start=pars[0]["start"], script_end=pars[0]["end"], word_start_idx=0, word_end_idx=5),
          NS(kind="matched", script_start=pars[1]["start"], script_end=pars[1]["end"], word_start_idx=10, word_end_idx=15)]
    doc = {"clips": [{"track_id": "main", "asset_id": "a", "source_in_ms": 0, "source_out_ms": 9000, "timeline_start_ms": 0,
                      "duration_ms": 9000}]}  # mantém 0-9s; o 2º parágrafo (10-15s) foi cortado
    return pars, words, al, doc


def test_split_ignores_short_lines():
    assert len(Y.split_paragraphs(TEXT)) == 3


def test_states_follow_the_cuts():
    pars, words, al, doc = _setup()
    st = [Y.paragraph_state(p, al, words, doc, "a")["state"] for p in pars]
    assert st == ["mantido", "cortado", "nao_falado"]
    assert Y.paragraph_state(pars[0], [], words, doc, "a")["state"] == "sem_alinhamento"


def test_keyword_query_drops_stopwords():
    q = Y.keyword_query(Y.split_paragraphs(TEXT)[1]["text"])
    assert "lítio" in q or "litio" in q and "para" not in q.split()


def test_suggest_only_searches_kept_and_dedups(monkeypatch):
    pars, words, al, doc = _setup()
    states = [Y.paragraph_state(p, al, words, doc, "a") for p in pars]
    monkeypatch.setattr(Y.settings, "youtube_api_key", "k")
    calls = []
    monkeypatch.setattr(Y, "youtube_search", lambda q, n, key, lang: calls.append(q) or [
        {"video_id": f"v{len(calls)}a", "url": "u", "title": "t", "channel": "c", "published_at": None, "thumbnail": None},
        {"video_id": f"v{len(calls)}b", "url": "u", "title": "t", "channel": "c", "published_at": None, "thumbnail": None}])
    out = Y.suggest(pars, states, 1, None, "pt")
    assert len(calls) == 1 and len(out["paragraphs"][0]["videos"]) == 1
    assert out["paragraphs"][1]["videos"] == [] and out["paragraphs"][1]["state"] == "cortado"


def test_without_key_returns_search_links(monkeypatch):
    pars, words, al, doc = _setup()
    monkeypatch.setattr(Y.settings, "youtube_api_key", "")
    out = Y.suggest(pars, [Y.paragraph_state(p, al, words, doc, "a") for p in pars], 2, None, "pt")
    assert out["api_configured"] is False and out["paragraphs"][0]["search_url"].startswith("https://www.youtube.com/results?")
