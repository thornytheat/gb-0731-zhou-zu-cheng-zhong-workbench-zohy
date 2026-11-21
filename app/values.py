import re
import unicodedata
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

from app.config import CENT
from app.errors import DomainError

MISSING = {"", "-", "n/a", "null", "未知"}
UNITS = {"kg": Decimal(1), "千克": Decimal(1), "斤": Decimal("0.5"), "t": Decimal(1000)}
NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]{1,6})?")
CLOCK = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})")


def token(value):
    cleaned = value.strip()
    if cleaned.casefold() in MISSING:
        raise DomainError("MISSING_VALUE")
    return cleaned


def decimal_value(value):
    cleaned = unicodedata.normalize("NFKC", token(value))
    if len(cleaned) > 22 or not NUMBER.fullmatch(cleaned):
        raise DomainError("BAD_VALUE")
    return Decimal(cleaned.replace(",", ""))


def in_range(value, low, high):
    if not low <= value <= high:
        raise DomainError("BAD_VALUE")
    return value


def mass(value, unit):
    multiplier = UNITS.get(token(unit).casefold())
    if multiplier is None:
        raise DomainError("BAD_UNIT")
    return in_range(decimal_value(value) * multiplier, Decimal("0.000001"), 150000)


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def instant(value):
    value = token(value)
    if not CLOCK.fullmatch(value):
        raise DomainError("BAD_TIME")
    try:
        parsed = datetime.fromisoformat(value)
        zone = value[-6:] if not value.endswith("Z") else "+00:00"
        if int(zone[1:3]) > 23 or int(zone[4:]) > 59:
            raise ValueError
        return parsed.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise DomainError("BAD_TIME") from exc


def delta_ms(later, earlier):
    delta = later - earlier
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
