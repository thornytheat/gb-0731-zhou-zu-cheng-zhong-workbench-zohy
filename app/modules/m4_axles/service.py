from collections import defaultdict

from app.modules.m4_axles.pair import match
from app.modules.m4_axles.spacing import classify_spacing


def reconstruct(kept, passes):
    by_pass = defaultdict(list)
    for wheel in kept:
        by_pass[wheel.trigger.pass_id].append(wheel)
    axes, issues = [], []
    for pass_id, crossing in passes.items():
        pairs, unmatched, unresolved = match(by_pass[pass_id], crossing)
        valid, spacing_issues = classify_spacing(pairs, unresolved, crossing)
        axes.extend(valid)
        issues.extend(unmatched + spacing_issues)
    return {"axes": axes, "issues": issues, "groups": len({axis["group"] for axis in axes})}
