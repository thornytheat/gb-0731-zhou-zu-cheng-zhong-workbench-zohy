"""按车次切分原轴组证据。

冷包内每个车次一个 JSON 切片，恢复与抽查回读都以整车为原子单元，
绝不允许只搬走同一车次的部分轴组证据。
"""

from app.manifest import canonical, digest


def _issue_index(results):
    index = {}
    for issue in results["quarantine"]:
        index.setdefault(issue["pass_id"], []).append(issue)
    for issue in results["debounce"]["duplicates"]:
        index.setdefault(issue["pass_id"], []).append(issue)
    return index


def build_train_slices(manifest: dict, results: dict) -> dict[str, dict]:
    """返回 {车次: 切片}；切片自带内容哈希，恢复后逐车比对。"""
    issues = _issue_index(results)
    axes_by_pass = {}
    for axis in results["axles"]["axes"]:
        axes_by_pass.setdefault(axis["pass_id"], []).append(axis)
    grades = {row["id"]: row for row in results["balance"]["rows"]}

    slices = {}
    for row in results["reconcile"]["rows"]:
        pass_id = row["pass_id"]
        train = {
            "run_id": manifest["run_id"],
            "pass_id": pass_id,
            "plate": row["plate"],
            "conclusion": {
                "status": row["status"],
                "codes": list(row["codes"]),
                "wheel_kg": row["wheel_kg"],
                "difference_kg": row["difference_kg"],
                "axle_ids": list(row["axle_ids"]),
                "pass_ref": row["pass_ref"],
                "ticket_refs": list(row["ticket_refs"]),
                "wheel_refs": list(row["wheel_refs"]),
                "review_refs": list(row["review_refs"]),
                "ticket": row["ticket"],
            },
            "axles": [],
            "evidence": {
                "issues": issues.get(pass_id, []),
                "ticket_issues": [
                    item for item in results["reconcile"]["ticket_issues"] if item["pass_id"] == pass_id
                ],
            },
        }
        for axis in axes_by_pass.get(pass_id, []):
            train["axles"].append({"axis": axis, "balance": grades.get(axis["id"])})
        train["slice_sha256"] = digest(canonical(train).encode("utf-8"))
        slices[pass_id] = train
    return slices


def slice_file(pass_id: str) -> str:
    return f"trains/{pass_id}.json"


def summarize_slices(slices: dict[str, dict]) -> dict:
    """封条级车次摘要：结论指纹与待复秤标记，供恢复后逐车核对。"""
    summary = {}
    for pass_id, train in sorted(slices.items()):
        summary[pass_id] = {
            "slice_sha256": train["slice_sha256"],
            "status": train["conclusion"]["status"],
            "codes": list(train["conclusion"]["codes"]),
            "axles": len(train["axles"]),
            "wheel_kg": train["conclusion"]["wheel_kg"],
            "difference_kg": train["conclusion"]["difference_kg"],
        }
    return summary
