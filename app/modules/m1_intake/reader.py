import csv
from dataclasses import dataclass
from io import StringIO

from app.config import MAX_ROWS
from app.errors import DomainError
from app.evidence import SourceRow
from app.modules.m1_intake.decode import decode


@dataclass
class Table:
    rows: list[SourceRow]
    encoding: str
    blank: int
    segments: int
    index: dict[str, int]

    def columns(self, row):
        return {column: row.cells[index] for column, index in self.index.items()}

    def field(self, row, name):
        index = self.index[name]
        return row.cells[index].strip() if index < len(row.cells) else ""


def read_table(source, expected):
    text, encoding = decode(source)
    reader = csv.reader(StringIO(text, newline=""), strict=True)
    previous_end = 0
    blank = 0
    header = None
    segments = 0
    rows = []
    try:
        for cells in reader:
            line = previous_end + 1
            previous_end = reader.line_num
            if not any(cell.strip() for cell in cells):
                blank += 1
                continue
            names = tuple(cell.strip() for cell in cells)
            if header is None:
                if len(names) != len(expected) or set(names) != set(expected):
                    raise DomainError("BAD_HEADER", file=source.name, line=line)
                header = names
                segments = 1
            elif names == header:
                segments += 1
            else:
                if len(rows) == MAX_ROWS:
                    raise DomainError("SOURCE_TOO_LARGE", file=source.name, line=line)
                rows.append(SourceRow(source.name, line, reader.line_num, tuple(cells)))
    except csv.Error as exc:
        raise DomainError("CSV_SYNTAX", file=source.name, line=previous_end + 1) from exc
    if header is None:
        raise DomainError("BLANK_FILE", file=source.name)
    if not rows:
        raise DomainError("HEADER_ONLY", file=source.name, line=1)
    return Table(rows, encoding, blank, segments, {name: i for i, name in enumerate(header)})
