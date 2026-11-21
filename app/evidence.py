from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal

from app.reasons import REASONS


@dataclass(frozen=True)
class SourceRow:
    file: str
    line: int
    end_line: int
    cells: tuple[str, ...]

    @property
    def ref(self):
        lines = str(self.line) if self.line == self.end_line else f"{self.line}–{self.end_line}"
        return f"{self.file}:{lines}"


@dataclass(frozen=True)
class Issue:
    code: str
    source: SourceRow
    pass_id: str = ""
    related: tuple[str, ...] = ()
    kept_id: str = ""


def wire(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(value, SourceRow):
        return {**{field.name: wire(getattr(value, field.name)) for field in fields(value)}, "ref": value.ref}
    if is_dataclass(value):
        result = {field.name: wire(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Issue):
            result["message"] = REASONS[value.code]
        return result
    if isinstance(value, dict):
        return {key: wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(item) for item in value]
    return value
