from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.modules.m1_intake.service import accept
from app.modules.m2_calibration.service import calibrate
from app.modules.m4_axles.pair import match
from app.modules.m4_axles.spacing import classify_spacing


# TRAP-19
def test_nearest_pair_would_invent_axle_when_candidates_conflict(dirty_result):
    stage = dirty_result["axles"]
    ambiguous = [item for item in stage["issues"] if item["code"] == "PAIR_AMBIGUOUS"]
    assert {item["source"]["line"] for item in ambiguous} == {28, 29, 30}
    axes = [axis for axis in stage["axes"] if axis["pass_id"] == "0019"]
    assert [(item["left"]["trigger"]["id"], item["right"]["trigger"]["id"]) for item in axes] == [
        ("0019-3L", "0019-3R"),
    ]


def test_left_without_right_goes_to_review_without_estimated_load(dirty_result):
    stage = dirty_result["axles"]
    missing = {item["source"]["cells"][0] for item in stage["issues"] if item["code"] == "PAIR_MISSING"}
    assert missing == {"0012-3L", "0012-4L", "0031-1R"}
    assert len([row for row in stage["axes"] if row["pass_id"] == "0012"]) == 2


def test_multiple_tandem_hits_form_one_group_with_real_distances(dirty_result):
    axes = [row for row in dirty_result["axles"]["axes"] if row["pass_id"] == "0007"]
    assert [(row["id"], row["group"], row["gap_m"]) for row in axes] == [
        ("0007/A01", "0007/G01", None), ("0007/A02", "0007/G01", "1.3"),
        ("0007/A03", "0007/G01", "1.3"), ("0007/A04", "0007/G02", "2.75"),
    ]
    assert axes[0]["time"] == "2026-11-20T12:00:00.104500Z"


def test_bad_spacing_isolates_implicated_pairs_and_keeps_other_evidence(dirty_result):
    stage = dirty_result["axles"]
    assert {item["source"]["line"] for item in stage["issues"] if item["code"] == "SPACING_SHORT"} == {33, 34, 35, 36}
    assert {item["source"]["line"] for item in stage["issues"] if item["code"] == "SPACING_LONG"} == {39, 40, 41, 42}
    assert {axis["left"]["trigger"]["id"] for axis in stage["axes"] if axis["pass_id"] in {"0023", "0028"}} == {
        "0023-3L", "0028-3L",
    }


def test_pairing_includes_35_ms_and_rejects_36_ms(dirty, dirty_result):
    axe = next(axis for axis in dirty_result["axles"]["axes"] if axis["pass_id"] == "0040")
    assert axe["skew_ms"] == 35
    events = [item for item in accept(dirty["triggers"])["accepted"] if item.id in {"0040-1L", "0040-1R"}]
    cal = calibrate([events[0], replace(events[1], time=events[1].time + timedelta(milliseconds=1))], dirty)
    pairs, issues, _ = match(cal["wheels"], cal["passes"]["0040"])
    assert pairs == []
    assert [item.code for item in issues] == ["PAIR_MISSING", "PAIR_MISSING"]


def test_spacing_intervals_accept_exact_bounds_and_tandem_threshold(dirty):
    raw = [item for item in accept(dirty["triggers"])["accepted"] if item.id in {"0007-1L", "0007-1R"}]
    cal = calibrate(raw, dirty)
    crossing = cal["passes"]["0007"]
    pairs, _, _ = match(cal["wheels"], crossing)
    first = pairs[0]
    offsets = (0, 55, 235, 1435)
    candidates = [replace(first, time=first.time + timedelta(milliseconds=offset)) for offset in offsets]
    axes, issues = classify_spacing(candidates, [], crossing)
    assert issues == []
    assert [axis["gap_m"] for axis in axes] == [None, Decimal("0.55"), Decimal("1.8"), Decimal("12")]
    assert [axis["group"] for axis in axes] == ["0007/G01", "0007/G01", "0007/G01", "0007/G02"]


def test_unmatched_trigger_between_axes_breaks_spacing_inference(dirty):
    raw = [item for item in accept(dirty["triggers"])["accepted"] if item.id in {"0007-1L", "0007-1R"}]
    cal = calibrate(raw, dirty)
    crossing = cal["passes"]["0007"]
    pairs, _, _ = match(cal["wheels"], crossing)
    first = pairs[0]
    axes, issues = classify_spacing([first, replace(first, time=first.time + timedelta(seconds=2))],
                                    [first.time + timedelta(seconds=1)], crossing)
    assert issues == []
    assert [axis["group"] for axis in axes] == ["0007/G01", "0007/G02"]
