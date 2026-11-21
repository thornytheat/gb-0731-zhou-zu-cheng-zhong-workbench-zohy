"""冷存归档工作台 CLI。

示例：
    python -m app.modules.m8_archive.cli plan --need-bytes 4096
    python -m app.modules.m8_archive.cli freeze <run_id>
    python -m app.modules.m8_archive.cli purge <run_id>
    python -m app.modules.m8_archive.cli restore <run_id>
    python -m app.modules.m8_archive.cli readback <run_id> --pass 0007
    python -m app.modules.m8_archive.cli hold <run_id> --subject 审计抽查-Q4 --reason 待回读
"""

import argparse
import json
import sys
from pathlib import Path

from app.config import Settings
from app.errors import DomainError
from app.modules.m8_archive import cold, service
from app.modules.m8_archive.archive_store import ArchiveStore
from app.store import Store


def _emit(payload, as_json: bool):
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if isinstance(payload, list):
        for item in payload:
            print(_line(item))
    elif isinstance(payload, dict) and "batches" in payload:
        for item in payload["batches"]:
            print(_line(item))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _line(item) -> str:
    if hasattr(item, "keys"):
        item = dict(item)
    keys = ("run_id", "state", "train_count", "review_count", "online_bytes",
            "reclaim_bytes", "restore_count", "merkle_root")
    return "  ".join(f"{key}={item[key]}" for key in keys if key in item)


def build_context(args):
    settings = Settings.from_env()
    if args.db:
        settings = Settings(
            settings.source_dir, Path(args.db),
            Path(args.archive_db) if args.archive_db else Path(args.db).parent / "archive.sqlite3",
            Path(args.cold_root) if args.cold_root else Path(args.db).parent / "cold",
        )
    if args.cold_root and not args.db:
        settings = Settings(settings.source_dir, settings.db_file, settings.archive_db_file, Path(args.cold_root))
    if args.archive_db and not args.db:
        settings = Settings(settings.source_dir, settings.db_file, Path(args.archive_db), settings.cold_root)
    store, archive = Store(settings.db_file), ArchiveStore(settings.archive_db_file)
    store.initialize()
    archive.initialize()
    key = args.hmac_key.encode("utf-8") if args.hmac_key else None
    return settings, store, archive, key


def main(argv=None):
    parser = argparse.ArgumentParser(prog="archive", description="轴组证据冷存归档工作台")
    parser.add_argument("--db", help="在线库路径（默认 WEIGH_DB 或 var/weigh.sqlite3）")
    parser.add_argument("--archive-db", help="归档台账路径")
    parser.add_argument("--cold-root", help="冷包根目录")
    parser.add_argument("--hmac-key", help="冷包 HMAC 密钥，默认不启用")
    parser.add_argument("--json", action="store_true", help="始终输出 JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ledger", help="列出冷存台账")

    p_elig = sub.add_parser("eligibility", help="查询单批转冷资格")
    p_elig.add_argument("run_id")

    p_plan = sub.add_parser("plan", help="按容量需求划定先转冷范围")
    p_plan.add_argument("--need-bytes", type=int, required=True)

    p_freeze = sub.add_parser("freeze", help="封冻：构建并验封冷包（不动在线库）")
    p_freeze.add_argument("run_id")

    p_purge = sub.add_parser("purge", help="验封后清理在线库")
    p_purge.add_argument("run_id")

    p_restore = sub.add_parser("restore", help="从冷包恢复并逐车核对结论")
    p_restore.add_argument("run_id")
    p_restore.add_argument("--dry-run", action="store_true")

    p_read = sub.add_parser("readback", help="抽查回读，不回灌在线库")
    p_read.add_argument("run_id")
    p_read.add_argument("--pass", dest="pass_id", help="仅回读指定车次")

    p_seal = sub.add_parser("verify-seal", help="单独复验冷包封条")
    p_seal.add_argument("run_id")

    p_hold = sub.add_parser("hold", help="放置抽查保留单")
    p_hold.add_argument("run_id")
    p_hold.add_argument("--subject", required=True)
    p_hold.add_argument("--reason", required=True)
    p_hold.add_argument("--expires-at")

    p_release = sub.add_parser("release", help="解除保留单")
    p_release.add_argument("hold_id")

    sub.add_parser("holds", help="列出有效保留单")

    p_events = sub.add_parser("events", help="查看归档事件")
    p_events.add_argument("run_id", nargs="?")

    args = parser.parse_args(argv)
    settings, store, archive, key = build_context(args)

    try:
        if args.command == "ledger":
            _emit({"batches": [dict(row) for row in archive.list()]}, args.json)
        elif args.command == "eligibility":
            _emit(service.eligibility(store, archive, args.run_id), True)
        elif args.command == "plan":
            _emit(service.plan(store, archive, args.need_bytes), True)
        elif args.command == "freeze":
            record, reused = service.freeze(store, archive, settings.cold_root, args.run_id, hmac_key=key)
            _emit({"batch": record, "reused": reused}, True)
        elif args.command == "purge":
            _emit({"batch": service.purge(store, archive, settings.cold_root, args.run_id, hmac_key=key)}, True)
        elif args.command == "restore":
            _emit({"report": service.restore(store, archive, settings.cold_root, args.run_id,
                                             hmac_key=key, dry_run=args.dry_run)}, True)
        elif args.command == "readback":
            _emit(service.readback(store, archive, settings.cold_root, args.run_id,
                                   args.pass_id, hmac_key=key), True)
        elif args.command == "verify-seal":
            _emit({"seal": cold.verify_package(settings.cold_root, args.run_id, hmac_key=key)}, True)
        elif args.command == "hold":
            _emit({"hold": service.place_hold(archive, args.run_id, args.subject,
                                              args.reason, expires_at=args.expires_at)}, True)
        elif args.command == "release":
            _emit({"hold": service.release_hold(archive, args.hold_id)}, True)
        elif args.command == "holds":
            _emit([dict(row) for row in archive.holds()], args.json)
        elif args.command == "events":
            rows = archive.events(args.run_id, limit=2**31 - 1)
            for row in rows:
                print(f"{row['seq']:>4} {row['time']} {row['level']:<4} {row['code']:<14} {row['message']}")
    except DomainError as exc:
        print(json.dumps({"error": exc.payload()}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
