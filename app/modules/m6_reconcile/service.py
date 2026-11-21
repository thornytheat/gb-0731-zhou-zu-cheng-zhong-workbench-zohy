from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from app.config import TICKET_GRACE_MIN, TICKET_TOLERANCE
from app.modules.m6_reconcile.tickets import choose, ticket_book


def reconcile(source, passes, axes, isolated, duplicates, raw_count):
    book, ticket_issues = ticket_book(source, passes)
    bad_tickets = defaultdict(list)
    for issue in ticket_issues:
        bad_tickets[issue.pass_id].append(issue.source.ref)
    by_pass = defaultdict(list)
    for axis in axes:
        by_pass[axis["pass_id"]].append(axis)
    review = defaultdict(list)
    for issue in isolated:
        review[issue.pass_id].append(issue.source.ref)

    results = []
    for pass_id, crossing in passes.items():
        items = by_pass[pass_id]
        wheel_kg = sum((axis["total_kg"] for axis in items), Decimal("0.00"))
        ticket, code, refs = choose(book[pass_id])
        if bad_tickets[pass_id]:
            ticket, code = None, "TICKET_INVALID"
            refs = tuple(bad_tickets[pass_id]) + refs
        if ticket is not None and ticket.plate != crossing.plate:
            ticket, code = None, "TICKET_PLATE"
        if ticket is not None and (
            ticket.time < crossing.start or ticket.time - crossing.end >= timedelta(minutes=TICKET_GRACE_MIN)
        ):
            ticket, code = None, "TICKET_TIME"
        difference = ticket.kg - wheel_kg if ticket else None
        codes = [] if code is None else [code]
        if review[pass_id] or not items:
            codes.append("WHEELS_INCOMPLETE")
        if difference is not None and abs(difference) > TICKET_TOLERANCE:
            codes.append("WEIGHT_DIFFERENCE")
        results.append({
            "pass_id": pass_id, "plate": crossing.plate, "pass_ref": crossing.source.ref,
            "ticket": ticket, "ticket_refs": refs, "axle_ids": [axis["id"] for axis in items],
            "wheel_refs": [axis[side].trigger.source.ref for axis in items for side in ("left", "right")],
            "review_refs": review[pass_id], "wheel_kg": wheel_kg, "difference_kg": difference,
            "status": "review" if codes else "matched", "codes": codes,
        })
    effective = 2 * len(axes)
    accounted = raw_count == effective + len(duplicates) + len(isolated)
    return {
        "rows": results, "ticket_issues": ticket_issues,
        "ledger": {
            "raw": raw_count, "effective": effective, "duplicates": len(duplicates),
            "isolated": len(isolated), "balanced": accounted,
            "wheel_kg": sum((row["wheel_kg"] for row in results), Decimal("0.00")),
            "matched": sum(row["status"] == "matched" for row in results),
            "review": sum(row["status"] == "review" for row in results),
            "isolation_counts": dict(sorted(Counter(issue.code for issue in isolated).items())),
        },
    }
