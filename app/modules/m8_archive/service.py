"""M8 冷存归档服务。

状态机：ONLINE（仅在线库）→ FROZEN（冷包已封边、在线保留）
        → PURGED（在线已清理、仅冷包可回读）→ RESTORED（冷包内容已回灌并核对）

不可变的安全边界：
1. 抽查保留单生效中的批次，封冻与清理一律拒绝；
2. 含待复秤车次或流水未核平的批次不具备转冷资格；
3. 清理前必须重新验封（Merkle 根 + 可选 HMAC），失败则在线记录原样保留；
4. 恢复按内容寻址 run_id 回灌，重复恢复只追加事件，绝不生成第二个批次；
5. 恢复后逐车次比对结论指纹，任一不符即 RESTORE_MISMATCH 且不写在线库。
"""

import json
from contextlib import closing
from pathlib import Path

from app.config import RULE_VERSION
from app.errors import DomainError
from app.manifest import canonical, clock, digest
from app.modules.m8_archive import cold
from app.modules.m8_archive.archive_store import add_event
from app.modules.m8_archive.slicing import build_train_slices, slice_file, summarize_slices
from app.store import add_run

MANIFEST_MEMBER = "manifest.json"
RESULTS_MEMBER = "results.json"
SUMMARY_MEMBER = "train-summary.json"


# ---------- 资格与容量 ----------

def eligibility(store, archive, run_id: str) -> dict:
    """判定一个在线批次是否允许进入冷存流程，并给出阻塞原因。"""
    manifest, results = store.read(run_id)
    reasons = []
    if not results["reconcile"]["ledger"]["balanced"]:
        reasons.append("ARCHIVE_UNBALANCED")
    if results["reconcile"]["ledger"]["review"] > 0:
        reasons.append("ARCHIVE_REVIEW_OPEN")
    if archive.active_holds(run_id):
        reasons.append("ARCHIVE_HELD")
    record = archive.get(run_id)
    state = record["state"] if record else "ONLINE"
    return {
        "run_id": run_id,
        "sample": manifest["sample"],
        "state": state,
        "eligible": not reasons,
        "blocking_codes": reasons,
        "train_count": len(results["reconcile"]["rows"]),
        "review_count": results["reconcile"]["ledger"]["review"],
        "online_bytes": _online_bytes(store, run_id),
        "created_at": manifest["created_at"],
        "holds": [dict(row) for row in archive.active_holds(run_id)],
    }


def plan(store, archive, need_bytes: int) -> dict:
    """容量压力下划定先转冷的范围。

    排序：无阻塞优先；同资格下先封冻时间成本低（旧批次优先，created_at 升序），
    大批次优先以尽快腾出空间。只推荐完整批次，绝不拆散车次。
    """
    candidates, blocked = [], []
    for row in store.history():
        run_id = row["run_id"]
        item = eligibility(store, archive, run_id)
        record = archive.get(run_id)
        item["reclaim_bytes"] = item["online_bytes"] if record is None or record["state"] != "PURGED" else 0
        if item["eligible"] and item["reclaim_bytes"]:
            candidates.append(item)
        else:
            blocked.append(item)
    candidates.sort(key=lambda item: (item["created_at"], -item["reclaim_bytes"], item["run_id"]))

    chosen, accumulated = [], 0
    for item in candidates:
        if accumulated >= need_bytes:
            break
        chosen.append(item)
        accumulated += item["reclaim_bytes"]
    return {
        "need_bytes": need_bytes,
        "satisfiable": accumulated >= need_bytes,
        "planned_reclaim_bytes": accumulated,
        "planned": chosen,
        "blocked": sorted(blocked, key=lambda item: item["run_id"]),
    }


def _online_bytes(store, run_id: str) -> int:
    with closing(store.connect()) as db:
        row = db.execute(
            "SELECT length(manifest) + length(results) AS bytes FROM runs WHERE id = ?", (run_id,),
        ).fetchone()
    return int(row["bytes"]) if row else 0


# ---------- 封冻 ----------

def freeze(store, archive, cold_root: Path, run_id: str, *, hmac_key: bytes | None = None) -> tuple[dict, bool]:
    """把在线批次固化为验封冷包。重复执行是幂等的，返回 (台账行, 是否复用已有冷包)。"""
    manifest, results = store.read(run_id)
    verdict = eligibility(store, archive, run_id)
    if not verdict["eligible"]:
        raise DomainError(verdict["blocking_codes"][0], 409, detail=verdict)

    slices = build_train_slices(manifest, results)
    summary = summarize_slices(slices)
    payload = {
        MANIFEST_MEMBER: canonical(manifest).encode("utf-8"),
        RESULTS_MEMBER: canonical(results).encode("utf-8"),
        SUMMARY_MEMBER: canonical(summary).encode("utf-8"),
    }
    for pass_id, train in sorted(slices.items()):
        payload[slice_file(pass_id)] = canonical(train).encode("utf-8")

    now = clock()
    seal = cold.write_package(cold_root, run_id, payload, rule_version=RULE_VERSION, hmac_key=hmac_key)
    package_sha = digest(cold.package_zip(cold_root, run_id).read_bytes())
    online_bytes = _online_bytes(store, run_id)

    now = clock()
    seal = cold.write_package(cold_root, run_id, payload, rule_version=RULE_VERSION, hmac_key=hmac_key)
    package_sha = digest(cold.package_zip(cold_root, run_id).read_bytes())
    online_bytes = _online_bytes(store, run_id)

    with archive.transaction() as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO archive_ledger (run_id,sample,state,created_at,updated_at,frozen_at,"
            "result_sha256,merkle_root,package_sha256,hmac_algorithm,train_count,review_count,"
            "online_bytes,manifest,train_summary) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, manifest["sample"], "FROZEN", now, now, now,
             manifest["result_sha256"], seal["merkle_root"], package_sha, seal["hmac_algorithm"],
             len(slices), summary_open_count(summary), online_bytes,
             canonical(manifest), canonical(summary)),
        )
        inserted = cursor.rowcount == 1
        if inserted:
            add_event(db, run_id, now, "ok", "FROZEN",
                      f"冷包封边 · {len(slices)} 车次 · Merkle {seal['merkle_root'][:12]}",
                      canonical({"merkle_root": seal["merkle_root"], "entries": len(seal["entries"])}))
        else:
            add_event(db, run_id, now, "info", "FREEZE_REUSED", "冷包已封边且验封一致，沿用原包", None)
    return dict(archive.require(run_id)), not inserted


def summary_open_count(summary: dict) -> int:
    return sum(1 for item in summary.values() if item["status"] == "review")


# ---------- 验封后清理 ----------

def purge(store, archive, cold_root: Path, run_id: str, *, hmac_key: bytes | None = None) -> dict:
    """先验封、后删在线记录；冷包不完整时在线库一行不丢。"""
    record = archive.require(run_id)
    now = clock()
    if archive.active_holds(run_id):
        raise DomainError("ARCHIVE_HELD", 409)
    if record["state"] == "PURGED":
        with archive.transaction() as db:
            add_event(db, run_id, now, "info", "PURGE_REUSED", "在线库此前已清理，重复清理无操作", None)
        return dict(record)
    if record["state"] not in ("FROZEN", "RESTORED"):
        raise DomainError("ARCHIVE_STATE", 409, detail={"state": record["state"]})

    # 删库前的强制闸门：任何一项不过都抛异常，在线记录保持原样。
    seal = cold.verify_package(cold_root, run_id, hmac_key=hmac_key)
    _check_seal_against_ledger(record, seal)

    reclaimed = _online_bytes(store, run_id)
    with store.transaction() as db:
        removed = db.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
        if removed != 1:
            raise DomainError("ONLINE_TOMBSTONE", 409)
        db.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
        db.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    with archive.transaction() as db:
        db.execute(
            "UPDATE archive_ledger SET state='PURGED', updated_at=?, purged_at=?, reclaim_bytes=? "
            "WHERE run_id=?",
            (now, now, reclaimed, run_id),
        )
        add_event(db, run_id, now, "ok", "PURGED",
                  f"验封通过后清理在线库 · 释放 {reclaimed} 字节", canonical({"reclaim_bytes": reclaimed}))
    return dict(archive.require(run_id))


def _check_seal_against_ledger(record, seal: dict):
    if seal["merkle_root"] != record["merkle_root"]:
        raise DomainError("PACKAGE_TAMPERED", 409, detail={"run_id": record["run_id"]})
    if seal["rule_version"] != RULE_VERSION:
        raise DomainError("PACKAGE_CORRUPT", 409, detail={"rule_version": seal["rule_version"]})


# ---------- 恢复（幂等 + 逐车次核对） ----------

def restore(store, archive, cold_root: Path, run_id: str, *,
            hmac_key: bytes | None = None, dry_run: bool = False) -> dict:
    """从冷包回灌在线库；恢复后的车次结论必须与封条逐车一致。"""
    record = archive.require(run_id)
    # PURGED：回灌；RESTORED：在线已有同 run_id 批次，走幂等复用；FROZEN 不属于恢复场景。
    if not dry_run and record["state"] not in ("PURGED", "RESTORED"):
        raise DomainError("ARCHIVE_STATE", 409, detail={"state": record["state"]})

    payload = cold.open_payload(cold_root, run_id, hmac_key=hmac_key)
    manifest = json.loads(payload[MANIFEST_MEMBER])
    results = json.loads(payload[RESULTS_MEMBER])
    summary = json.loads(payload[SUMMARY_MEMBER])

    _verify_restoration(record, manifest, results, summary)
    report = _restore_report(record, manifest, results, summary)
    if dry_run:
        report["dry_run"] = True
        return report

    now = clock()
    with store.transaction() as db:
        existing = db.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if existing is None:
            if record["state"] != "PURGED":
                raise DomainError("ARCHIVE_STATE", 409, detail={"state": record["state"]})
            add_run(db, manifest, results)
            action = "RESTORED"
            message = f"冷包回灌在线库 · {report['train_count']} 车次结论逐车核对一致"
        else:
            action = "RESTORE_REUSED"
            message = "在线批次已存在且 run_id 一致，重复恢复未生成新批次"
    with archive.transaction() as db:
        if action == "RESTORED":
            db.execute(
                "UPDATE archive_ledger SET state='RESTORED', updated_at=?, restored_at=?, "
                "restore_count=restore_count+1 WHERE run_id=?",
                (now, now, run_id),
            )
        add_event(db, run_id, now, "ok" if action == "RESTORED" else "info", action, message,
                  canonical({"trains": report["train_count"], "matched": report["matched"]}))
    report["action"] = action
    return report


def _verify_restoration(record, manifest, results, summary):
    if manifest["run_id"] != record["run_id"]:
        raise DomainError("RESTORE_MISMATCH", 409, detail={"field": "run_id"})
    if digest(canonical(results).encode("utf-8")) != record["result_sha256"]:
        raise DomainError("RESTORE_MISMATCH", 409, detail={"field": "result_sha256"})
    restored_summary = summarize_slices(build_train_slices(manifest, results))
    if canonical(restored_summary) != canonical(summary):
        raise DomainError("RESTORE_MISMATCH", 409, detail={"field": "train_summary"})
    if canonical(summary) != canonical(json.loads(record["train_summary"])):
        raise DomainError("RESTORE_MISMATCH", 409, detail={"field": "ledger_summary"})


def _restore_report(record, manifest, results, summary) -> dict:
    rows = {row["pass_id"]: row for row in results["reconcile"]["rows"]}
    trains = []
    for pass_id, item in sorted(summary.items()):
        row = rows[pass_id]
        trains.append({
            "pass_id": pass_id,
            "plate": row["plate"],
            "status": item["status"],
            "codes": list(item["codes"]),
            "wheel_kg": item["wheel_kg"],
            "difference_kg": item["difference_kg"],
            "slice_sha256": item["slice_sha256"],
            "verified": True,
        })
    return {
        "run_id": record["run_id"],
        "sample": manifest["sample"],
        "result_sha256": record["result_sha256"],
        "merkle_root": record["merkle_root"],
        "train_count": len(trains),
        "matched": sum(1 for train in trains if train["verified"]),
        "review_count": sum(1 for train in trains if train["status"] == "review"),
        "trains": trains,
        "dry_run": False,
    }


# ---------- 抽查回读（不回灌、不动状态） ----------

def readback(store, archive, cold_root: Path, run_id: str, pass_id: str | None = None, *,
             hmac_key: bytes | None = None) -> dict:
    """审计抽查随时回读：在线优先；已清理则从验封冷包取整车切片。"""
    record = archive.get(run_id)
    online = _online_row(store, run_id)
    if online is not None:
        manifest, results = online
        slices = build_train_slices(manifest, results)
        source = "ONLINE"
    else:
        if record is None or not cold.is_sealed(cold_root, run_id):
            raise DomainError("PACKAGE_MISSING", 409)
        payload = cold.open_payload(cold_root, run_id, hmac_key=hmac_key)
        manifest = json.loads(payload[MANIFEST_MEMBER])
        if pass_id is not None:
            member = slice_file(pass_id)
            if member not in payload:
                raise DomainError("RUN_UNKNOWN", 404, detail={"pass_id": pass_id})
            return {"run_id": run_id, "source": "COLD", "state": record["state"], "train": json.loads(payload[member])}
        results = json.loads(payload[RESULTS_MEMBER])
        slices = build_train_slices(manifest, results)
        source = "COLD"

    if pass_id is not None:
        if pass_id not in slices:
            raise DomainError("RUN_UNKNOWN", 404, detail={"pass_id": pass_id})
        return {"run_id": run_id, "source": source,
                "state": record["state"] if record else "ONLINE", "train": slices[pass_id]}
    return {
        "run_id": run_id,
        "source": source,
        "state": record["state"] if record else "ONLINE",
        "manifest_sample": manifest["sample"],
        "trains": sorted(slices),
        "summary": summarize_slices(slices),
    }


def _online_row(store, run_id: str):
    with closing(store.connect()) as db:
        row = db.execute("SELECT manifest, results FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return json.loads(row["manifest"]), json.loads(row["results"])


# ---------- 抽查保留单 ----------

def place_hold(archive, run_id: str, subject: str, reason: str, *, expires_at: str | None = None) -> dict:
    now = clock()
    hold_id = digest(canonical({"run_id": run_id, "subject": subject}).encode("utf-8"))[:16]
    with archive.transaction() as db:
        try:
            db.execute(
                "INSERT INTO audit_holds (hold_id,run_id,subject,reason,created_at,expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (hold_id, run_id, subject, reason, now, expires_at),
            )
        except Exception as exc:
            if getattr(exc, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE":
                raise DomainError("HOLD_EXISTS", 409, detail={"subject": subject}) from exc
            raise
        add_event(db, run_id, now, "warn", "HOLD_PLACED", f"抽查保留 · {subject} · {reason}", None)
    return dict(archive.holds(run_id)[-1])


def release_hold(archive, hold_id: str) -> dict:
    now = clock()
    with archive.transaction() as db:
        row = db.execute("SELECT * FROM audit_holds WHERE hold_id = ?", (hold_id,)).fetchone()
        if row is None:
            raise DomainError("HOLD_UNKNOWN", 404)
        if row["released_at"] is not None:
            return dict(row)
        db.execute("UPDATE audit_holds SET released_at=? WHERE hold_id=?", (now, hold_id))
        add_event(db, row["run_id"], now, "info", "HOLD_RELEASED", f"保留单解除 · {row['subject']}", None)
    return _reload_hold(archive, hold_id)


def _reload_hold(archive, hold_id: str) -> dict:
    with closing(archive.connect()) as db:
        return dict(db.execute("SELECT * FROM audit_holds WHERE hold_id=?", (hold_id,)).fetchone())
