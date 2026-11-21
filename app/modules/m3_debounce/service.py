from app.config import DEBOUNCE_MS
from app.evidence import Issue
from app.modules.m3_debounce.identity import identities
from app.values import delta_ms


def debounce(events, wheels):
    candidates, duplicates, issues = identities(events, wheels)
    kept = []
    anchors = {}
    for wheel in sorted(candidates, key=lambda item: (item.trigger.time, item.trigger.source.line)):
        event = wheel.trigger
        channel = (event.pass_id, event.side)
        anchor = anchors.get(channel)
        if anchor is not None and delta_ms(event.time, anchor.time) <= DEBOUNCE_MS:
            duplicates.append(Issue("BOUNCE", event.source, event.pass_id, (anchor.source.ref,), anchor.id))
        else:
            anchors[channel] = event
            kept.append(wheel)
    return {"kept": kept, "duplicates": duplicates, "issues": issues}
