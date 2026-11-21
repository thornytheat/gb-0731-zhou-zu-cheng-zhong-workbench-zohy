"""M8 冷存归档工作台测试。"""

import json
import shutil
from contextlib import closing

import pytest

from app.config import ROOT
from app.errors import DomainError
from app.manifest import canonical, digest
from app.modules.m7_batches.pipeline import run_pipeline
from app.modules.m7_batches.service import commit_sample
from app.modules.m8_archive import cold, service
from app.modules.m8_archive.archive_store import ArchiveStore
from app.modules.m8_archive.slicing import build_train_slices, summarize_slices
from app.sources import read_sources
from app.store import Store, add_run


@pytest.fixture
def stores(settings):
    shutil.copytree(ROOT / "sample_data", settings.source_dir)
    store, archive = Store(settings.db_file), ArchiveStore(settings.archive_db_file)
    store.initialize()
    archive.initialize()
    return store, archive


def commit(stores, settings, sample="clean"):
    store, _ = stores
    manifest, _ = commit_sample(store, settings.source_dir, sample)
    return manifest["run_id"]


@pytest.fixture
def clean_run(stores, settings):
    return commit(stores, settings, "clean")


@pytest.fixture
def dirty_run(stores, settings):
    return commit(stores, settings, "dirty")


# ---------- 资格与规划 ----------

def test_clean_balanced_batch_is_eligible_but_review_batch_is_blocked(stores, clean_run, dirty_run):
    store, archive = stores
    clean_ok = service.eligibility(store, archive, clean_run)
    dirty_verdict = service.eligibility(store, archive, dirty_run)
    assert clean_ok["eligible"] is True
    assert clean_ok["blocking_codes"] == []
    assert dirty_verdict["eligible"] is False
    assert "ARCHIVE_REVIEW_OPEN" in dirty_verdict["blocking_codes"]
    assert dirty_verdict["review_count"] > 0


def test_hold_blocks_freeze_and_purge(stores, settings, clean_run):
    store, archive = stores
    service.place_hold(archive, clean_run, "审计抽查-01", "监管要求随时回读")
    verdict = service.eligibility(store, archive, clean_run)
    assert verdict["blocking_codes"] == ["ARCHIVE_HELD"]
    with pytest.raises(DomainError) as exc:
        service.freeze(store, archive, settings.cold_root, clean_run)
    assert exc.value.code == "ARCHIVE_HELD"
    service.release_hold(archive, archive.holds(clean_run)[0]["hold_id"])
    record, reused = service.freeze(store, archive, settings.cold_root, clean_run)
    service.place_hold(archive, clean_run, "审计抽查-02", "二次抽查")
    with pytest.raises(DomainError) as exc:
        service.purge(store, archive, settings.cold_root, clean_run)
    assert exc.value.code == "ARCHIVE_HELD"


def test_duplicate_hold_subject_is_rejected(stores, clean_run):
    _, archive = stores
    service.place_hold(archive, clean_run, "同一主题", "原因一")
    with pytest.raises(DomainError) as exc:
        service.place_hold(archive, clean_run, "同一主题", "原因二")
    assert exc.value.code == "HOLD_EXISTS"


def test_plan_only_picks_whole_eligible_batches_and_reports_blocked(stores, settings, clean_run, dirty_run):
    store, archive = stores
    plan = service.plan(store, archive, 1)
    assert [item["run_id"] for item in plan["planned"]] == [clean_run]
    blocked = {item["run_id"]: item["blocking_codes"] for item in plan["blocked"]}
    assert blocked[dirty_run] == ["ARCHIVE_REVIEW_OPEN"]
    assert all(item["reclaim_bytes"] > 0 for item in plan["planned"])
    # 已清理批次不再计入可回收容量
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    plan_after = service.plan(store, archive, 1)
    assert all(item["run_id"] != clean_run for item in plan_after["planned"])


# ---------- 封冻与验封 ----------

def test_freeze_is_idempotent_and_keeps_online_records(stores, settings, clean_run):
    store, archive = stores
    first, reused_first = service.freeze(store, archive, settings.cold_root, clean_run)
    second, reused_second = service.freeze(store, archive, settings.cold_root, clean_run)
    assert (reused_first, reused_second) == (False, True)
    assert first == second
    assert first["state"] == "FROZEN"
    # 封冻不释放在线库
    assert store.read(clean_run) is not None
    seal = cold.verify_package(settings.cold_root, clean_run)
    assert seal["merkle_root"] == first["merkle_root"]
    names = {entry["name"] for entry in seal["entries"]}
    assert {"manifest.json", "results.json", "train-summary.json"} <= names
    assert any(name.startswith("trains/") for name in names)
    events = [row["code"] for row in archive.events(clean_run)]
    assert events.count("FROZEN") == 1 and events.count("FREEZE_REUSED") == 1


def test_corrupt_package_is_detected_and_purge_refuses(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    package = cold.package_zip(settings.cold_root, clean_run)
    original = package.read_bytes()
    package.write_bytes(original[:-4] + b"XXXX")
    with pytest.raises(DomainError) as exc:
        service.purge(store, archive, settings.cold_root, clean_run)
    assert exc.value.code in ("PACKAGE_CORRUPT", "PACKAGE_TAMPERED")
    # 闸门失败：在线记录原样保留，状态仍为 FROZEN
    assert store.read(clean_run) is not None
    assert archive.require(clean_run)["state"] == "FROZEN"
    package.write_bytes(original)
    record = service.purge(store, archive, settings.cold_root, clean_run)
    assert record["state"] == "PURGED" and record["reclaim_bytes"] > 0


def test_tampered_member_hash_fails_verification(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    seal_file = cold.seal_path(settings.cold_root, clean_run)
    seal = json.loads(seal_file.read_text(encoding="utf-8"))
    seal["entries"][0]["sha256"] = "0" * 64
    seal_file.write_text(json.dumps(seal), encoding="utf-8")
    with pytest.raises(DomainError) as exc:
        cold.verify_package(settings.cold_root, clean_run)
    assert exc.value.code == "PACKAGE_TAMPERED"


def test_unsealed_package_cannot_be_purged(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    cold.sealed_marker(settings.cold_root, clean_run).unlink()
    with pytest.raises(DomainError) as exc:
        service.purge(store, archive, settings.cold_root, clean_run)
    assert exc.value.code == "PACKAGE_MISSING"


def test_hmac_seal_rejects_wrong_key(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run, hmac_key=b"key-a")
    assert cold.verify_package(settings.cold_root, clean_run, hmac_key=b"key-a")["hmac"]
    with pytest.raises(DomainError) as exc:
        cold.verify_package(settings.cold_root, clean_run, hmac_key=b"key-b")
    assert exc.value.code == "PACKAGE_TAMPERED"


# ---------- 清理与恢复 ----------

def test_purge_removes_online_rows_but_keeps_ledger(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    with closing(store.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM runs WHERE id=?", (clean_run,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM events WHERE run_id=?", (clean_run,)).fetchone()[0] == 0
    record = archive.require(clean_run)
    assert record["state"] == "PURGED"
    assert json.loads(record["train_summary"])  # 台账凭据仍在
    with pytest.raises(DomainError) as exc:
        store.read(clean_run)
    assert exc.value.code == "RUN_UNKNOWN"


def test_restore_repours_identical_batch_and_verifies_every_train(stores, settings, clean_run):
    store, archive = stores
    manifest_before, results_before = store.read(clean_run)
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    report = service.restore(store, archive, settings.cold_root, clean_run)
    assert report["action"] == "RESTORED"
    assert report["train_count"] == report["matched"]
    assert report["review_count"] == 0
    manifest_after, results_after = store.read(clean_run)
    assert canonical(manifest_after) == canonical(manifest_before)
    assert canonical(results_after) == canonical(results_before)
    assert archive.require(clean_run)["state"] == "RESTORED"
    assert archive.require(clean_run)["restore_count"] == 1
    assert all(train["verified"] for train in report["trains"])


def test_restore_is_idempotent_and_never_creates_a_second_batch(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    first = service.restore(store, archive, settings.cold_root, clean_run)
    second = service.restore(store, archive, settings.cold_root, clean_run)
    assert first["action"] == "RESTORED" and second["action"] == "RESTORE_REUSED"
    with closing(store.connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert archive.require(clean_run)["restore_count"] == 1
    codes = [row["code"] for row in archive.events(clean_run)]
    assert codes.count("RESTORED") == 1 and codes.count("RESTORE_REUSED") == 1


def test_restore_dry_run_does_not_write(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    report = service.restore(store, archive, settings.cold_root, clean_run, dry_run=True)
    assert report["dry_run"] is True
    with pytest.raises(DomainError) as exc:
        store.read(clean_run)
    assert exc.value.code == "RUN_UNKNOWN"
    assert archive.require(clean_run)["state"] == "PURGED"


def test_restore_mismatch_on_tampered_results_blocks_writeback(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    # 直接篡改台账里记录的结果指纹，模拟冷包与凭据不一致
    with archive.transaction() as db:
        db.execute("UPDATE archive_ledger SET result_sha256=? WHERE run_id=?", ("0" * 64, clean_run))
    with pytest.raises(DomainError) as exc:
        service.restore(store, archive, settings.cold_root, clean_run)
    assert exc.value.code == "RESTORE_MISMATCH"
    with pytest.raises(DomainError):
        store.read(clean_run)
    assert archive.require(clean_run)["state"] == "PURGED"


# ---------- 抽查回读 ----------

def test_readback_serves_online_then_cold_without_state_change(stores, settings, clean_run):
    store, archive = stores
    service.freeze(store, archive, settings.cold_root, clean_run)
    online = service.readback(store, archive, settings.cold_root, clean_run)
    assert online["source"] == "ONLINE"
    service.purge(store, archive, settings.cold_root, clean_run)
    cold_view = service.readback(store, archive, settings.cold_root, clean_run)
    assert cold_view["source"] == "COLD" and cold_view["state"] == "PURGED"
    pass_id = cold_view["trains"][0]
    train = service.readback(store, archive, settings.cold_root, clean_run, pass_id)["train"]
    assert train["pass_id"] == pass_id
    assert train["conclusion"]["status"] == "matched"
    assert train["slice_sha256"] == digest(canonical({
        key: value for key, value in train.items() if key != "slice_sha256"
    }).encode("utf-8"))
    # 回读不改变状态、不回灌
    assert archive.require(clean_run)["state"] == "PURGED"
    with pytest.raises(DomainError):
        store.read(clean_run)
    # 原轴组证据完整：轮级触发与标定引用都在切片内
    assert train["axles"], "整车切片必须包含轴组证据"
    for item in train["axles"]:
        assert item["axis"]["left"]["trigger"]["source"]["ref"]
        assert item["axis"]["right"]["trigger"]["source"]["ref"]


# ---------- 批次边界不可拆 ----------

def test_archive_never_splits_a_train_across_packages(stores, settings, dirty_run):
    store, archive = stores
    # dirty 批次整体不合格（含待复秤），无法通过服务层封冻
    with pytest.raises(DomainError) as exc:
        service.freeze(store, archive, settings.cold_root, dirty_run)
    assert exc.value.code == "ARCHIVE_REVIEW_OPEN"
    # 合格批次的冷包里，每个车次的全部轴组都在同一包内
    clean = commit(stores, settings, "clean")
    manifest, results = store.read(clean)
    slices = build_train_slices(manifest, results)
    service.freeze(store, archive, settings.cold_root, clean)
    payload = cold.open_payload(settings.cold_root, clean)
    for pass_id, train in slices.items():
        member = f"trains/{pass_id}.json"
        restored = json.loads(payload[member])
        assert len(restored["axles"]) == len(train["axles"])
        assert restored["slice_sha256"] == train["slice_sha256"]


# ---------- 恢复后的车次结论可核对 ----------

def test_restore_report_matches_sealed_conclusions(stores, settings, dirty_run, clean_run):
    store, archive = stores
    manifest, results = store.read(dirty_run)
    summary = summarize_slices(build_train_slices(manifest, results))
    review_trains = [pass_id for pass_id, item in summary.items() if item["status"] == "review"]
    assert review_trains  # dirty 批次确有待复秤车次，规划层必须挡住
    service.freeze(store, archive, settings.cold_root, clean_run)
    service.purge(store, archive, settings.cold_root, clean_run)
    report = service.restore(store, archive, settings.cold_root, clean_run)
    sealed = json.loads(archive.require(clean_run)["train_summary"])
    for train in report["trains"]:
        assert train["slice_sha256"] == sealed[train["pass_id"]]["slice_sha256"]
        assert train["status"] == sealed[train["pass_id"]]["status"]


# ---------- 并发与未知批次 ----------

def test_unknown_run_and_unknown_archive_fail_explicitly(stores, settings):
    store, archive = stores
    with pytest.raises(DomainError) as exc:
        service.freeze(store, archive, settings.cold_root, "missing")
    assert exc.value.code == "RUN_UNKNOWN"
    with pytest.raises(DomainError) as exc:
        service.purge(store, archive, settings.cold_root, "missing")
    assert exc.value.code == "ARCHIVE_UNKNOWN"


def test_concurrent_freeze_commits_one_ledger_row(stores, settings, clean_run):
    from concurrent.futures import ThreadPoolExecutor

    store, archive = stores
    with ThreadPoolExecutor(max_workers=4) as workers:
        outcomes = list(workers.map(
            lambda _: service.freeze(store, archive, settings.cold_root, clean_run), range(4),
        ))
    rows = [item[0] for item in outcomes]
    assert all(row["merkle_root"] == rows[0]["merkle_root"] for row in rows)
    assert archive.list() and len(archive.list()) == 1
    assert [row["code"] for row in archive.events(clean_run)].count("FROZEN") == 1


def test_pipeline_results_round_trip_through_cold_package(stores, settings):
    """端到端：流水线结果 → 冷包 → 恢复，序列化字节完全一致。"""
    store, archive = stores
    sources = read_sources(ROOT / "sample_data", "clean")
    results = run_pipeline(sources)
    manifest = {
        "run_id": digest(b"synthetic-roundtrip"), "sample": "clean", "created_at": "2026-11-21T00:00:00Z",
        "result_sha256": digest(canonical(results).encode("utf-8")),
        "ledger": results["reconcile"]["ledger"],
    }
    run_id = manifest["run_id"]
    with store.transaction() as db:
        add_run(db, manifest, results)
    service.freeze(store, archive, settings.cold_root, run_id)
    service.purge(store, archive, settings.cold_root, run_id)
    service.restore(store, archive, settings.cold_root, run_id)
    manifest_back, results_back = store.read(run_id)
    assert canonical(results_back) == canonical(results)
    assert manifest_back["result_sha256"] == manifest["result_sha256"]
