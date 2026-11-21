from collections import Counter

from app.modules.m5_balance.thresholds import grade


def balance(axes):
    results = []
    counts = Counter({"pass": 0, "warn": 0, "severe": 0})
    for axis in axes:
        left, right = axis["left"], axis["right"]
        level, percent = grade(left.kg, right.kg)
        counts[level] += 1
        results.append({
            "id": axis["id"], "pass_id": axis["pass_id"], "level": level, "percent": percent,
            "left_kg": left.kg, "right_kg": right.kg,
            "heavy": "L" if left.kg > right.kg else "R" if right.kg > left.kg else None,
            "left_ref": left.trigger.source.ref, "right_ref": right.trigger.source.ref,
        })
    return {"rows": results, "counts": dict(counts)}
