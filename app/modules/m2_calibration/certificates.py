from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.errors import DomainError
from app.evidence import SourceRow
from app.modules.m1_intake.reader import read_table
from app.values import decimal_value, in_range, instant, token

HEADER = ("证书", "轮道", "生效", "失效", "增益", "偏置千克")


@dataclass(frozen=True)
class Certificate:
    id: str
    side: str
    start: datetime
    end: datetime
    gain: Decimal
    bias_kg: Decimal
    source: SourceRow


def certificates(source):
    table = read_table(source, HEADER)
    catalog = {}
    for row in table.rows:
        try:
            if len(row.cells) != len(HEADER):
                raise DomainError("BAD_COLUMNS")
            data = table.columns(row)
            cert_id, side = token(data["证书"]), token(data["轮道"]).upper()
            start, end = instant(data["生效"]), instant(data["失效"])
            if cert_id in catalog or side not in {"L", "R"} or start >= end:
                raise DomainError("BAD_VALUE")
            gain = in_range(decimal_value(data["增益"]), Decimal("0.1"), 10)
            bias = in_range(decimal_value(data["偏置千克"]), -500, 500)
            catalog[cert_id] = Certificate(cert_id, side, start, end, gain, bias, row)
        except DomainError as exc:
            raise DomainError("AUTHORITY_INVALID", file=source.name, line=row.line, detail=exc.code) from exc
    return list(catalog.values())
