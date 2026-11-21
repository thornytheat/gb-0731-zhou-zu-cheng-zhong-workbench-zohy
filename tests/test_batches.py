import csv
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO, StringIO
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.main import create_app


def run(client, sample="dirty"):
    return client.post("/api/batches", json={"sample": sample})


def read_csv(bundle, name, key):
    return {row[key]: row for row in csv.DictReader(StringIO(bundle.read(name).decode("utf-8-sig")))}


def test_full_flow_from_unarchived_preview_to_standalone_export(client, settings):
    page = client.get("/")
    assert page.status_code == 200
    assert all(word in page.text for word in ("运行样例", "重跑", "导出复核包", "暂停滚动", "左右轮载"))
    assert client.get("/api/workbench").json()["manifest"] is None
    response = run(client)
    assert response.status_code == 201
    manifest = response.json()["manifest"]
    run_id = manifest["run_id"]
    assert manifest["ledger"]["wheel_kg"] == "49590.01"
    assert manifest["files"]["triggers"]["sha256"] == hashlib.sha256(
        (settings.source_dir / "dirty-triggers.csv").read_bytes(),
    ).hexdigest()
    response = client.get(f"/api/batches/{run_id}/export")
    assert response.headers["Content-Type"] == "application/zip"
    assert response.headers["Content-Disposition"] == f'attachment; filename="axle-{run_id[:12]}.zip"'
    with ZipFile(BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {"运行清单.json", "触发复核.csv", "整车勾稽.csv", "轴组轮载.csv"}
        assert json.loads(bundle.read("运行清单.json")) == manifest
        votes = read_csv(bundle, "整车勾稽.csv", "车次")
        assert votes["0007"]["差额kg"] == "50.00"
        assert votes["0023"]["状态"] == "待复秤"
        axes = read_csv(bundle, "轴组轮载.csv", "轴号")
        assert axes["0007/A03"]["偏载率%"] == "20.00"
        issues = list(csv.DictReader(StringIO(bundle.read("触发复核.csv").decode("utf-8-sig"))))
        row = next(item for item in issues if item["原因码"] == "CAL_OVERLAP")
        assert (row["起始行"], row["关联证据"]) == ("23", "certificates.csv:4 / certificates.csv:5")
        assert len(issues) == 30


def test_idempotent_post_reuses_manifest_and_results(client):
    first = run(client).json()["manifest"]
    second = run(client)
    assert second.status_code == 200
    assert second.json() == {"manifest": first, "reused": True}
    assert client.get("/api/batches").json()["batches"] == [first]


def test_exact_replay_is_new_log_event_with_same_export_bytes(client):
    first = run(client).json()["manifest"]
    run_path = f"/api/batches/{first['run_id']}"
    before = client.get(f"{run_path}/export").content
    cursor = client.get("/api/batches/events").json()["cursor"]
    outcome = client.post(f"{run_path}/rerun")
    assert outcome.json() == {"manifest": first, "reused": True, "replayed": True}
    assert client.get(f"{run_path}/export").content == before
    assert client.get("/api/batches").json()["batches"] == [first]
    rows = client.get(f"/api/batches/events?after={cursor}").json()["events"]
    assert [(row["seq"], row["code"]) for row in rows] == [(cursor + 1, "REPLAYED")]


def test_changed_source_rejects_rerun_without_rewriting_old_snapshot(client, settings):
    original = run(client).json()["manifest"]
    run_id = original["run_id"]
    source = settings.source_dir / "dirty-triggers.csv"
    source.write_bytes(source.read_bytes() + b"\r\n")
    reply = client.post(f"/api/batches/{run_id}/rerun")
    assert (reply.status_code, reply.json()["error"]["code"]) == (409, "SOURCE_CHANGED")
    assert client.get("/api/batches").json()["batches"] == [original]
    new = run(client).json()["manifest"]
    assert new["run_id"] != run_id
    assert new["ledger"] == original["ledger"]


def test_fatal_source_rolls_back_everything_and_can_recover(client, settings):
    path = settings.source_dir / "dirty-tickets.csv"
    original = path.read_bytes()
    path.write_bytes(original + b'"cut off\n')
    broken = run(client)
    assert (broken.status_code, broken.json()["error"]["code"]) == (422, "CSV_SYNTAX")
    assert client.get("/api/batches").json()["batches"] == []
    assert client.get("/api/batches/events").json() == {"events": [], "cursor": 0}
    path.write_bytes(original)
    assert run(client).status_code == 201


def test_database_error_after_snapshot_insert_rolls_back_the_entire_batch(client, settings):
    with closing(sqlite3.connect(settings.db_file)) as db:
        db.executescript("""
            CREATE TRIGGER deny_log BEFORE INSERT ON events
            BEGIN SELECT RAISE(ABORT, 'receipt write failed'); END;
        """)
    with TestClient(client.app, raise_server_exceptions=False) as tolerant:
        assert run(tolerant).status_code == 500
    assert client.get("/api/batches").json()["batches"] == []
    assert client.get("/api/batches/events").json()["events"] == []


def test_concurrent_runs_commit_once(client):
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: run(client), range(4)))
    assert sorted(result.status_code for result in results) == [200, 200, 200, 201]
    ids = {result.json()["manifest"]["run_id"] for result in results}
    assert len(ids) == 1
    codes = [event["code"] for event in client.get("/api/batches/events").json()["events"]]
    assert (codes.count("COMMITTED"), codes.count("REUSED")) == (1, 3)


def test_events_use_cursor_without_reordering_or_duplicates(client):
    manifest = run(client).json()["manifest"]
    base = "/api/batches/events"
    first = client.get(f"{base}?limit=5").json()
    second = client.get(f"{base}?after={first['cursor']}&limit=5").json()
    assert [event["seq"] for event in first["events"] + second["events"]] == list(range(1, 11))
    assert first["events"][0]["code"] == "START"
    axle = next(event for event in second["events"] if event["code"] == "AXLE")
    assert axle["source_time"].startswith("2026-11-20T12:00:")
    assert axle["run_id"] == manifest["run_id"]


def test_archive_survives_app_restart_and_supports_export_without_sources(client, settings):
    manifest = run(client).json()["manifest"]
    run_id = manifest["run_id"]
    export = client.get(f"/api/batches/{run_id}/export").content
    (settings.source_dir / "dirty-triggers.csv").unlink()
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(f"/api/batches/{run_id}").json()["manifest"] == manifest
        assert restarted.get(f"/api/batches/{run_id}/export").content == export
        assert restarted.get(f"/api/axles?run_id={run_id}").json()["data"]["groups"] == 8
        assert restarted.post(f"/api/batches/{run_id}/rerun").json()["error"]["code"] == "SOURCE_MISSING"


def test_independent_module_entrypoints_return_sample_evidence(client):
    expected = {
        "intake": ("raw", 50), "calibration": ("certificates", 4), "debounce": ("duplicates", 3),
        "axles": ("groups", 8), "balance": ("rows", 11), "reconcile": ("rows", 7),
    }
    for stage, (key, count) in expected.items():
        response = client.get(f"/api/{stage}?sample=dirty")
        assert response.status_code == 200
        actual = response.json()["data"][key]
        assert (len(actual) if isinstance(actual, list) else actual) == count
    assert client.get("/api/batches").json() == {"batches": []}


def test_early_stages_do_not_require_unused_sources(client, settings):
    (settings.source_dir / "dirty-tickets.csv").unlink()
    assert client.get("/api/balance").json()["data"]["counts"]["severe"] == 1
    assert client.get("/api/reconcile").json()["error"]["file"] == "dirty-tickets.csv"
    (settings.source_dir / "certificates.csv").unlink()
    assert client.get("/api/intake").json()["data"]["raw"] == 50
    assert client.get("/api/calibration").json()["error"]["file"] == "certificates.csv"


def test_invalid_sample_export_id_and_log_limits_fail_explicitly(client):
    reply = run(client, "absent")
    assert (reply.status_code, reply.json()["error"]["code"]) == (404, "SAMPLE_UNKNOWN")
    for path in ("/api/batches/absent/export", "/api/intake?run_id=absent"):
        response = client.get(path)
        assert (response.status_code, response.json()["error"]["code"]) == (404, "RUN_UNKNOWN")
    assert client.get("/api/batches/events?limit=0").status_code == 422
