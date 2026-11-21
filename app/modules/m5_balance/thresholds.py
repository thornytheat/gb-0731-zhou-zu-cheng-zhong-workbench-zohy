from app.config import NOTICE_RATIO, SEVERE_RATIO
from app.values import rounded


def grade(left, right):
    total, difference = left + right, abs(left - right)
    if difference >= total * SEVERE_RATIO:
        level = "severe"
    elif difference >= total * NOTICE_RATIO:
        level = "warn"
    else:
        level = "pass"
    return level, rounded(difference * 100 / total)
