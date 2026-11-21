from decimal import Decimal

import pytest

from app.errors import DomainError
from app.modules.m1_intake.parse import HEADER
from app.modules.m1_intake.reader import read_table
from app.modules.m1_intake.service import accept
from app.sources import Source


# TRAP-02
def test_bom_header_uses_record_id(dirty):
    source = dirty["triggers"]
    assert source.content.startswith(b"\xef\xbb\xbf")
    table = read_table(source, HEADER)
    assert table.encoding == "utf-8-sig"
    assert table.columns(table.rows[0])["记录号"] == "0007-2L"


# TRAP-03
def test_multiline_note_keeps_physical_source_range(dirty):
    table = read_table(dirty["triggers"], HEADER)
    row = table.rows[1]
    assert (row.line, row.end_line) == (3, 4)
    assert table.columns(row)["备注"] == "桥面潮湿\n班组复核接缝"
    assert table.rows[2].line == 5


# TRAP-04
def test_repeated_header_and_blank_do_not_inflate_raw_count(dirty):
    intake = accept(dirty["triggers"])
    assert (intake["raw"], intake["segments"], intake["blank"]) == (50, 2, 1)
    assert len(intake["accepted"]) + len(intake["issues"]) == 50


# TRAP-05
def test_extra_column_is_quarantined_at_source_line(dirty):
    issue = next(issue for issue in accept(dirty["triggers"])["issues"] if issue.code == "BAD_COLUMNS")
    assert (issue.pass_id, issue.source.line, issue.source.cells[-1]) == ("0012", 26, "多余一列")


# TRAP-06
def test_full_width_decimal_and_thousands_grouping(dirty):
    events = {item.id: item for item in accept(dirty["triggers"])["accepted"]}
    assert events["0007-1L"].raw_kg == Decimal("2400.005")
    assert events["0007-1R"].raw_kg == Decimal("2395")
    assert sum(events[key].raw_kg for key in ("0007-1L", "0007-1R")) == Decimal("4795.005")


# TRAP-07
def test_missing_sentinel_never_contributes_zero(dirty):
    intake = accept(dirty["triggers"])
    assert "0012-5L" not in {event.id for event in intake["accepted"]}
    issue = next(item for item in intake["issues"] if item.code == "MISSING_VALUE")
    assert (issue.source.line, issue.source.cells[4]) == (24, "N/A")


# TRAP-13
def test_out_of_order_sensor_row_is_retained_and_marked(dirty):
    intake = accept(dirty["triggers"])
    late = {event.id for event in intake["accepted"] if event.late}
    assert late == {"0007-1L", "0007-1Lb", "0007-3L", "0007-3R"}
    assert intake["late"] == 4


def test_unzoned_clock_is_a_row_error(dirty):
    issue = next(item for item in accept(dirty["triggers"])["issues"] if item.code == "BAD_TIME")
    assert (issue.source.line, issue.source.cells[3]) == (27, "2026-11-20T20:01:01.210")


# TRAP-18
def test_empty_blank_and_header_only_have_distinct_errors():
    bodies = [b"", b"\r\n  \n", (",".join(HEADER) + "\n\n").encode()]
    for body, code in zip(bodies, ("EMPTY_FILE", "BLANK_FILE", "HEADER_ONLY")):
        with pytest.raises(DomainError) as error:
            accept(Source("signals.csv", body))
        assert error.value.code == code


def test_unclosed_multiline_is_fatal_and_points_to_start(dirty):
    source = dirty["triggers"]
    with pytest.raises(DomainError) as error:
        accept(Source(source.name, source.content + b'"incomplete\n'))
    assert (error.value.code, error.value.file, error.value.line) == ("CSV_SYNTAX", source.name, 55)
