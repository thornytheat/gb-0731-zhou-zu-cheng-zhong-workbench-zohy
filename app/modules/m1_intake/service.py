from app.errors import DomainError
from app.evidence import Issue
from app.modules.m1_intake.parse import HEADER, parse_trigger
from app.modules.m1_intake.reader import read_table


def accept(source):
    table = read_table(source, HEADER)
    accepted, issues = [], []
    highwater = {}
    for row in table.rows:
        try:
            if len(row.cells) != len(HEADER):
                raise DomainError("BAD_COLUMNS")
            accepted.append(parse_trigger(row, table.columns(row), highwater))
        except DomainError as exc:
            issues.append(Issue(exc.code, row, table.field(row, "车次")))
    return {
        "file": source.name,
        "encoding": table.encoding,
        "segments": table.segments,
        "blank": table.blank,
        "raw": len(table.rows),
        "late": sum(event.late for event in accepted),
        "accepted": accepted,
        "issues": issues,
    }
