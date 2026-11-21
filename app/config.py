import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULE_VERSION = "axle-1.0.0"
MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 4000
CENT = Decimal("0.01")
MAX_WHEEL_KG = Decimal("25000")
DEBOUNCE_MS = 12
PAIR_MS = 35
MIN_SPACING = Decimal("0.55")
TANDEM_SPACING = Decimal("1.80")
MAX_SPACING = Decimal("12.00")
NOTICE_RATIO = Decimal("0.10")
SEVERE_RATIO = Decimal("0.20")
TICKET_TOLERANCE = Decimal("50.00")
TICKET_GRACE_MIN = 15

RULE_PARAMETERS = {
    "debounce_ms": DEBOUNCE_MS,
    "pair_ms": PAIR_MS,
    "min_spacing_m": str(MIN_SPACING),
    "tandem_spacing_m": str(TANDEM_SPACING),
    "max_spacing_m": str(MAX_SPACING),
    "max_wheel_kg": str(MAX_WHEEL_KG),
    "weight_resolution_kg": str(CENT),
    "notice_ratio": str(NOTICE_RATIO),
    "severe_ratio": str(SEVERE_RATIO),
    "ticket_tolerance_kg": str(TICKET_TOLERANCE),
    "ticket_grace_min": TICKET_GRACE_MIN,
}


@dataclass(frozen=True)
class Settings:
    source_dir: Path
    db_file: Path

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.getenv("WEIGH_SAMPLE_DIR", ROOT / "sample_data")),
            Path(os.getenv("WEIGH_DB", ROOT / "var/weigh.sqlite3")),
        )
