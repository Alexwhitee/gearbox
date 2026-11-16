#!/usr/bin/env bash
# resolve-models.sh — 宿主判定（内联精简版）
#
# 用法：HOST_ENV="$(resolve-models.sh --root <repo_root>)"; eval "$HOST_ENV"
# 输出一行：export G_HOST=claude|codex|unknown
#
# 模型档位 / effort / 跨模型 voice 机械已随 fan-out 架构整体移除（恢复看 git 历史）。
# 本脚本只回答「当前跑在哪个宿主」，供报告如实标注；不派发、不切换、不猜测机队。
set -u

ROOT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      [ $# -ge 2 ] || { echo "resolve-models: --root requires a value" >&2; exit 64; }
      case "$2" in -*) echo "resolve-models: --root requires a value" >&2; exit 64 ;; esac
      ROOT="$2"; shift 2 ;;
    *) echo "resolve-models: unknown arg: $1" >&2; exit 64 ;;
  esac
done
if [ -z "$ROOT" ]; then
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd 2>/dev/null || true)"
fi
[ -n "$ROOT" ] && [ -d "$ROOT" ] || { echo "resolve-models: root 不可用: ${ROOT:-空}" >&2; exit 66; }

_claude=0; _codex=0
[ "${CLAUDECODE:-}" = "1" ] && _claude=1
[ -n "${CODEX_THREAD_ID:-}" ] && _codex=1

if [ "$_claude" -eq 1 ] && [ "$_codex" -eq 1 ]; then
  echo "resolve-models: ⚠ 宿主信号冲突（CLAUDECODE=1 且 CODEX_THREAD_ID 非空）——HOST=unknown" >&2
  HOST="unknown"
elif [ "$_claude" -eq 1 ]; then
  HOST="claude"
elif [ "$_codex" -eq 1 ]; then
  HOST="codex"
else
  HOST="unknown"
fi

printf 'export G_HOST=%q\n' "$HOST"
