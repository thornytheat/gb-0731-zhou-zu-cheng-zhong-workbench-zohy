from dataclasses import dataclass
from pathlib import Path

from app.config import MAX_FILE_BYTES
from app.errors import DomainError

SAMPLES = {"dirty": "东门晚班 · 原始采样", "clean": "南门校验 · 对照采样"}


@dataclass(frozen=True)
class Source:
    name: str
    content: bytes


def sample_files(sample):
    if sample not in SAMPLES:
        raise DomainError("SAMPLE_UNKNOWN", 404)
    return {
        "triggers": f"{sample}-triggers.csv",
        "tickets": f"{sample}-tickets.csv",
        "certificates": "certificates.csv",
        "passes": "passes.csv",
    }


def read_sources(directory: Path, sample, roles=None):
    result = {}
    for role, name in sample_files(sample).items():
        if roles is not None and role not in roles:
            continue
        try:
            with (directory / name).open("rb") as handle:
                content = handle.read(MAX_FILE_BYTES + 1)
        except OSError as exc:
            raise DomainError("SOURCE_MISSING", 422, file=name) from exc
        if len(content) > MAX_FILE_BYTES:
            raise DomainError("SOURCE_TOO_LARGE", file=name)
        result[role] = Source(name, content)
    return result
