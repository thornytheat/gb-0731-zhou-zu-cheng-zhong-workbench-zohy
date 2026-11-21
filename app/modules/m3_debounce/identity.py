from collections import defaultdict

from app.evidence import Issue


def signature(event):
    return event.pass_id, event.side, event.time, event.raw_kg


def identities(events, wheels):
    versions = defaultdict(dict)
    for event in events:
        versions[event.id].setdefault(signature(event), event.source.ref)
    conflicts = {event_id: tuple(rows.items())[:2] for event_id, rows in versions.items() if len(rows) > 1}

    survivors, duplicates, issues = [], [], []
    seen = {}
    for wheel in wheels:
        event = wheel.trigger
        if event.id in conflicts:
            other = next(ref for values, ref in conflicts[event.id] if values != signature(event))
            issues.append(Issue("ID_CONFLICT", event.source, event.pass_id, (other,)))
        elif event.id in seen:
            duplicates.append(Issue("REPLAY_ID", event.source, event.pass_id, (seen[event.id],), event.id))
        else:
            survivors.append(wheel)
            seen[event.id] = event.source.ref
    return survivors, duplicates, issues
