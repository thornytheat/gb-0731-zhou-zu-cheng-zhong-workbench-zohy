"""把 clean / dirty 样例提交到指定在线库，供归档演示与手工演练使用。"""

import argparse
from pathlib import Path

from app.config import ROOT
from app.modules.m7_batches.service import commit_sample
from app.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(description="归档演示：向在线库播种两个称重批次")
    parser.add_argument("--db", required=True)
    parser.add_argument("--print-id", choices=("clean", "dirty"), help="仅输出指定样例的 run_id")
    args = parser.parse_args(argv)

    store = Store(Path(args.db))
    store.initialize()
    ids = {}
    for sample in ("clean", "dirty"):
        manifest, _ = commit_sample(store, ROOT / "sample_data", sample)
        ids[sample] = manifest["run_id"]
    if args.print_id:
        print(ids[args.print_id])
    else:
        for sample, run_id in ids.items():
            print(f"{sample}\t{run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
