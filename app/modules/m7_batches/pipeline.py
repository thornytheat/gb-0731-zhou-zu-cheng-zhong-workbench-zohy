from app.evidence import wire
from app.manifest import clock
from app.modules.m1_intake.service import accept
from app.modules.m2_calibration.service import calibrate
from app.modules.m3_debounce.service import debounce
from app.modules.m4_axles.service import reconstruct
from app.modules.m5_balance.service import balance
from app.modules.m6_reconcile.service import reconcile
from app.reasons import REASONS


def run_pipeline(sources, until="reconcile", events=None):
    results = {}

    def log(level, code, message, time=None):
        if events is not None:
            events.append((clock(), level, code, message, time))

    intake = results["intake"] = accept(sources["triggers"])
    log("info", "INTAKE", f"{intake['file']} · {intake['raw']} 条 · {intake['encoding']}")
    if until == "intake":
        return wire(results)
    cal = results["calibration"] = calibrate(intake["accepted"], sources)
    log("info", "CALIBRATION", f"完成标定 {len(cal['wheels'])} 条")
    if until == "calibration":
        return wire(results)
    pulse = results["debounce"] = debounce(intake["accepted"], cal["wheels"])
    log("info", "DEBOUNCE", f"保留 {len(pulse['kept'])} 条 · 重复 {len(pulse['duplicates'])} 条")
    if until == "debounce":
        return wire(results)
    axles = results["axles"] = reconstruct(pulse["kept"], cal["passes"])
    for axis in axles["axes"]:
        left, right = (axis[side].trigger for side in ("left", "right"))
        log("ok", "AXLE", f"{axis['id']} · {left.id} / {right.id} · {axis['total_kg']} kg", axis["time"])
    if until == "axles":
        return wire(results)
    grades = results["balance"] = balance(axles["axes"])
    log("info", "BALANCE", f"偏载 {grades['counts']['warn']} 轴 · 严重 {grades['counts']['severe']} 轴")
    if until == "balance":
        return wire(results)
    isolated = sorted(
        intake["issues"] + cal["issues"] + pulse["issues"] + axles["issues"], key=lambda issue: issue.source.line,
    )
    duplicates = sorted(pulse["duplicates"], key=lambda issue: issue.source.line)
    results["quarantine"] = isolated
    ledger = results["reconcile"] = reconcile(
        sources["tickets"], cal["passes"], axles["axes"], isolated, duplicates, intake["raw"],
    )
    if not ledger["ledger"]["balanced"]:
        raise RuntimeError("触发流水未守恒")
    for issue in sorted(isolated + duplicates, key=lambda item: item.source.line):
        level = "info" if issue.code in {"REPLAY_ID", "BOUNCE"} else "warn"
        log(level, issue.code, f"{issue.source.ref} · {REASONS[issue.code]}")
    log("ok", "LEDGER", f"触发核平 · {ledger['ledger']['review']} 车次待复秤")
    return wire(results)
