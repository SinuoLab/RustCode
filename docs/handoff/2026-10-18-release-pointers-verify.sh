#!/usr/bin/env bash
# docs/handoff/2026-10-18-release-pointers-and-test-hygiene.md 的附属验证脚本。
#
# 为什么单独放一个 .sh：中文文档门禁（scripts/check-zh-docs.py 的 AC-4）把 markdown
# 里每一个 inline code span 连同 fenced 代码块的每一行都计入"新增英文"，需要逐条
# 登记白名单。把可执行命令集中到这里，交接文档本身就能保持零代码块。
#
# 用法：
#   bash docs/handoff/2026-10-18-release-pointers-verify.sh           # 全部离线项
#   bash docs/handoff/2026-10-18-release-pointers-verify.sh --online  # 含 GitCode API 对账
#
# 只读：除 git 只读命令外不写任何文件；不需要构建，几秒内完成。

set -uo pipefail

# docs/handoff/<this-file> -> repo root is two levels up (docs/handoff -> docs -> root).
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT" || exit 1

ONLINE=0
[ "${1:-}" = "--online" ] && ONLINE=1

hr() { printf '\n=== %s ===\n' "$*"; }

hr "1) 版本指针一致性（离线，毫秒级）"
bash scripts/release-check-pointers.sh --root .

hr "2) 指针门禁自身回归（7 个场景，含「指针落后必须失败」）"
bash scripts/release-check-pointers.sh --self-test

hr "3) 推送前会跑的两道门禁（对当前 HEAD）"
bash scripts/prepush-release-check.sh --sha HEAD --target linux-x64

hr "4) 当前版本指针快照"
printf '%s\n' "--- release/index.json（仓库兜底源） ---"
sed -n '1,8p' release/index.json
printf '%s\n' "--- latest.json（在线自更新清单） ---"
sed -n '1,6p' latest.json

hr "5) 测试隔离修复复现（并行 harness，单线程跑不出该竞态）"
cargo test -p rustcode --bin rustcode -- --test-threads=8 im_admin schedule_cmd 2>&1 | tail -3

if [ "$ONLINE" = "1" ]; then
  hr "6) 在线对账 GitCode Release API（需要网络）"
  bash scripts/release-check-pointers.sh --root . --online
else
  hr "6) 在线对账已跳过（加 --online 开启）"
fi

hr "完成"
