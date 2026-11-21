from time import perf_counter_ns

from app.errors import DomainError
from app.manifest import canonical, clock, digest, identify
from app.modules.m7_batches.pipeline import run_pipeline
from app.sources import read_sources
from app.store import add_events, add_run, find


def commit_sample(store, source_dir, sample):
    sources = read_sources(source_dir, sample)
    identity = identify(sample, sources)
    run_id = identity["run_id"]
    with store.transaction() as db:
        existing = find(db, run_id)
        if existing:
            add_events(db, run_id, [(clock(), "info", "REUSED", "相同来源已归档", None)])
            return existing[0], True
        started = perf_counter_ns()
        events = [(clock(), "info", "START", "开始读取称重源文件", None)]
        results = run_pipeline(sources, events=events)
        manifest = {
            **identity,
            "created_at": clock(),
            "elapsed_ms": (perf_counter_ns() - started) // 1_000_000,
            "result_sha256": digest(canonical(results).encode("utf-8")),
            "ledger": results["reconcile"]["ledger"],
        }
        add_run(db, manifest, results)
        add_events(db, run_id, events + [(manifest["created_at"], "ok", "COMMITTED", "批次已归档", None)])
        return manifest, False


def replay_sample(store, source_dir, run_id):
    manifest, original = store.read(run_id)
    sample = manifest["sample"]
    current = read_sources(source_dir, sample)
    if identify(sample, current)["run_id"] != run_id:
        raise DomainError("SOURCE_CHANGED", 409)
    recomputed = run_pipeline(current)
    if canonical(recomputed) != canonical(original):
        raise DomainError("REPLAY_MISMATCH", 409)
    with store.transaction() as db:
        add_events(db, run_id, [(clock(), "ok", "REPLAYED", "重算核验一致 · 沿用归档", None)])
    return manifest
