import pytest

from app.services import timeline as T

A = "aaaa"
ASSETS = {A: {"kind": "video", "duration_ms": 60_000}, "img": {"kind": "image", "duration_ms": None},
          "vid2": {"kind": "video", "duration_ms": 20_000}}


def base():
    return T.apply_op(T.empty_doc(), {"type": "init_main", "asset_id": A}, ASSETS)


def ap(doc, **op):
    new = T.apply_op(doc, op, ASSETS)
    T.validate(new, ASSETS)
    return new


def spans(doc):
    return [(c["source_in_ms"], c["source_out_ms"], c["timeline_start_ms"]) for c in T.main_clips(doc)]


def test_init_and_immutability_of_input():
    d = base()
    assert d["duration_ms"] == 60_000 and spans(d) == [(0, 60_000, 0)]
    before = str(d)
    ap(d, type="remove_range", start_ms=10_000, end_ms=20_000)
    assert str(d) == before  # operação não altera o documento anterior
    with pytest.raises(T.TimelineError):
        T.apply_op(d, {"type": "init_main", "asset_id": A}, ASSETS)


def test_remove_range_ripples_and_maps_coordinates():
    d = ap(base(), type="remove_range", start_ms=10_000, end_ms=20_000)
    assert spans(d) == [(0, 10_000, 0), (20_000, 60_000, 10_000)] and d["duration_ms"] == 50_000
    assert T.source_to_output(d, A, 25_000) == 15_000 and T.source_to_output(d, A, 15_000) is None
    assert T.output_to_source(d, 15_000) == (A, 25_000)


def test_remove_multiple_and_edges_and_noeffect():
    d = ap(base(), type="remove_range", start_ms=0, end_ms=5_000)
    d = ap(d, type="remove_range", start_ms=50_000, end_ms=60_000)
    assert spans(d) == [(5_000, 50_000, 0)]
    with pytest.raises(T.TimelineError) as e:
        T.apply_op(d, {"type": "remove_range", "start_ms": 0, "end_ms": 1000}, ASSETS)
    assert e.value.code == "no_effect"
    with pytest.raises(T.TimelineError):
        T.apply_op(d, {"type": "remove_range", "start_ms": 5000, "end_ms": 5000}, ASSETS)
    with pytest.raises(T.TimelineError):
        T.apply_op(base(), {"type": "remove_range", "start_ms": 0, "end_ms": 60_000}, ASSETS)  # esvazia


def test_restore_range_merges_back():
    d = ap(base(), type="remove_range", start_ms=10_000, end_ms=20_000)
    d = ap(d, type="restore_range", start_ms=10_000, end_ms=20_000)
    assert spans(d) == [(0, 60_000, 0)] and d["duration_ms"] == 60_000
    d = ap(d, type="remove_range", start_ms=10_000, end_ms=20_000)
    with pytest.raises(T.TimelineError) as e:
        T.apply_op(d, {"type": "restore_range", "start_ms": 5_000, "end_ms": 15_000}, ASSETS)  # sobrepõe
    assert e.value.code == "overlaps_existing"


def test_overlay_shifts_with_ripple_and_free_track_allocation():
    d = ap(base(), type="insert_overlay", asset_id="img", timeline_start_ms=30_000, duration_ms=4_000)
    d = ap(d, type="insert_overlay", asset_id="vid2", timeline_start_ms=31_000, duration_ms=3_000, mode="pip")
    tracks = {c["asset_id"]: c["track_id"] for c in T.overlay_clips(d)}
    assert tracks["img"] != tracks["vid2"]  # sobrepostos → trilhas distintas
    d = ap(d, type="remove_range", start_ms=10_000, end_ms=20_000)  # 10s a menos antes dos overlays
    assert sorted(c["timeline_start_ms"] for c in T.overlay_clips(d)) == [20_000, 21_000]


def test_split_reorder_and_remove_clip():
    d = base()
    cid = T.main_clips(d)[0]["id"]
    d = ap(d, type="split", clip_id=cid, at_ms=20_000)
    c1, c2 = T.main_clips(d)
    assert (c1["source_out_ms"], c2["source_in_ms"], c2["timeline_start_ms"]) == (20_000, 20_000, 20_000)
    d = ap(d, type="reorder_main", clip_ids=[c2["id"], c1["id"]])
    assert [(c["source_in_ms"], c["timeline_start_ms"]) for c in T.main_clips(d)] == [(20_000, 0), (0, 40_000)]
    with pytest.raises(T.TimelineError):
        T.apply_op(d, {"type": "reorder_main", "clip_ids": [c1["id"]]}, ASSETS)
    d = ap(d, type="remove_clip", clip_id=c2["id"])
    assert d["duration_ms"] == 20_000
    with pytest.raises(T.TimelineError):
        T.apply_op(d, {"type": "split", "clip_id": T.main_clips(d)[0]["id"], "at_ms": 0}, ASSETS)


def test_insert_sequential_splits_and_ripples():
    d = ap(base(), type="insert_sequential", asset_id="vid2", at_ms=30_000, duration_ms=5_000)
    assert d["duration_ms"] == 65_000
    assert spans(d) == [(0, 30_000, 0), (0, 5_000, 30_000), (30_000, 60_000, 35_000)]
    assert T.output_to_source(d, 32_000) == ("vid2", 2_000)


def test_overlay_validation():
    d = base()
    for bad in ({"asset_id": "img", "timeline_start_ms": 70_000, "duration_ms": 1000},
                {"asset_id": "vid2", "timeline_start_ms": 0, "duration_ms": 25_000},
                {"asset_id": "img", "timeline_start_ms": 0, "duration_ms": 1000, "mode": "x"},
                {"asset_id": "nope", "timeline_start_ms": 0, "duration_ms": 1000},
                {"asset_id": "img", "timeline_start_ms": -1, "duration_ms": 1000}):
        with pytest.raises(T.TimelineError):
            T.apply_op(d, {"type": "insert_overlay", **bad}, ASSETS)


def test_move_trim_overlay_and_overlap_invariant():
    d = ap(base(), type="insert_overlay", asset_id="vid2", timeline_start_ms=0, duration_ms=5_000, track_id="overlay-1")
    d = ap(d, type="insert_overlay", asset_id="vid2", timeline_start_ms=10_000, duration_ms=5_000, track_id="overlay-1")
    first = T.overlay_clips(d)[0]
    d = ap(d, type="trim_clip", clip_id=first["id"], source_out_ms=3_000)
    assert T.overlay_clips(d)[0]["duration_ms"] == 3_000
    moved = T.apply_op(d, {"type": "move_clip", "clip_id": first["id"], "timeline_start_ms": 12_000}, ASSETS)
    with pytest.raises(T.TimelineError) as e:
        T.validate(moved, ASSETS)
    assert e.value.code == "invariant"


def test_validate_catches_out_of_duration():
    d = base()
    d["clips"][0]["source_out_ms"] = 70_000
    d["clips"][0]["duration_ms"] = 70_000
    d["duration_ms"] = 70_000
    with pytest.raises(T.TimelineError):
        T.validate(d, ASSETS)
