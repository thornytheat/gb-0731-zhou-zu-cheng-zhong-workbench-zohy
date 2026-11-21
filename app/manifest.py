import hashlib
import json
from datetime import UTC, datetime

from app.config import RULE_PARAMETERS, RULE_VERSION
from app.evidence import wire


def clock():
    return wire(datetime.now(UTC))


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identify(sample, sources):
    files = {role: {"file": source.name, "bytes": len(source.content), "sha256": digest(source.content)}
             for role, source in sources.items()}
    key = {"sample": sample, "files": files, "rules": RULE_VERSION, "parameters": RULE_PARAMETERS}
    return {"run_id": digest(canonical(key).encode("utf-8")), **key}
