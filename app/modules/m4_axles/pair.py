from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.config import PAIR_MS
from app.evidence import Issue
from app.modules.m2_calibration.service import Wheel
from app.values import delta_ms


@dataclass(frozen=True)
class Pair:
    left: Wheel
    right: Wheel
    time: datetime
    skew_ms: int


def match(wheels, crossing):
    lanes = {side: [wheel for wheel in wheels if wheel.trigger.side == side] for side in ("L", "R")}
    times = {
        side: [delta_ms(wheel.trigger.time, crossing.start) for wheel in lane]
        for side, lane in lanes.items()
    }
    neighbors = {}
    for side, other in (("L", "R"), ("R", "L")):
        for wheel, time in zip(lanes[side], times[side]):
            first = bisect_left(times[other], time - PAIR_MS)
            last = bisect_right(times[other], time + PAIR_MS)
            neighbors[wheel.trigger.id] = lanes[other][first:last]

    pairs, issues, unresolved = [], [], []
    for wheel in wheels:
        event = wheel.trigger
        candidates = neighbors[event.id]
        if len(candidates) == 1 and len(neighbors[candidates[0].trigger.id]) == 1:
            if event.side == "L":
                right = candidates[0]
                skew = delta_ms(right.trigger.time, event.time)
                pairs.append(Pair(wheel, right, event.time + timedelta(microseconds=skew * 500), skew))
        else:
            code = "PAIR_AMBIGUOUS" if candidates else "PAIR_MISSING"
            refs = [item.trigger.source.ref for item in candidates]
            for item in candidates:
                refs.extend(peer.trigger.source.ref for peer in neighbors[item.trigger.id] if peer != wheel)
            issues.append(Issue(code, event.source, crossing.id, tuple(dict.fromkeys(refs))))
            unresolved.append(event.time)
    return sorted(pairs, key=lambda pair: pair.time), issues, sorted(unresolved)
