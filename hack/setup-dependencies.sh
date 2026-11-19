#!/usr/bin/env bash
# setup.sh 的内部预检库：source 仅定义函数，不执行安装。
# 调用方先选择 Python，并通过 check_dependencies <python-command> 传入。
# ─── 运行依赖预检（shared-yaml-subset-parser · R1/R2）────────────────────
# 统一检测并报告全部运行依赖：python3 >= 3.7 / git / yq(mikefarah) / openspec / pytest（开发可选）。
# **不中止 setup.sh**——降级汇报，与全文既定的 skipped[] 范式一致
# （同「set -e 面治」节的取向：检测本身不是安装的必要步，缺失只影响下游脚本能不能跑）。
# 但「不中止」≠「可选」：yq 与 openspec 是主流程（/g-spec → /g-done）的运行依赖，缺失进
# missing[] 并在 setup.sh 末尾再提示一次（G_DEPS_MISSING），不让它淹没在安装清单上方。
#
# yq 最低版本 4.16.0 = `--front-matter` 选项的支持下限 [spec-review-amendment F5]——
# 低于此版本即便是 mikefarah/yq 也用不了本 change 引入的 frontmatter 读写路径。
_YQ_MIN_VERSION="4.16.0"
# openspec 最低版本 = g-init 铺 project-local schema 的版本门（init.py MIN_SCHEMA_CLI）。
# 验证版本 = CI 契约测试钉死的版本（.github/workflows/mechanical-gates.yml）；二者与 README、
# g-spec 0.1 的安装命令由 hack/tests/test_openspec_cli_contract.py 机械比对，改一处 MUST 同步全部。
_OPENSPEC_MIN_VERSION="1.7.0"
_OPENSPEC_TESTED_VERSION="2.1.0"
G_DEPS_MISSING=""

# 版本号大小比较（"X.Y.Z" 形式，缺位按 0 补）。不用 `sort -V`——那是把判定外包给
# coreutils 的另一种手搓，两行整数比较就能穷举 semver 三段，犯不上多一个工具依赖。
_version_ge() {
  local IFS=.
  local -a v1=($1) v2=($2)
  local i a b
  for i in 0 1 2; do
    a="${v1[i]:-0}"; b="${v2[i]:-0}"
    case "$a" in ''|*[!0-9]*) a=0 ;; esac
    case "$b" in ''|*[!0-9]*) b=0 ;; esac
    if [ "$a" -gt "$b" ]; then return 0; fi
    if [ "$a" -lt "$b" ]; then return 1; fi
  done
  return 0
}

check_dependencies() {
  local _py="${1:-}"
  echo ""
  echo "运行依赖预检："
  local missing=()

  # 复用 setup.sh [T48] 已选择并传入的 Python，这里只报告，不重新选择。
  # install_g 和 retire-hooks 也消费该解释器，候选选择仍留在安装入口。
  if [ -n "$_py" ]; then
    echo "  ✓ python3 ($("$_py" --version 2>&1))"
  else
    echo "  ✗ python3 >= 3.7 — 未找到"
    missing+=("python3>=3.7")
  fi

  # git
  if command -v git >/dev/null 2>&1; then
    echo "  ✓ git ($(git --version 2>&1))"
  else
    echo "  ✗ git — 未找到"
    missing+=("git")
  fi

  # yq（mikefarah/yq，>= 4.16.0）
  if command -v yq >/dev/null 2>&1; then
    local yqv yqnum
    yqv="$(yq --version 2>&1)" || true
    if printf '%s' "$yqv" | grep -q "mikefarah"; then
      yqnum="$(printf '%s' "$yqv" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
      if [ -n "$yqnum" ] && _version_ge "$yqnum" "$_YQ_MIN_VERSION"; then
        echo "  ✓ yq ($yqv)"
      else
        echo "  ⚠ yq 版本过低（${yqv}，需 >= ${_YQ_MIN_VERSION} —— --front-matter 支持下限）"
        echo "    升级：macOS brew upgrade yq | Windows winget upgrade --id MikeFarah.yq | Linux snap refresh yq"
        missing+=("yq>=$_YQ_MIN_VERSION")
      fi
    else
      echo "  ⚠ yq 已安装但不是 mikefarah/yq（可能是 kislyuk/yq，jq 语法不兼容）——请卸载后安装正确版本"
      missing+=("yq(mikefarah)")
    fi
  else
    echo "  ✗ yq — 未找到"
    missing+=("yq")
  fi

  # openspec（主流程必需：/g-spec 起手预检 + /g-done archive；setup.sh 本身不依赖）
  if command -v openspec >/dev/null 2>&1; then
    local osv osnum
    osv="$(openspec --version 2>&1)" || true
    osnum="$(printf '%s' "$osv" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
    if [ -n "$osnum" ] && _version_ge "$osnum" "$_OPENSPEC_MIN_VERSION"; then
      echo "  ✓ openspec ($osv)"
      if [ "$osnum" != "$_OPENSPEC_TESTED_VERSION" ]; then
        echo "    · 本仓 CLI 契约验证版本为 ${_OPENSPEC_TESTED_VERSION}，当前版本未经验证；/g-spec 若报 instructions 载荷不兼容，装回验证版本"
      fi
    else
      echo "  ⚠ openspec 版本过低或不可解析（${osv}，需 >= ${_OPENSPEC_MIN_VERSION}）"
      missing+=("openspec>=$_OPENSPEC_MIN_VERSION")
    fi
  else
    echo "  ✗ openspec — 未找到（主流程必需：/g-spec 起手预检、/g-done archive）"
    missing+=("openspec")
  fi

  # pytest（开发可选，跑测试才需要）
  if [ -n "$_py" ] && "$_py" -m pytest --version >/dev/null 2>&1; then
    echo "  ✓ pytest ($("$_py" -m pytest --version 2>&1))"
  else
    echo "  · pytest — 未找到（跑测试需要：pip install pytest）"
  fi

  if [ ${#missing[@]} -gt 0 ]; then
    G_DEPS_MISSING="${missing[*]}"
    echo ""
    echo "  缺少/不满足必要依赖：${missing[*]}"
    echo "  skills 照常安装；补齐前主流程（/g-spec → /g-done）无法运行，补齐后无需重跑 setup.sh"
    for m in "${missing[@]}"; do
      case "$m" in
        python3*)
          echo "  python3 安装：https://python.org 或系统包管理器（apt/brew/winget 等）"
          ;;
        git)
          echo "  git 安装：https://git-scm.com 或系统包管理器（apt/brew/winget 等）"
          ;;
        yq*)
          echo "  yq 安装／升级："
          echo "    macOS:   brew install yq          （升级：brew upgrade yq）"
          echo "    Windows: winget install --id MikeFarah.yq   （升级：winget upgrade --id MikeFarah.yq）"
          echo "    Linux:   snap install yq          （升级：snap refresh yq）"
          ;;
        openspec*)
          echo "  openspec 安装／升级（需 Node.js >= 22.20.0）：npm install -g @fission-ai/openspec@${_OPENSPEC_TESTED_VERSION}"
          echo "    已在无 CLI 时初始化过的项目，装好后在项目根重跑 g-init 的 init.py update 补铺 project-local schema"
          ;;
      esac
    done
  fi
}
