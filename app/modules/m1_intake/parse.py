from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.errors import DomainError
from app.evidence import SourceRow
from app.values import instant, mass, token

HEADER = ("记录号", "车次", "轮道", "采样时间", "载荷", "单位", "质态", "备注")


@dataclass(frozen=True)
class Trigger:
    id: str
    pass_id: str
    side: str
    time: datetime
    raw_kg: Decimal
    source: SourceRow
    late: bool


def parse_trigger(row, data, highwater):
    record_id, pass_id = token(data["记录号"]), token(data["车次"])
    side = token(data["轮道"]).upper()
    if side not in {"L", "R"}:
        raise DomainError("BAD_VALUE")
    time = instant(data["采样时间"])
    weight = mass(data["载荷"], data["单位"])
    if token(data["质态"]).upper() != "OK":
        raise DomainError("SENSOR_UNCERTAIN")
    channel = (pass_id, side)
    watermark = highwater.get(channel, time)
    highwater[channel] = max(watermark, time)
    return Trigger(record_id, pass_id, side, time, weight, row, time < watermark)
