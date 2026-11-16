#!/usr/bin/env bash
# checkpoint-commit.sh —— 工作流「过场提交」：固定 Conventional message。
#
# 由 workflow step prompt / 编排 skill 在「某逻辑步骤完成」时调用，非交互、自动过场。
# 区别于交互式 /commit-message（那个是最终提交，human-in-loop）。见 design.md §5.2。
#
# 焊死本机三坑（design.md §5.2）：
#   ① commit message 禁 `\` 续行 + heredoc（本机 shell 会损坏 message）→ 只用单行 -m，参数化拼接
#   ② core.fileMode=false：过场提交只记内容变更，不主动 --chmod、不 churn 权限位
#   ③ CRLF：本脚本纯 add + commit，不碰行尾（交给仓库 .gitattributes / gofmt 各自负责）
#
# 用法：
#   checkpoint-commit.sh <step> [描述]
#   checkpoint-commit.sh <step> <描述> -- openspec/<文件>...
#     → 报告模式仅提交指定路径；拒绝 openspec/ 外的脏改动，保留无关暂存文件。
#     → 普通模式仍 git add -A；代码 PASS 的报告必须用报告模式。
# 例：
#   checkpoint-commit.sh ff "生成 proposal/design/specs/tasks"
#     → commit: "checkpoint(ff): 生成 proposal/design/specs/tasks"
#   checkpoint-commit.sh spec-review
#     → commit: "checkpoint(spec-review)"
#
# 语义：无变更时静默跳过（过场提交不该因空提交中断流程）。

set -euo pipefail

if [ "$#" -lt 1 ] || [ -z "${1:-}" ]; then
  echo "用法: checkpoint-commit.sh <step> [描述]" >&2
  exit 2
fi

step="$1"
desc="${2:-}"
report_paths=()
if [ "$#" -gt 2 ]; then
  [ "$3" = "--" ] && [ "$#" -gt 3 ] || { echo "报告提交用法: $0 <step> <描述> -- openspec/<文件>..." >&2; exit 2; }
  shift 3
  for path in "$@"; do
    case "$path" in openspec/*) ;; *) echo "报告提交仅接受 openspec/ 内的路径" >&2; exit 2 ;; esac
    case "/$path/" in */../*|*/./*) echo "报告路径不得含 . 或 .. 组件" >&2; exit 2 ;; esac
    report_paths+=(":(literal)$path")
  done
fi

# 必须在 git 仓库内
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "checkpoint($step): 非 git 仓库，中止" >&2
  exit 2
fi

cd "$(git rev-parse --show-toplevel)"

if [ "${#report_paths[@]}" -gt 0 ]; then
  # 报告提交不得夹带源码，亦不得消耗用户已有的暂存区。
  untracked_code="$(git ls-files --others --exclude-standard -- . ':(exclude)openspec')"
  if ! git diff --quiet -- . ':(exclude)openspec' ||
     ! git diff --cached --quiet -- . ':(exclude)openspec' ||
     [ -n "$untracked_code" ]; then
    echo "报告提交拒绝：openspec/ 外存在未提交改动，先完成代码提交并重新检查" >&2
    exit 1
  fi
fi

# 无任何变更（含未跟踪文件）则跳过——git status --porcelain 空 = 干净
if [ -z "$(git status --porcelain)" ]; then
  echo "checkpoint($step): 无变更，跳过"
  exit 0
fi

# 拼 message：坑① 决定只用单行 subject（无 `\` 续行、无 heredoc、无 body 多行拼接）
if [ -n "$desc" ]; then
  subject="checkpoint($step): $desc"
else
  subject="checkpoint($step)"
fi

if [ "${#report_paths[@]}" -gt 0 ]; then
  git add -A -- "${report_paths[@]}"
  if git diff --cached --quiet -- "${report_paths[@]}"; then
    echo "checkpoint($step): 指定报告无变更，跳过"
    exit 0
  fi
  git commit --only -m "$subject" -- "${report_paths[@]}"
else
  git add -A
  git commit -m "$subject"
fi
echo "✓ $subject"
