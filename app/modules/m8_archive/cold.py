"""冷包构建、封边与验封。

冷包目录布局（一个批次一个目录，目录名即内容寻址 run_id）::

    cold/<run_id>/
        package.zip              # 载荷，ZIP_DEFLATED，固定 DOS 时刻保证可复算
        seal.json                # 封条：逐文件 SHA-256、Merkle 根、HMAC
        SEALED                   # 封边标记，仅在全部写入并复验成功后落盘

封条是删库前的唯一凭据：没有 SEALED 或 Merkle 根对不上，服务层一律拒绝清理。
"""

import hashlib
import hmac
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from app.errors import DomainError
from app.manifest import canonical, digest

SEAL_NAME = "seal.json"
SEALED_MARKER = "SEALED"
PACKAGE_NAME = "package.zip"


def package_dir(cold_root: Path, run_id: str) -> Path:
    return cold_root / run_id


def package_zip(cold_root: Path, run_id: str) -> Path:
    return package_dir(cold_root, run_id) / PACKAGE_NAME


def seal_path(cold_root: Path, run_id: str) -> Path:
    return package_dir(cold_root, run_id) / SEAL_NAME


def sealed_marker(cold_root: Path, run_id: str) -> Path:
    return package_dir(cold_root, run_id) / SEALED_MARKER


def _merkle_root(entries):
    """按文件名排序后对叶子哈希两两合并，奇数节点复制末节点。"""
    leaves = [entry["sha256"] for entry in sorted(entries, key=lambda item: item["name"])]
    if not leaves:
        return hashlib.sha256(b"empty-cold-package").hexdigest()
    level = leaves
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256((level[i] + level[i + 1]).encode("ascii")).hexdigest()
                 for i in range(0, len(level), 2)]
    return level[0]


def build_zip(payload: dict[str, bytes]) -> bytes:
    """用固定 DOS 时刻写 ZIP，使同一载荷反复封包得到同一字节序列。"""
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(payload):
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload[name])
    return buffer.getvalue()


def _zip_entries(data: bytes):
    """直接在内存字节上计算条目哈希，不落临时目录。"""
    import io

    entries = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            bad = archive.testzip()
            if bad is not None:
                raise DomainError("PACKAGE_CORRUPT", 422, detail={"member": bad})
            for name in sorted(archive.namelist()):
                content = archive.read(name)
                entries.append({
                    "name": name,
                    "size": len(content),
                    "sha256": digest(content),
                })
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise DomainError("PACKAGE_CORRUPT", 422, detail={"reason": str(exc)}) from exc
    return entries


def make_seal(run_id: str, entries, *, rule_version: str, hmac_key: bytes | None) -> dict:
    seal = {
        "run_id": run_id,
        "rule_version": rule_version,
        "algorithm": "sha256-merkle",
        "entries": entries,
        "merkle_root": _merkle_root(entries),
        "hmac_algorithm": "HMAC-SHA256" if hmac_key else None,
        "hmac": None,
    }
    if hmac_key:
        seal["hmac"] = hmac.new(
            hmac_key, canonical({k: v for k, v in seal.items() if k != "hmac"}).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    return seal


def write_package(cold_root: Path, run_id: str, payload: dict[str, bytes], *,
                  rule_version: str, hmac_key: bytes | None = None) -> dict:
    """原子落盘：临时目录构建 → 自验 → 整体 rename，最后才放 SEALED 标记。

    已封边且凭据一致的包直接复用，保证重复执行不重复生成。
    """
    target = package_dir(cold_root, run_id)
    if is_sealed(cold_root, run_id):
        return verify_package(cold_root, run_id, hmac_key=hmac_key)

    data = build_zip(payload)
    entries = _zip_entries(data)
    seal = make_seal(run_id, entries, rule_version=rule_version, hmac_key=hmac_key)

    cold_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{run_id}-", dir=cold_root.resolve()))
    try:
        (staging / PACKAGE_NAME).write_bytes(data)
        (staging / SEAL_NAME).write_text(
            json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8",
        )
        # 落位前先在临时目录自验内容，通过后才原子 rename；SEALED 标记最后落盘。
        _verify_contents(staging / PACKAGE_NAME, staging / SEAL_NAME, hmac_key)
        try:
            # 目标此前不可能存在有效包（is_sealed 已判），rename 是同文件系统原子操作。
            os.replace(staging, target)
        except OSError:
            # 并发封冻：另一线程已抢先落位。清理自己的暂存区，改走验封复用路径。
            if not is_sealed(cold_root, run_id):
                raise
            return verify_package(cold_root, run_id, hmac_key=hmac_key)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    if not is_sealed(cold_root, run_id):
        sealed_marker(cold_root, run_id).touch()
    return seal


def is_sealed(cold_root: Path, run_id: str) -> bool:
    return sealed_marker(cold_root, run_id).is_file() and package_zip(cold_root, run_id).is_file()


def _verify_contents(zip_file: Path, seal_file: Path, hmac_key: bytes | None) -> dict:
    """对指定的 ZIP 与封条做内容级校验（不检查 SEALED 标记）。"""
    if not zip_file.is_file() or not seal_file.is_file():
        raise DomainError("PACKAGE_MISSING", 409)
    seal = json.loads(seal_file.read_text(encoding="utf-8"))
    entries = _zip_entries(zip_file.read_bytes())
    if entries != seal["entries"] or _merkle_root(entries) != seal["merkle_root"]:
        raise DomainError("PACKAGE_TAMPERED", 409, detail={"run_id": seal.get("run_id")})
    if seal.get("hmac"):
        if not hmac_key:
            raise DomainError("PACKAGE_CORRUPT", 409, detail={"reason": "封条带 HMAC 但未提供密钥"})
        expected = hmac.new(
            hmac_key,
            canonical({k: v for k, v in seal.items() if k != "hmac"}).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, seal["hmac"]):
            raise DomainError("PACKAGE_TAMPERED", 409, detail={"run_id": seal.get("run_id"), "hmac": True})
    return seal


def verify_package(cold_root: Path, run_id: str, *, hmac_key: bytes | None = None) -> dict:
    """三重校验：封边标记 → ZIP 内逐文件哈希与 Merkle 根 → 可选 HMAC。"""
    if not is_sealed(cold_root, run_id):
        raise DomainError("PACKAGE_MISSING", 409)
    return _verify_contents(package_zip(cold_root, run_id), seal_path(cold_root, run_id), hmac_key)


def open_payload(cold_root: Path, run_id: str, *, hmac_key: bytes | None = None):
    """验封后返回 {文件名: 字节}，供回读与恢复使用，不向在线库写任何内容。"""
    import io

    verify_package(cold_root, run_id, hmac_key=hmac_key)
    with zipfile.ZipFile(io.BytesIO(package_zip(cold_root, run_id).read_bytes())) as archive:
        return {name: archive.read(name) for name in archive.namelist()}
