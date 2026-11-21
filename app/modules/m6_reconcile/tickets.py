from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.errors import DomainError
from app.evidence import Issue, SourceRow
from app.modules.m1_intake.reader import read_table
from app.values import instant, mass, rounded, token

HEADER = ("磅单号", "车次", "版次", "车牌", "签发时间", "总重", "单位")


@dataclass(frozen=True)
class Ticket:
    id: str
    pass_id: str
    revision: int
    plate: str
    time: datetime
    kg: Decimal
    source: SourceRow


def ticket_book(source, passes):
    table = read_table(source, HEADER)
    book = defaultdict(list)
    issues = []
    for row in table.rows:
        pass_id = table.field(row, "车次")
        try:
            if len(row.cells) != len(HEADER):
                raise DomainError("BAD_COLUMNS")
            if pass_id not in passes:
                raise DomainError("PASS_UNKNOWN")
            data = table.columns(row)
            version = token(data["版次"])
            if not version.isascii() or not version.isdigit() or len(version) > 6 or int(version) == 0:
                raise DomainError("BAD_VALUE")
            kg = rounded(mass(data["总重"], data["单位"]))
            if kg <= 0:
                raise DomainError("BAD_VALUE")
            book[pass_id].append(Ticket(
                token(data["磅单号"]), pass_id, int(version), token(data["车牌"]),
                instant(data["签发时间"]), kg, row,
            ))
        except DomainError as exc:
            issues.append(Issue(exc.code, row, pass_id))
    return book, issues


def choose(tickets):
    if not tickets:
        return None, "TICKET_MISSING", ()
    current = max(ticket.revision for ticket in tickets)
    candidates = [ticket for ticket in tickets if ticket.revision == current]
    refs = tuple(ticket.source.ref for ticket in candidates)
    signatures = {(ticket.id, ticket.plate, ticket.time, ticket.kg) for ticket in candidates}
    if len(signatures) > 1:
        return None, "TICKET_CONFLICT", refs
    return candidates[0], None, refs
