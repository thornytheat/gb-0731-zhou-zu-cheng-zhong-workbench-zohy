from bisect import bisect_right
from datetime import timedelta
from decimal import Decimal

from app.config import MAX_SPACING, MIN_SPACING, TANDEM_SPACING
from app.evidence import Issue


def classify_spacing(pairs, unresolved, crossing):
    rejected = {}
    distances = {}
    for index, (previous, current) in enumerate(zip(pairs, pairs[1:]), 1):
        between = bisect_right(unresolved, previous.time)
        if between < len(unresolved) and unresolved[between] < current.time:
            continue
        elapsed = (current.time - previous.time) // timedelta(microseconds=1)
        distance = crossing.speed_mps * Decimal(elapsed) / 1_000_000
        distances[index] = distance
        if not MIN_SPACING <= distance <= MAX_SPACING:
            code = "SPACING_SHORT" if distance < MIN_SPACING else "SPACING_LONG"
            rejected.setdefault(index - 1, (code, current))
            rejected.setdefault(index, (code, previous))

    axes, issues = [], []
    group, serial = 0, 0
    prior = -2
    for index, pair in enumerate(pairs):
        if index in rejected:
            code, other = rejected[index]
            refs = (other.left.trigger.source.ref, other.right.trigger.source.ref)
            for event in (pair.left.trigger, pair.right.trigger):
                issues.append(Issue(code, event.source, crossing.id, refs))
            continue
        gap = distances.get(index) if prior == index - 1 else None
        if gap is None or gap > TANDEM_SPACING:
            group += 1
        prior = index
        serial += 1
        axes.append({
            "id": f"{crossing.id}/A{serial:02}",
            "pass_id": crossing.id,
            "group": f"{crossing.id}/G{group:02}",
            "time": pair.time.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "skew_ms": pair.skew_ms,
            "gap_m": gap,
            "left": pair.left,
            "right": pair.right,
            "total_kg": pair.left.kg + pair.right.kg,
        })
    return axes, issues
