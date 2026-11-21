from decimal import Decimal

from app.modules.m5_balance.service import balance
from app.modules.m5_balance.thresholds import grade


def test_warn_threshold_includes_exact_ten_percent(dirty_result):
    row = next(row for row in dirty_result["balance"]["rows"] if row["id"] == "0007/A02")
    assert (row["percent"], row["level"], row["left_kg"], row["right_kg"]) == ("10.00", "warn", "2750.00", "2250.00")


def test_severe_threshold_includes_exact_twenty_percent(dirty_result):
    row = next(row for row in dirty_result["balance"]["rows"] if row["id"] == "0007/A03")
    assert (row["percent"], row["level"], row["heavy"]) == ("20.00", "severe", "L")
    assert (row["left_ref"], row["right_ref"]) == ("dirty-triggers.csv:14", "dirty-triggers.csv:15")


def test_rounding_for_display_does_not_change_level():
    level, display = grade(Decimal("549.99"), Decimal("450.01"))
    assert display == Decimal("10.00")
    assert level == "pass"


def test_swapping_sides_preserves_grade():
    assert grade(Decimal("3000"), Decimal("2000")) == grade(Decimal("2000"), Decimal("3000")) == (
        "severe", Decimal("20.00"),
    )


def test_clean_equal_wheels_have_no_heavy_side(clean_result):
    assert clean_result["balance"]["counts"] == {"pass": 14, "warn": 0, "severe": 0}
    assert {(row["heavy"], row["percent"]) for row in clean_result["balance"]["rows"]} == {(None, "0.00")}


def test_quarantined_wheels_never_participate_in_grading(dirty_result):
    stage = dirty_result["balance"]
    assert stage["counts"] == {"pass": 9, "warn": 1, "severe": 1}
    assert {row["id"] for row in stage["rows"]} == {axis["id"] for axis in dirty_result["axles"]["axes"]}


def test_no_axes_produces_zero_grade_counts():
    assert balance([]) == {"rows": [], "counts": {"pass": 0, "warn": 0, "severe": 0}}
