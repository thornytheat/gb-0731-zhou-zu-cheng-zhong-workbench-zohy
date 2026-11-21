from decimal import Decimal

from app.modules.m2_calibration.crossing import crossings
from app.modules.m6_reconcile.service import reconcile
from app.sources import Source


def row_for(result, key):
    return next(row for row in result["reconcile"]["rows"] if row["pass_id"] == key)


def test_ledger_partitions_source_lines_without_overlap(dirty_result):
    data = dirty_result["reconcile"]["ledger"]
    assert (data["raw"], data["effective"], data["duplicates"], data["isolated"], data["balanced"]) == (50, 22, 3, 25, True)
    accepted = [item[side]["trigger"]["source"]["line"] for item in dirty_result["axles"]["axes"] for side in ("left", "right")]
    discarded = [item["source"]["line"] for item in dirty_result["quarantine"] + dirty_result["debounce"]["duplicates"]]
    assert sorted(accepted + discarded) == [line for line in range(2, 55) if line not in (4, 12, 13)]


# TRAP-10
def test_decimal_rollup_matches_independently_summed_axles(dirty_result):
    expected = sum(Decimal(axis["total_kg"]) for axis in dirty_result["axles"]["axes"])
    actual = dirty_result["reconcile"]["ledger"]["wheel_kg"]
    assert Decimal(actual) == expected == Decimal("49590.01")


# TRAP-08
def test_latest_semantic_duplicate_and_inclusive_tolerance(dirty_result):
    row = row_for(dirty_result, "0007")
    assert (row["pass_id"], row["ticket"]["revision"], row["ticket"]["kg"], row["wheel_kg"]) == (
        "0007", 2, "20050.01", "20000.01",
    )
    assert (row["difference_kg"], row["status"], row["ticket_refs"]) == (
        "50.00", "matched", ["dirty-tickets.csv:2", "dirty-tickets.csv:4"],
    )


def test_latest_conflicting_revision_never_falls_back(dirty_result):
    row = row_for(dirty_result, "0019")
    assert row["codes"] == ["TICKET_CONFLICT", "WHEELS_INCOMPLETE"]
    assert row["ticket_refs"] == ["dirty-tickets.csv:6", "dirty-tickets.csv:8"]
    assert row["difference_kg"] is None


def test_no_weight_variance_does_not_clear_missing_wheel_evidence(dirty_result):
    row = row_for(dirty_result, "0023")
    assert (row["difference_kg"], row["codes"], row["status"]) == ("0.00", ["WHEELS_INCOMPLETE"], "review")
    assert row["review_refs"] == [f"dirty-triggers.csv:{line}" for line in range(33, 37)]


def test_bad_highest_revision_and_wrong_plate_cannot_supply_total(dirty_result):
    invalid = row_for(dirty_result, "0028")
    bad_plate = row_for(dirty_result, "0040")
    assert invalid["ticket_refs"] == ["dirty-tickets.csv:11", "dirty-tickets.csv:10"]
    assert [invalid["codes"][0], bad_plate["codes"][0]] == ["TICKET_INVALID", "TICKET_PLATE"]
    assert invalid["difference_kg"] is bad_plate["difference_kg"] is None


def test_late_ticket_right_boundary_is_excluded(dirty):
    header = "磅单号,车次,版次,车牌,签发时间,总重,单位"
    line = "WB-0007,0007,1,粤B·07612,2026-11-20T20:15:03.000+08:00,8000,kg"
    source = Source("tickets.csv", f"{header}\n{line}\n".encode())
    result = reconcile(source, crossings(dirty["passes"]), [], [], [], 0)
    actual = next(row for row in result["rows"] if row["pass_id"] == "0007")
    assert actual["codes"] == ["TICKET_TIME", "WHEELS_INCOMPLETE"]
    assert actual["ticket_refs"] == ("tickets.csv:2",)


def test_clean_rollup_has_no_review_and_zero_differences(clean_result):
    stage = clean_result["reconcile"]
    assert (stage["ledger"]["matched"], stage["ledger"]["review"], stage["ledger"]["wheel_kg"]) == (7, 0, "56000.00")
    assert {row["difference_kg"] for row in stage["rows"]} == {"0.00"}
