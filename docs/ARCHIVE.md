# M8 冷存归档工作台

审计季在线库容量不足时，按**完整批次**转冷；抽查车次随时可从验封冷包回读原轴组证据。
模块建立在 M7 内容寻址批次（`run_id` = 来源文件 SHA-256 + 规则版本 + 参数的哈希）之上。

## 冷存边界（先转冷的范围怎么划）

批次是最小不可拆单元，一个批次内的全部车次、轴组与轮级触发证据同进同出，
不允许把同一车次的部分轴组搬到冷包。`plan` 按以下硬规则给出范围：

| 规则 | 效果 | 错误码 |
|---|---|---|
| 抽查保留单生效中 | 封冻、清理一律拒绝 | `ARCHIVE_HELD` |
| 含待复秤车次（`status=review`） | 不具备转冷资格 | `ARCHIVE_REVIEW_OPEN` |
| 触发流水未核平（`ledger.balanced=false`） | 不具备转冷资格 | `ARCHIVE_UNBALANCED` |
| 已清理批次 | 不计入可回收容量 | — |

合格批次按封冻时间成本排序（旧批次优先、同龄大批次优先），整批累加直到满足容量需求；
被挡住的批次在 `blocked` 中逐条给出原因，审计可直接核对为什么没有动它。

## 状态机与完整性凭据

```
ONLINE ──freeze──▶ FROZEN ──purge──▶ PURGED ──restore──▶ RESTORED
                       │                 │
                       └ 冷包已封边，     └ 在线库已删，仅冷包可回读
                         在线记录保留       （台账与封条永久保留）
```

冷包目录 `var/cold/<run_id>/`：

- `package.zip`：`manifest.json`、`results.json`、`train-summary.json` 与 `trains/<车次>.json`，
  ZIP 使用固定 DOS 时刻，同载荷反复封包字节一致；
- `seal.json`：每个成员的 SHA-256、Merkle 根（两两哈希合并），可选 HMAC-SHA256；
- `SEALED`：封边标记，只在临时目录构建并自验通过、原子 rename 落位后才生成。

**删库闸门**：`purge` 先重新验封（封边标记 → 逐文件哈希与 Merkle 根 → HMAC），
任一不过即抛 `PACKAGE_MISSING` / `PACKAGE_CORRUPT` / `PACKAGE_TAMPERED`，
在线库一行不删、台账状态不变。

## 恢复幂等与车次结论

- 恢复按原 `run_id` 回灌，先比对 `result_sha256`、再逐车次比对切片指纹与台账摘要，
  任一不符抛 `RESTORE_MISMATCH` 且不写在线库；
- 在线库已存在同 `run_id` 批次时，重复恢复只追加 `RESTORE_REUSED` 事件，
  **不会生成第二个批次**，`restore_count` 不增加；
- 恢复报告逐车列出 `status`、原因码、轮载合计、差额与 `slice_sha256`，可与封条直接核对。

## 抽查回读

`readback` 在线优先；批次已清理时从验封冷包流式取整车切片，
含轴组、左右轮触发的源文件行号引用、标定证书引用与隔离证据。
回读不回灌、不改变冷存状态。

## CLI

```sh
python -m app.modules.m8_archive.cli plan --need-bytes 4096
python -m app.modules.m8_archive.cli eligibility <run_id>
python -m app.modules.m8_archive.cli freeze <run_id> [--hmac-key SECRET]
python -m app.modules.m8_archive.cli verify-seal <run_id>
python -m app.modules.m8_archive.cli purge <run_id>
python -m app.modules.m8_archive.cli readback <run_id> --pass 0007
python -m app.modules.m8_archive.cli restore <run_id> [--dry-run]
python -m app.modules.m8_archive.cli hold <run_id> --subject 审计抽查-Q4 --reason 待回读
python -m app.modules.m8_archive.cli holds
python -m app.modules.m8_archive.cli release <hold_id>
python -m app.modules.m8_archive.cli ledger
python -m app.modules.m8_archive.cli events [<run_id>]
```

全局参数 `--db`、`--archive-db`、`--cold-root` 可指向隔离演练目录；
`--json` 放在子命令前。端到端演练：`scripts/archive_demo.sh`。

## HTTP 接口

| 方法与路径 | 用途 |
|---|---|
| `GET /api/archive/ledger` | 冷存台账（状态、Merkle 根、回收字节、恢复次数） |
| `GET /api/archive/eligibility/{run_id}` | 单批转冷资格与阻塞原因 |
| `GET /api/archive/plan?need_bytes=N` | 容量规划 |
| `POST /api/archive/freeze` | 封冻（重复执行返回 200 + `reused=true`） |
| `GET /api/archive/seal/{run_id}` | 复验封条 |
| `POST /api/archive/purge` | 验封后清理 |
| `POST /api/archive/restore?dry_run=false` | 恢复并逐车核对 |
| `GET /api/archive/readback/{run_id}?pass_id=` | 抽查回读 |
| `GET/POST /api/archive/holds`、`POST /api/archive/holds/{id}/release` | 抽查保留单 |
| `GET /api/archive/events` | 只追加归档事件 |

## 环境变量

`WEIGH_ARCHIVE_DB`、`WEIGH_COLD_ROOT` 分别指定归档台账与冷包根目录；
`WEIGH_COLD_HMAC` 设置后封条带 HMAC，验封与回读必须提供同一密钥。
