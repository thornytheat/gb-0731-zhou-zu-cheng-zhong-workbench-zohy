from dataclasses import replace
from datetime import timedelta

from app.modules.m1_intake.service import accept
from app.modules.m2_calibration.service import calibrate
from app.modules.m3_debounce.service import debounce


def test_same_id_mixed_unit_retransmission_retains_first_source(dirty_result):
    duplicate = next(item for item in dirty_result["debounce"]["duplicates"] if item["code"] == "REPLAY_ID")
    assert (duplicate["source"]["ref"], duplicate["related"], duplicate["kept_id"]) == (
        "dirty-triggers.csv:8", ["dirty-triggers.csv:7"], "0007-2R",
    )


# TRAP-14
def test_same_id_conflict_rejects_both_records(dirty_result):
    stage = dirty_result["debounce"]
    assert [(row["code"], row["source"]["line"], row["related"]) for row in stage["issues"]] == [
        ("ID_CONFLICT", 45, ["dirty-triggers.csv:46"]), ("ID_CONFLICT", 46, ["dirty-triggers.csv:45"]),
    ]
    assert "0031-1L" not in {row["trigger"]["id"] for row in stage["kept"]}


def test_debounce_boundary_is_inclusive_and_lane_specific(dirty_result):
    stage = dirty_result["debounce"]
    by_line = {item["source"]["line"]: item for item in stage["duplicates"]}
    assert by_line[6]["kept_id"] == "0007-1L"
    assert by_line[9]["kept_id"] == "0007-2R"
    assert "0007-1R" in {item["trigger"]["id"] for item in stage["kept"]}


def test_debounce_measures_from_anchor_not_previous_bounce(dirty):
    events = accept(dirty["triggers"])["accepted"]
    base = next(item for item in events if item.id == "0007-1L")
    chain = [replace(base, id=f"pulse-{offset}", time=base.time + timedelta(milliseconds=offset),
                     source=replace(base.source, line=100 + offset, end_line=100 + offset)) for offset in (0, 12, 13, 24)]
    wheels = calibrate(chain, dirty)["wheels"]
    stage = debounce(chain, list(reversed(wheels)))
    assert [item.trigger.id for item in stage["kept"]] == ["pulse-0", "pulse-13"]
    assert [item.kept_id for item in stage["duplicates"]] == ["pulse-0", "pulse-13"]


def test_debounce_never_merges_across_vehicle_passes(dirty):
    events = accept(dirty["triggers"])["accepted"]
    base = next(item for item in events if item.id == "0007-1L")
    wheel = calibrate([base], dirty)["wheels"][0]
    other = replace(base, id="other", pass_id="0012")
    stage = debounce([base, other], [wheel, replace(wheel, trigger=other)])
    assert [item.trigger.pass_id for item in stage["kept"]] == ["0007", "0012"]
    assert stage["duplicates"] == []


def test_debounce_partitions_every_calibrated_trigger(dirty_result):
    stage = dirty_result["debounce"]
    assert (len(stage["kept"]), len(stage["duplicates"]), len(stage["issues"])) == (36, 3, 2)
    assert len(dirty_result["calibration"]["wheels"]) == 36 + 3 + 2
