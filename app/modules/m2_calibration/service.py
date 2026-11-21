from dataclasses import dataclass
from decimal import Decimal

from app.config import MAX_WHEEL_KG
from app.evidence import Issue
from app.modules.m1_intake.parse import Trigger
from app.modules.m2_calibration.certificates import certificates
from app.modules.m2_calibration.crossing import crossings
from app.values import rounded


@dataclass(frozen=True)
class Wheel:
    trigger: Trigger
    kg: Decimal
    cert: str
    cert_ref: str


def calibrate(events, sources):
    catalog = certificates(sources["certificates"])
    passes = crossings(sources["passes"])
    by_side = {side: [item for item in catalog if item.side == side] for side in ("L", "R")}
    wheels, issues = [], []
    for event in events:
        crossing = passes.get(event.pass_id)
        if crossing is None:
            issues.append(Issue("PASS_UNKNOWN", event.source, event.pass_id))
            continue
        if not crossing.start <= event.time < crossing.end:
            issues.append(Issue("OUTSIDE_PASS", event.source, event.pass_id, (crossing.source.ref,)))
            continue
        eligible = [item for item in by_side[event.side] if item.start <= event.time < item.end]
        if len(eligible) != 1:
            code = "CAL_OVERLAP" if eligible else "CAL_MISSING"
            issues.append(Issue(code, event.source, event.pass_id, tuple(item.source.ref for item in eligible)))
            continue
        chosen = eligible[0]
        kg = rounded(event.raw_kg * chosen.gain + chosen.bias_kg)
        if not 0 < kg <= MAX_WHEEL_KG:
            issues.append(Issue("WHEEL_RANGE", event.source, event.pass_id, (chosen.source.ref,)))
            continue
        wheels.append(Wheel(event, kg, chosen.id, chosen.source.ref))
    return {"wheels": wheels, "issues": issues, "certificates": catalog, "passes": passes}
