from dataclasses import replace
from decimal import Decimal

import pytest

from app.errors import DomainError
from app.modules.m1_intake.service import accept
from app.modules.m2_calibration.certificates import HEADER, certificates
from app.modules.m2_calibration.service import calibrate
from app.sources import Source


# TRAP-01
def test_gb18030_recovers_certificate_headers_and_ids(dirty):
    source = dirty["certificates"]
    with pytest.raises(UnicodeDecodeError):
        source.content.decode("utf-8")
    catalog = certificates(source)
    assert [(item.id, item.source.line) for item in catalog] == [
        ("L-旧", 2), ("L-1120", 3), ("R-1120", 4), ("R-借表", 5),
    ]


# TRAP-23
def test_exact_handoff_uses_new_certificate_and_no_double_match(dirty_result):
    stage = dirty_result["calibration"]
    wheel = next(item for item in stage["wheels"] if item["trigger"]["id"] == "0007-1L")
    assert (wheel["cert"], wheel["cert_ref"], wheel["kg"]) == ("L-1120", "certificates.csv:3", "2410.01")


# TRAP-11
def test_mixed_offsets_align_to_same_utc_clock(dirty_result):
    stage = dirty_result["calibration"]
    cert = next(item for item in stage["certificates"] if item["id"] == "L-1120")
    wheel = next(item for item in stage["wheels"] if item["trigger"]["id"] == "0007-1L")
    assert cert["start"] == wheel["trigger"]["time"] == "2026-11-20T12:00:00.100Z"


# TRAP-25
def test_overlap_isolates_with_both_certificates(dirty_result):
    stage = dirty_result["calibration"]
    issue = next(item for item in stage["issues"] if item["code"] == "CAL_OVERLAP")
    assert issue["source"]["line"] == 23
    assert issue["related"] == ["certificates.csv:4", "certificates.csv:5"]
    assert "0012-4R" not in {item["trigger"]["id"] for item in stage["wheels"]}


# TRAP-15
def test_affine_calibration_keeps_mixed_unit_weights_consistent(dirty_result):
    rows = {item["trigger"]["id"]: item for item in dirty_result["calibration"]["wheels"]}
    assert rows["0007-1R"]["kg"] == "2390.00"
    assert rows["0007-4R"]["trigger"]["raw_kg"] == "2605.000"
    assert rows["0007-4R"]["kg"] == "2600.00"


def test_expired_certificate_and_crossing_end_have_separate_codes(dirty_result):
    issues = {item["source"]["line"]: item["code"] for item in dirty_result["calibration"]["issues"]}
    assert issues == {23: "CAL_OVERLAP", 52: "CAL_MISSING", 53: "OUTSIDE_PASS", 54: "PASS_UNKNOWN"}


def test_corrected_weight_cap_retains_boundary_only(dirty):
    event = next(item for item in accept(dirty["triggers"])["accepted"] if item.id == "0007-1L")
    valid = replace(event, raw_kg=Decimal("24990"))
    invalid = replace(event, raw_kg=Decimal("24990.01"))
    calc = calibrate([valid, invalid], dirty)
    assert [item.kg for item in calc["wheels"]] == [Decimal("25000.00")]
    assert [(item.code, item.related) for item in calc["issues"]] == [("WHEEL_RANGE", ("certificates.csv:3",))]


def test_authority_rejects_bad_gain_instead_of_skipping_file_row():
    body = ",".join(HEADER) + "\nA,L,2026-01-01T00:00:00Z,2026-01-02T00:00:00Z,0,0\n"
    with pytest.raises(DomainError) as error:
        certificates(Source("cert.csv", body.encode()))
    assert (error.value.code, error.value.line, error.value.detail) == ("AUTHORITY_INVALID", 2, "BAD_VALUE")
