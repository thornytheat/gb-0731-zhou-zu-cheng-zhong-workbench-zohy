from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.errors import DomainError
from app.evidence import SourceRow
from app.modules.m1_intake.reader import read_table
from app.values import decimal_value, in_range, instant, token

HEADER = ("车次", "车牌", "入口", "出口", "速度米每秒")


@dataclass(frozen=True)
class Crossing:
    id: str
    plate: str
    start: datetime
    end: datetime
    speed_mps: Decimal
    source: SourceRow


def crossings(source):
    table = read_table(source, HEADER)
    catalog = {}
    for row in table.rows:
        try:
            if len(row.cells) != len(HEADER):
                raise DomainError("BAD_COLUMNS")
            data = table.columns(row)
            pass_id, plate = token(data["车次"]), token(data["车牌"])
            start, end = instant(data["入口"]), instant(data["出口"])
            if pass_id in catalog or start >= end:
                raise DomainError("BAD_VALUE")
            speed = in_range(decimal_value(data["速度米每秒"]), Decimal("0.5"), 40)
            catalog[pass_id] = Crossing(pass_id, plate, start, end, speed, row)
        except DomainError as exc:
            raise DomainError("AUTHORITY_INVALID", file=source.name, line=row.line, detail=exc.code) from exc
    return catalog
