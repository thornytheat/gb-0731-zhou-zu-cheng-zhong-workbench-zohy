#!/usr/bin/env bash
# 审计季冷存归档端到端演示：完全在 var/demo/ 隔离目录内运行，不触碰默认数据。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO="$ROOT/var/demo"
DB="$DEMO/weigh.sqlite3"
ARCHIVE_DB="$DEMO/archive.sqlite3"
COLD="$DEMO/cold"
rm -rf "$DEMO"
mkdir -p "$DEMO"

PY=(python3 -m app.modules.m8_archive.cli --db "$DB" --archive-db "$ARCHIVE_DB" --cold-root "$COLD")

echo "━━ 1. 先在在线库建立两个批次：clean（全核平）与 dirty（含待复秤车次）━━"
python3 -m app.modules.m8_archive.demo_seed --db "$DB"

echo
echo "━━ 2. 容量规划：需要腾 2048 字节，系统划定可转冷范围并列出阻塞批次 ━━"
"${PY[@]}" plan --need-bytes 2048

echo
echo "━━ 3. 对 clean 批次放置抽查保留单，验证保留期内禁止封冻 ━━"
CLEAN_ID=$(python3 -m app.modules.m8_archive.demo_seed --db "$DB" --print-id clean)
DIRTY_ID=$(python3 -m app.modules.m8_archive.demo_seed --db "$DB" --print-id dirty)
"${PY[@]}" hold "$CLEAN_ID" --subject "审计抽查-2026Q4" --reason "监管要求随时回读原轴组"
"${PY[@]}" freeze "$CLEAN_ID" || true

echo
echo "━━ 4. 解除保留后封冻 clean；dirty 因含待复秤车次被资格闸门拒绝 ━━"
HOLD_ID=$("${PY[@]}" --json holds | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['hold_id'])")
"${PY[@]}" release "$HOLD_ID" >/dev/null
"${PY[@]}" freeze "$CLEAN_ID"
"${PY[@]}" freeze "$DIRTY_ID" || true

echo
echo "━━ 5. 复验冷包封条（Merkle 根 + 逐文件 SHA-256）━━"
"${PY[@]}" verify-seal "$CLEAN_ID" | python3 -c "import sys,json; s=json.load(sys.stdin)['seal']; print('merkle_root =', s['merkle_root']); print('entries =', len(s['entries']))"

echo
echo "━━ 6. 验封通过后清理在线库，台账保留全部凭据 ━━"
"${PY[@]}" purge "$CLEAN_ID" | python3 -c "import sys,json; b=json.load(sys.stdin)['batch']; print('state =', b['state'], '| reclaim_bytes =', b['reclaim_bytes'])"

echo
echo "━━ 7. 抽查回读：在线已删，直接从冷包取整车原轴组证据（不回灌、不改状态）━━"
"${PY[@]}" readback "$CLEAN_ID" --pass 0007 | python3 -c "
import sys,json
t=json.load(sys.stdin)['train']
print('source = 冷包回读 | 车次 =', t['pass_id'], '| 结论 =', t['conclusion']['status'])
print('轴组数 =', len(t['axles']), '| 切片指纹 =', t['slice_sha256'][:16], '...')
ref=t['axles'][0]['axis']['left']['trigger']['source']['ref']
print('左轮原始证据引用 =', ref)
"

echo
echo "━━ 8. 恢复：逐车次核对封条结论，回灌在线库 ━━"
"${PY[@]}" restore "$CLEAN_ID" | python3 -c "
import sys,json
r=json.load(sys.stdin)['report']
print('action =', r['action'], '| 车次 =', r['train_count'], '| 逐车核对一致 =', r['matched'])
print('首车 =', r['trains'][0]['pass_id'], r['trains'][0]['status'], r['trains'][0]['slice_sha256'][:16])
"

echo
echo "━━ 9. 重复恢复：幂等，不产生第二个批次 ━━"
"${PY[@]}" restore "$CLEAN_ID" | python3 -c "import sys,json; print('action =', json.load(sys.stdin)['report']['action'])"

echo
echo "━━ 10. 归档事件全链路 ━━"
"${PY[@]}" events "$CLEAN_ID"

echo
echo "演示数据保留在 $DEMO，可用 \"${PY[*]} ledger\" 复查。"
