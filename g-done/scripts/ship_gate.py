#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""g-done 确定性台账：只读，盘面推导下一步。

active 报告只认头部 ship-gate frontmatter：design_approved、code_review、verify。
reviewed_sha 是监视域 manifest 的 SHA-256（64 hex），与 reviewed_manifest 同批互证，
不是 Git commit。设计域监视 proposal/design/specs，进入实现前检查；代码域监视
openspec/ 外的提交内容，代码审与 verify 都检查。脏工作树不作为新鲜度输入。
归档兼容旧 inline verify 锚；坏锚不能回退成 PASS。

tickets.md 首次提交到 HEAD 是完成标签窗口，仅 checkpoint(change:taskN-slug)
提交（兼容旧裸标签）计为完成。复选框只描述验收，不独立授权推进。
计划必须有唯一 R-ID: all 收尾票、完整 Blocked-by 和聚合测试验收。

gate verdict / exit / next：
REFUSE_START / 3 / -：未过设计门或 change 不存在。
RUN_PLAN / 0 / g-implement：缺出票产物。
CONTINUE_IMPL / 0 / g-implement：尚有票缺完成标签，done_tasks 返回已完成票号。
RUN_CODE_REVIEW / 0 / g-code-review：实现完成，缺代码审。
BLOCKED_UPSTREAM / 4 / -：代码审 blocked。
RUN_VERIFY / 0 / g-done：需验证、归档收尾或 merge。
VERIFY_FAIL / 5 / -：新鲜 verify=FAIL。
RERUN_STALE / 0 / 对应步骤：报告陈旧。
STEP_IN_PROGRESS / 0 / 对应步骤：报告结论缺失或 defer 台账未对账。
SHIPPED / 0 / -：归档已并 base 且 verify=PASS；或 HEAD 归档 verify=PASS
并有已提交的 .skip-merge（merge_skipped=true）；或分支约定明确原地完成。
新变更的分支约定保存固定比较基准与合并目标；旧活动变更可诊断进度，但缺约定不能自动合并。
UNKNOWN / 6 / -：坏结构、坏锚或无法可靠判定。
旧 next 名仅用于 JSON 兼容，由 g-done 映射到 g-review spec/code。

旧 metrics 配置和 lens 度量锚不再参与 gate；历史数据仅供 retro 只读汇总。
已知边界：只看已提交代码；设计失鲜窗口在实现结束后关闭；归档终态不重验源码；
同名旧归档、历史改写与旧裸标签混用仍需遵守 change 身份及提交纪律。
"""
# [T74/grill-amendment Q2] 已知不覆盖（登记越权盲区，非正常可达）：
#   「首行 --- 无闭合 × 归档 verify-report 正文独占一行 inline PASS 锚」杂交形态——
#   改判 absent 后 archived_verify_state 会回退 inline 扫到独占行 PASS → 判 pass。
#   但此形态**无 producer 产出**：目标态 producer 写 frontmatter 不写 inline，旧 producer
#   首行恒 '#' 非 '---'。须手工伪造归档才能构造 = 显式越权（git 留痕可审计，adr/0008/0011）。
#   目标态论证：迁移期评估安全锚 producer 契约而非现存语料快照（见 design ADR-4）。
import argparse
import base64
import functools
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from pathlib import Path

# ────────────────────────────── yq(mikefarah) subprocess 薄封装 ──────────────────────────
# [shared-yaml-subset-parser] `parse_ship_gate_frontmatter` 的 YAML **取值**核心委托给外部
# yq 二进制（同 git 的外部二进制先例），MUST NOT `import yaml`（零依赖不变量）。
#
# duplicate-key/tab-indent 精细诊断 yq 给不出（实测：重复键静默取最后值，exit 0；tab 缩进
# 只报笼统 go-yaml 词法错误，无法反解析出 tab-indent 这个分类）——R11 显式要求这两类检测
# 保留原始文本预扫描、在 yq 调用**之前**执行。分工：prescan 管结构诊断（dup-key/tab-indent/
# 顶层 `ship-gate:` 头是否为规范空 map 形），yq 管取值（真 YAML 语义：布尔类型/引号剥离/
# 注释剥离/嵌套结构），见 `parse_ship_gate_frontmatter`。
_yq_bin = None  # 进程内缓存


def _yq(expression, file=None, *, text=None, front_matter=False, in_place=False, default=None):
    """yq(mikefarah) subprocess 薄封装。`file`=路径 或 `text`=字符串（走 stdin），二选一——
    `parse_ship_gate_frontmatter` 的调用方既有从磁盘读（live）也有从 `git show` 取文本
    （归档 dual-read）两种来源，`text` 模式让两者共用同一 yq 调用点，不必先落临时文件。

    [R7/F2] exit≠0 恒 raise（转发 stderr）——「键不存在」（exit 0 + stdout=null，走 `default`）
    与「解析失败」（exit≠0）MUST 是两条不同分支，调用方不得把两者混为一谈、不得吞非零退出。
    [F6] 身份校验：`--version` 输出须含 `mikefarah`，拒 kislyuk/yq（jq 语法不兼容，误调会
    产生词不达意的报错）。
    [F10] `encoding="utf-8", errors="replace"`——Windows 默认 GBK/cp936 会破坏非 ASCII 内容。
    [F3] 多文档防御：stdout 若含一个以上 JSON 值（疑似多文档 YAML）→ raise，不静默只取第一个。
    [R5/F4] `front_matter=True` 时，解出的顶层结构非 dict（且非 null/键缺席，那两种已在
    default 分支短路返回）→ 视为坏块 raise，不静默当作合法标量返回。
    [F11] 已联网核实（mikefarah/yq Windows 已知行为）：`--front-matter` 在 Windows 上每次
    调用都会在 stderr 打一行 `Failed to remove temp file` 噪音（yq 自身的临时文件清理失败，
    不影响正确性）——本函数只信 `returncode`，不检查 stderr 内容。
    """
    global _yq_bin
    if _yq_bin is None:
        yq = shutil.which("yq")
        if not yq:
            raise GateIndeterminate(
                "yq 未安装。安装方式：\n"
                "  macOS:   brew install yq\n"
                "  Windows: winget install --id MikeFarah.yq\n"
                "  Linux:   snap install yq",
                CAUSE_YQ_UNAVAILABLE)
        vr = subprocess.run([yq, "--version"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        if "mikefarah" not in vr.stdout:
            raise GateIndeterminate(
                "检测到的 yq 不是 mikefarah/yq（可能是 kislyuk/yq）。\n"
                "  请卸载后安装正确版本：\n"
                "  macOS:   brew install yq\n"
                "  Windows: winget install --id MikeFarah.yq\n"
                "  Linux:   snap install yq",
                CAUSE_YQ_UNAVAILABLE)
        _yq_bin = yq
    cmd = [_yq_bin]
    if front_matter:
        cmd += [f"--front-matter={'process' if in_place else 'extract'}"]
    if in_place:
        cmd.append("-i")
    else:
        cmd += ["-o", "json"]
    cmd.append(expression)
    stdin_input = None
    if text is not None:
        cmd.append("-")
        stdin_input = text
    else:
        cmd.append(str(file))
    r = subprocess.run(cmd, capture_output=True, text=True, input=stdin_input,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"yq failed: {r.stderr.strip()}")
    if in_place:
        return None
    raw = r.stdout.strip()
    if not raw or raw == "null":
        return default
    decoder = json.JSONDecoder()
    parsed, idx = decoder.raw_decode(raw)
    if raw[idx:].strip():
        # [F3] 多文档 YAML → yq 逐文档各吐一个 JSON 值拼接；json.loads 前若不检测单值，
        # 会静默用第一个文档的值掩盖后续文档的存在（已联网核实：mikefarah/yq issue 讨论）。
        raise RuntimeError(f"yq 输出多个 JSON 值（疑似多文档 YAML，不支持）: {raw[:200]!r}")
    if front_matter and not isinstance(parsed, dict):
        raise RuntimeError(f"yq front-matter 顶层结构非 dict（坏块）: {raw!r}")
    return parsed


# [T75] design/code-review inline 锚常量已随 Task6 live inline 读半场退役而删除；
# 仅 verify 锚保留——archived_verify_state 的归档 dual-read 兜底旧 inline 现役唯一在用。
ANCHOR_VERIFY_PASS = "<!-- ship-gate: verify=PASS -->"
ANCHOR_VERIFY_FAIL = "<!-- ship-gate: verify=FAIL -->"
ALL_ANCHORS = [ANCHOR_VERIFY_PASS, ANCHOR_VERIFY_FAIL]

EXIT_OK, EXIT_REFUSE, EXIT_BLOCKED, EXIT_VFAIL, EXIT_UNKNOWN = 0, 3, 4, 5, 6


# [harden-gate-git-layer Task1 · ADR-1/3.5] 判定不能的结构化信号。
# 复用仓内 `_fail_closed_on_bad` 的 (cause, category) 二元组模式：category 供 main() 机械分派，
# cause 供人读。**唯一映射点在 main()** —— 抛出方 MUST NOT 自行 emit/exit，否则退出码映射
# 会散成多处、各处措辞漂移（design.md「五类原因各给可行动诊断」的前提是单一映射点）。
CAUSE_GIT_UNAVAILABLE = "git-unavailable"     # git 不在 PATH / 不可执行（Task2 接入）
CAUSE_GIT_TIMEOUT = "git-timeout"             # 调用超时（Task2 接入）
CAUSE_ANCHOR_MISSING = "anchor-missing"       # reviewed_sha/reviewed_manifest 字段缺失（含报告读不到）
CAUSE_ANCHOR_INVALID = "anchor-invalid"       # 〔sweep-pool-debt D3/D4〕reviewed_sha 语法非法 /
                                               # 非 64-hex（旧 40-hex 格式锚）/ 与 reviewed_manifest 不互证
CAUSE_READ_FAILED = "read-failed"             # 仓损坏 / 权限（Task3/4 接入）
CAUSE_YQ_UNAVAILABLE = "yq-unavailable"       # yq 未安装 / 检测到非 mikefarah/yq（身份校验失败）


class GateIndeterminate(Exception):
    """判定不能 → main() 统一映射 UNKNOWN(6)。

    cause: 人读原因串（含具体字段值 / 路径，供撞门者直接行动）
    category: 上列 CAUSE_* 之一，main() 按它选可行动诊断（MUST NOT 用一句「git 调用失败」打天下）
    """

    def __init__(self, cause, category):
        super().__init__(f"[{category}] {cause}")
        self.cause = cause
        self.category = category


# [harden-gate-git-layer Task2 · ADR-6 · tasks 3.4] `_GIT_HARDEN` 的职责 =
# **中和一切能改变判定输入的外部可控态**，而不只是「中和 core.quotePath」。外部可控态有两个面，
# 两面都必须扫，缺一即判定输入仍可被外部翻转：
#   **config 面**（本常量，`-c` 注入）：
#   ① -c core.quotePath=false：git 默认把非 ASCII 路径 C-quote（八进制+首尾引号），
#      裸 f.startswith(base)/startswith("openspec/") 对中文文件名路径全失配 → design 域假鲜
#      （拍板后偷改中文名 spec 静默放行=假✅）/ code 域假陈旧。本项目中文文件名密集，realistic。
#   ② errors="replace"：报告内容/subject/文件名非 UTF-8 时 strict 解码抛 UnicodeDecodeError
#      → 退出码 1 逸出契约集 {0,3,4,5,6}；与头注释「非 UTF-8 以 replace 解码」及本地 read_text
#      路径的既有加固对齐（archived verify 走 git show 是首个用 subprocess 读报告内容的路径）。
#   **环境面**（`_git_env()`，denylist 清理）：见该函数注释。
# MUST NOT 以「我们碰巧没用到 diff / pathspec」当安全论据——那是拿现状当保证（基准 3）。
_GIT_HARDEN = ("-c", "core.quotePath=false")

# [harden-gate-git-layer Task2 · ADR-5 · tasks 3.2] 三个 helper 统一上界。
# 判据来源 = 仓内既有先例 `g-issues/scripts/gear_issues_core/__init__.py::repo_root` 的 `git_timeout = 30`：
# 这些都是**纯本地元数据查询**（正常毫秒级），30 秒是**文件系统卡死 / 网络文件系统挂起**的
# 判定线，**不是性能预算**。MUST NOT 按「最慢的仓要多久」来调大——那会把它误当性能预算，
# 从而让真正的挂起拖到无限久（而 gate 是同步阻塞在链序里的）。
# 聚合上界的数量级：design 域一次 decide() 约 4 次 git 调用（与提交数无关）
# ⇒ 最坏情形（文件系统级挂起）约 2 分钟落进 UNKNOWN(6)。**有界 ≠ 短**，此处写明免各自心算。
GIT_TIMEOUT_SECONDS = 30


def _git_env(user_config=False):
    """子进程 env：复制当前环境 → **剔除 `GIT_` 前缀键** → **本进程回填两个禁读键**。

    [harden-gate-git-layer Task2 · ADR-6 · tasks 3.3] MUST 用 denylist，**MUST NOT 用 allowlist**
    （只显式构造 PATH/HOME 等几个键）——allowlist 在 Windows 会漏 `SYSTEMROOT`/`COMSPEC` 等
    `CreateProcess` 依赖变量，导致子进程启动本身失败；这与本仓已踩过的跨平台坑同类：
    **本地 macOS 测不出，只有真实 Windows runner 才暴露**。

    剔除面 = 全部 `GIT_*`，非只剔已知的几个（`GIT_ICASE_PATHSPECS` / `GIT_DIR` / `GIT_WORK_TREE`…）：
    已知集是会增长的，逐个点名等于承诺「git 不再新增能改变输出的环境变量」——那是拿现状当保证。

    [fix1 F1] **剔 `GIT_*` 不等于封死环境面**：global/system gitconfig 的**位置**由
    `HOME` / `XDG_CONFIG_HOME` 决定，而这两个键非 `GIT_` 前缀、按 denylist 必须透传
    ⇒ 外部仍能经一份 global gitconfig 改判定输入。已实测：global 置
    `i18n.logOutputEncoding=GBK` 后 `run_git("log", "--format=%s")` 的 subject 由
    `主题中文` 变成 `����`，而该 subject 正是 `done_task_ids` 的判定输入。
    ∴ 在 denylist **之后**回填 `GIT_CONFIG_GLOBAL` / `GIT_CONFIG_SYSTEM` = `/dev/null`：
    **本进程注入 ≠ 外部可控**，不破坏 denylist 口径（先剔干净，再由我们自己写死）。
      · 空设备是 git **官方文档给的**跳过写法（git(1)：「Can be set to /dev/null to
        skip reading configuration files of the respective level.」），非平台巧合。
        取 `os.devnull` 而非字面量 `"/dev/null"`：Windows 上它是原生 `nul`（Git for
        Windows 的 compat 层两种写法都认，用平台原生值免赌 compat 映射）。
      · MUST NOT 改用 `-c i18n.logOutputEncoding=UTF-8 -c log.showSignature=false` 之类的
        **逐项覆盖**：那是点名已知 knob，与本函数剔除面选全前缀的理由同构地错（config 键集
        只会增长，点名 = 承诺「不再新增能改变输出的配置项」）。整片禁读才是面治。
      · **未封 repo-local `.git/config`——理由是能力等价，不是「有别的东西守着」。**
        能写 `.git/config` 的人，同样能写 `.git/objects` / `.git/refs`，或直接
        `git commit --amend` 伪造 subject——所需权限 ≤ 已足以击穿本 gate 的权限，
        ∴ 被判仓按构造就在信任边界内，封它无净收益（且 env 层无干净关法）。
        🔴 **此项无机械覆盖，是登记在案的残余**：`.git/config` 置
        `i18n.logOutputEncoding=GBK` 确实能翻转判定输入（实测 subject 变乱码）。
        MUST NOT 声称它被 `test_verdict_is_identical_under_polluted_git_env` 守住——
        那条只污染 `diff.ignoreSubmodules` 这一个良性 knob，覆盖不到本面。

    [fix1 M1] **与先例的差异登记**：`g-issues/scripts/gear_issues_core/__init__.py::repo_root`
    只剔 discovery 类（`GIT_DIR`/`GIT_WORK_TREE`/`GIT_CONFIG_*`…）并**刻意保留执行类**
    （`GIT_EXEC_PATH` 等）；本函数剔全前缀，故连 `GIT_EXEC_PATH` 一并剔掉。
    理由：本文件只调 builtin 子命令（`log`/`rev-parse`/`ls-tree`/`show`/`cat-file`），
    不依赖外部 `git-*` 可执行文件的查找路径，∴ 保留执行类无收益、而枚举「哪些算执行类」
    要长期跟 git 版本（正是本函数拒绝的那种承诺）。**代价**（显式登记，非未知）：日后若
    引入非 builtin 的 git 子命令，剔掉 `GIT_EXEC_PATH` 可能令 git 找不到它而 rc≠0，
    `run_git` 返 `""` ⇒ **静默降级而非 UNKNOWN**。届时 MUST 改为按 buglist 口径分类剔除，
    而不是给这里打一个特例补丁。

    [B37] `user_config=True` 只供 `_user_safe_directories` 读用户声明的 `safe.directory` 用：
    照样剔 `GIT_*`，但不回填两个禁读键。
    """
    env = os.environ.copy()
    for key in [k for k in env if k.startswith("GIT_")]:
        del env[key]
    if not user_config:
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_SYSTEM"] = os.devnull
    return env


# [B37] 禁读 global/system 会连带吞掉用户在这两级声明的 `safe.directory` ⇒ 属主不是当前账号
# 的仓（多账号共用目录）被 git 判 dubious ownership，全部 git 调用返回空、写锚与 gate 双双失效。
# 透传口径：**只取 safe.directory 一个键、只认 system/global 两级**，以 `-c` 注入（命令行级
# 属 git 的受保护配置，safe.directory 在此生效）。其余 config 仍整片禁读，上文加固意图不变。
# 仓库级（local/worktree）值 MUST 丢弃：git 自己不认它（防仓库给自己开后门），透传它就等于
# 把 `.git/config` 提升成命令行级、替仓库开了这个后门。信不信任某个仓仍由用户自己的配置决定。
_SAFE_DIRECTORY_SCOPES = ("system", "global")


@functools.lru_cache(maxsize=None)
def _user_safe_directories():
    r = _git_run(Path.cwd(), ("config", "--show-scope", "--get-all", "safe.directory"),
                 text=True, user_config=True)
    if r.returncode != 0:   # 1 = 未声明该键
        return ()
    values = []
    for line in r.stdout.splitlines():
        scope, _, value = line.partition("\t")
        if scope in _SAFE_DIRECTORY_SCOPES:
            values.append(value)
    return tuple(values)


def _git_run(root, args, text, user_config=False):
    """三个 helper 唯一的 subprocess 出口：统一 timeout + env 清理 + 环境级失败映射。

    [harden-gate-git-layer Task2 · tasks 3.1/3.2/3.3] 单出口而非三处复制——三份拷贝必然漂移
    （历史上 `_GIT_HARDEN` 就是靠单点注入才没漏），且「新增一个 git 调用点忘了加固」这条
    失效模式在单出口下不存在。三个 helper 的语义差异（text/strip vs 原始字节）留在各自壳里。

    环境级失败 MUST 收敛进退出码契约集 `{0,3,4,5,6}`：裸 `OSError`（git 不在 PATH /
    不可执行 / 权限不足）与 `TimeoutExpired`（文件系统挂起）逸出后是 Python 默认退出码 1，
    对 `/g-ship` 链序而言是**契约外**取值 ⇒ 无处置路径。二者各自 category 不同，
    因为补救动作完全不同（装 git vs 查磁盘），MUST NOT 合并成一句「git 调用失败」。
    """
    safe = () if user_config else tuple(
        x for d in _user_safe_directories() for x in ("-c", f"safe.directory={d}"))
    cmd = ["git", "-C", str(root), *safe, *_GIT_HARDEN, *args]
    kwargs = {"capture_output": True, "timeout": GIT_TIMEOUT_SECONDS,
              "env": _git_env(user_config=user_config)}
    if text:
        kwargs["text"] = True
        kwargs["encoding"] = "utf-8"
        kwargs["errors"] = "replace"
    shown = " ".join(str(x) for x in cmd)
    try:
        return subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise GateIndeterminate(
            f"git 调用超过 {GIT_TIMEOUT_SECONDS}s 未返回：{shown}", CAUSE_GIT_TIMEOUT)
    except OSError as exc:
        raise GateIndeterminate(
            f"git 子进程无法启动（{type(exc).__name__}: {exc}）：{shown}",
            CAUSE_GIT_UNAVAILABLE)


def run_git(root, *args):
    r = _git_run(root, args, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def run_git_rc(root, *args):
    # [spec-review-amendment H3] 返回码可见版：run_git 把 git 错误与「路径不在树/空输出」
    # 都折叠成空串，base_ref 的 None 性据此驱动「base 不存在→UNKNOWN」vs「归档缺→REFUSE」分岔。
    r = _git_run(root, args, text=True)
    return r.returncode, r.stdout.strip()


def default_branch(root):
    """所有步骤共用的默认分支名；只接受分支引用，不把 tag 当 base。"""
    ref = run_git(root, "symbolic-ref", "refs/remotes/origin/HEAD")
    if ref.startswith("refs/remotes/origin/"):
        return ref[len("refs/remotes/origin/"):]
    for ref, name in (("refs/remotes/origin/master", "master"),
                      ("refs/heads/main", "main"), ("refs/heads/master", "master")):
        rc, _ = run_git_rc(root, "rev-parse", "--verify", ref)
        if rc == 0:
            return name
    return None


def base_ref(root):
    name = default_branch(root)
    if name is None:
        return None
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        rc, _ = run_git_rc(root, "rev-parse", "--verify", ref)
        if rc == 0:
            return ref
    return None


def archived_dirs_in_tree(root, ref, change):
    # [spec-review-amendment H2/H5] 纯 git 域发现（非文件系统 glob，工作树无关、忽略未跟踪
    # 垃圾目录）：列 ref 树里 archive/ 的直接子项，以 re.escape(change) 套日期前缀 fullmatch
    # （H5 注入防御：--change 的 * ? [] 不当 glob 元字符）。返回匹配的 archive 目录名 set。
    rc, out = run_git_rc(root, "ls-tree", "--name-only", ref,
                         "openspec/changes/archive/")
    if rc != 0 or not out:
        return set()
    pat = re.compile(r"\d{4}-\d\d-\d\d-" + re.escape(change) + r"$")
    return {line.rsplit("/", 1)[-1] for line in out.splitlines()
            if pat.fullmatch(line.rsplit("/", 1)[-1])}


def uncommitted_archive_dirs(root, change):
    """〔A2〕工作树里有、HEAD 树里没有的 `archive/<日期>-{change}`（= 已 `openspec archive`、尚未提交）。

    `openspec archive` 只在文件系统里搬目录、不提交：此刻 active 目录已从工作树消失，HEAD 树里
    又还没有归档目录——纯 git 域视角下 change「不存在」，若不识别这一窗口，「每步前后跑 gate」
    会把正常收尾流程停在 archive 与 commit 之间。只认本 change 在 HEAD 树里仍是 active 的情形
    （归档前已提交过），未跟踪的同名垃圾目录不会被当成本窗口。
    """
    adir = root / "openspec" / "changes" / "archive"
    if not adir.is_dir():
        return []
    rc, _ = run_git_rc(root, "cat-file", "-e", f"HEAD:openspec/changes/{change}")
    if rc != 0:
        return []
    pat = re.compile(r"\d{4}-\d\d-\d\d-" + re.escape(change) + r"$")
    committed = archived_dirs_in_tree(root, "HEAD", change)
    return sorted(d.name for d in adir.iterdir()
                  if d.is_dir() and pat.fullmatch(d.name) and d.name not in committed)


def archived_verify_state(root, ref, archive_dir):
    # [spec-review-amendment H1/BR-2] SHIPPED 前追读归档目录内 verify-report.md 的 verify 锚
    # （从 ref 树）——不把「归档⟹已验」当无条件蕴含（手工空壳归档目录不得假 SHIPPED）。
    # [impl-review-fix] tri-state（CV-1/HRTG-c2 三声）：D3 短路须与 active 侧冲突锚判 UNKNOWN
    # 同等互斥——PASS+FAIL 并存 = 'conflict'（→UNKNOWN），非只查 PASS in。
    rc, out = run_git_rc(root, "show",
                         f"{ref}:openspec/changes/archive/{archive_dir}/verify-report.md")
    if rc != 0:
        return "none"
    # [mlh-p5 Task3 D4/G2] frontmatter 优先（新归档），共用同一严格 helper（防漂移）——
    # 与 live 侧的区别：live 坏→UNKNOWN(6) 停；归档坏→fail-safe 'none'（不 emit、不 exit，
    # 归档不可变、无人可修，只能保守判无 verify pass，不回退 inline 掩盖假 SHIPPED）。
    state, err = parse_ship_gate_frontmatter(out)
    if err is not None:
        return "none"                        # 坏 frontmatter → fail-safe（不回退 inline 掩盖）
    if "verify" in state:                     # Q4：frontmatter 有效即采信，不再交叉扫 inline
        return "pass" if state["verify"] == "PASS" else "none"
    # absent（迁移前旧归档，无 ship-gate frontmatter 键）→ 回退旧 inline 读半场，永久保留
    hits, unbalanced = _line_scoped_hits(out, [ANCHOR_VERIFY_PASS, ANCHOR_VERIFY_FAIL])  # [ADR-4] 行级，非子串
    if unbalanced:   # [ADR-5] 保守：未闭合 fence 不判 SHIPPED
        return "none"
    has_pass, has_fail = ANCHOR_VERIFY_PASS in hits, ANCHOR_VERIFY_FAIL in hits
    if has_pass and has_fail:
        return "conflict"
    return "pass" if has_pass else "none"


# [harden-gate-git-layer Task1 · tasks 1.9] `report_last_sha`（`git log -1 -- <report>` 反推锚）
# 已退役：任何后续提交顺带碰一下报告文件（空行 / CI reformat / 措辞回填）都会把锚无声前移，
# 埋掉锚前的未审改动，且该提交无需改动任何结论字段（design.md 缺陷 9）。
# 取代者 = 下方 `read_reviewed_sha`：producer 落结论时把「被批准的盘面」录进 frontmatter，
# reader 只读不推。**MUST NOT** 在锚缺失/非法时回退本函数或任何反推式锚（Compliance 硬约束）。


# [impl-review-fix F3] 报告文件内容读取的**单一出口**：`is_file()` 已确认存在之后再读，
# 中间仍有两个外部可控失败面——① 权限不足（PermissionError）② TOCTOU（is_file() 与
# read_text() 之间文件被删）——两者都是裸 `OSError` 子类，不捕获则逸出成 Python 默认退出码 1，
# 落在契约集 `{0,3,4,5,6}` 之外（与 Task2 已修的 `UnicodeEncodeError` 逸出同类；`errors="replace"`
# 已堵住解码面，但没堵读取本身的面）。三个报告读点（`read_reviewed_sha` / `live_ship_gate_state` /
# `_unclosed_frontmatter_hint`）面治式统一走本出口，防「新增一个报告读点忘了包」。
# MUST NOT 用 `except Exception`：那会把编程错误一并吞成 UNKNOWN（同 `is_stale` 里同款约束）。
def _read_report_text(path, label):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateIndeterminate(
            f"{label} 读取失败（{type(exc).__name__}: {exc}）——仓损坏 / 权限不足 / "
            "文件在存在性确认后被删（TOCTOU）", CAUSE_READ_FAILED)


def _read_anchor(root, rel):
    """读报告 frontmatter 的内容锚（`reviewed_sha` + `reviewed_manifest`），互证后返回
    `(sha64, manifest_bytes)`。〔sweep-pool-debt D3/D4：内容指纹单一源，取代 commit-sha 把手〕

    两层校验显式分层：
      - **语法级**在纯文本函数 `parse_ship_gate_frontmatter`（`FIELD_VALIDATORS`）——
        `reviewed_sha` 40 或 64 位小写 hex（DT-1 校验分层，兼容归档旧 40-hex）、
        `reviewed_manifest` 单行 base64。live 读与归档 git-show 文本读共用同一核心。
      - **语义级**在本函数（live 读点专属，归档读点 `archived_verify_state` 不调本函数、
        不做本级校验——归档只消费 `verify` 结论）：`reviewed_sha` MUST 恰为 64 位（旧
        40-hex 格式锚在 live 侧判非法，需重跑写锚脚本）；`reviewed_manifest` MUST 可
        base64 解码；解码后字节流的 sha256 MUST 等于 `reviewed_sha`（双字段密码学互锁）。

    缺失 / 非法 / 不互证均抛 `GateIndeterminate`（→ main() 映射 UNKNOWN(6)），category
    分两类：字段缺失 → `CAUSE_ANCHOR_MISSING`；格式/互证失败 → `CAUSE_ANCHOR_INVALID`。
    **MUST NOT** 在任一形态下回退反推式锚，**MUST NOT** 把锚值作 git ref 解析。
    """
    path = root / rel
    if not path.is_file():
        raise GateIndeterminate(
            f"报告 {rel} 读不到（文件不存在），无从取内容锚", CAUSE_ANCHOR_MISSING)
    text = _read_report_text(path, f"报告 {rel}")
    state, err = parse_ship_gate_frontmatter(text)
    if err is not None:
        field, cat = err
        # 语法级校验不过（含 reviewed_sha/reviewed_manifest 自身 out-of-domain，也含同块内
        # 其它字段的坏形态——坏块整体不可信，MUST NOT 从坏块里挑一个字段出来采信）。
        raise GateIndeterminate(
            f"报告 {rel} 的 ship-gate frontmatter 坏（字段={field} 类别={cat}）",
            CAUSE_ANCHOR_INVALID)
    missing = [k for k in ("reviewed_sha", "reviewed_manifest") if k not in state]
    if missing:
        raise GateIndeterminate(
            f"报告 {rel} 的 ship-gate frontmatter 缺 {'/'.join(missing)} 字段",
            CAUSE_ANCHOR_MISSING)
    sha = state["reviewed_sha"]
    if len(sha) != 64:
        raise GateIndeterminate(
            f"报告 {rel} 的 reviewed_sha={sha} 非 64 位（旧 40-hex commit-OID 格式锚）"
            "——请重跑写锚脚本（anchor_writeback.py）补齐内容锚", CAUSE_ANCHOR_INVALID)
    try:
        manifest_bytes = base64.b64decode(state["reviewed_manifest"], validate=True)
    except Exception:
        raise GateIndeterminate(
            f"报告 {rel} 的 reviewed_manifest 不是合法 base64", CAUSE_ANCHOR_INVALID)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    if digest != sha:
        raise GateIndeterminate(
            f"报告 {rel} 的 reviewed_sha 与 reviewed_manifest 不互证"
            "（manifest 的 sha256 ≠ reviewed_sha）", CAUSE_ANCHOR_INVALID)
    return sha, manifest_bytes


def read_reviewed_sha(root, rel):
    """`_read_anchor` 的薄封装：只取 sha（供诊断/emit 展示，打印零推断成本）。"""
    return _read_anchor(root, rel)[0]


def _manifest_bytes_from_entries(entries):
    """`{path_bytes: (mode, type, oid)}` → 规范字节流（按原始 path 字节序排序，逐条
    `mode SP type SP oid TAB path`，记录间以 `\\0`（NUL）连接）。〔sweep-pool-debt D3/D4〕
    〔impl-review-fix C1〕

    字节保真：mode/type/oid/path 均取自 `ls-tree -z` 的原始字节，不解码、不归一化——
    与 write 侧（`anchor_writeback.py`）共用本函数，故双方对同一盘面恒得字节相同的
    manifest（round-trip 无损，含 Tab/换行/非 UTF-8 路径）。

    〔impl-review-fix C1〕**记录分隔符 MUST 是 `\\0`，MUST NOT 是 `\\n`**：git 路径本身
    可以合法含 `\\n`（`\\t` 亦可），若仍以 `\\n` 分隔记录，一个含 `\\n` 的路径会与「下一条
    真实记录」的字面文本在字节层面不可分辨——实测 `{"a\\n100644 blob <oid>\\tc": …}`（单路径，
    路径本身含换行）与 `{"a": …, "c": …}`（两条独立路径）产出完全相同的 manifest 字节与
    digest，构成碰撞（design DT-2「字节保真、MUST NOT 依赖会被路径内容混淆的分隔符」实质
    要求的正是「无歧义」，`\\n` 不满足）。`\\0` 是无歧义选择：git 路径按 `ls-tree -z` 的
    设计前提本身就不能含 NUL（`-z` 正是靠 NUL 做记录终止符），故用它做本函数的记录分隔符
    不会与任何合法路径字节冲突。
    """
    lines = []
    for path in sorted(entries.keys()):
        mode, typ, oid = entries[path]
        lines.append(mode + b" " + typ + b" " + oid + b"\t" + path)
    return b"\0".join(lines)


def fingerprint_entries(entries):
    """`{path_bytes: (mode, type, oid)}` → `(manifest_bytes, sha256_hex)`。

    单一源：`is_stale`（HEAD 侧重算）与 `anchor_writeback.py`（producer 写锚）都调本函数，
    物理同源杜绝两端口径漂移（design.md「锚的计算逻辑单一源」）。
    """
    mb = _manifest_bytes_from_entries(entries)
    return mb, hashlib.sha256(mb).hexdigest()


def _manifest_entries_from_bytes(manifest_bytes):
    """`fingerprint_entries` 的逆运算之一半：解析规范字节流回 `{path: (mode,type,oid)}`，
    仅供诊断（`guard_design_freshness` 的差异路径点名）使用，不参与等值判定本身
    （等值判定只走 digest，见 DT-2）。空输入 → 空字典。

    〔impl-review-fix C1〕记录分隔符与 `_manifest_bytes_from_entries` 同步改为 `\\0`
    （原 `\\n` 分隔在路径含换行时会与生产侧构成 C1 碰撞，见该函数注释）。
    """
    if not manifest_bytes:
        return {}
    entries = {}
    for line in manifest_bytes.split(b"\0"):
        meta, sep, path = line.partition(b"\t")
        if not sep:
            continue
        entries[path] = tuple(meta.split(b" "))
    return entries


DESIGN_WATCHED_NAMES = ("proposal.md", "design.md")   # 〔sweep-pool-debt D2〕tasks.md 移出监视集


def run_git_bytes(root, *args):
    """保真读取：返回 (returncode, stdout **原始字节**)。

    [fix-design-gate-freshness-proxy Task1 · tasks 1.1d] MUST NOT 复用 run_git/run_git_rc——
    那条路径 text=True + errors="replace" + .strip()，四者各自可造假等值：
    吞首尾空白、吞末尾换行、CRLF↔LF 不可分辨、非 UTF-8 字节被替换成 U+FFFD 后两版趋同。
    本函数只做 subprocess 原样取字节，解码与归一化留给调用方按判据自行决定。

    [harden-gate-git-layer Task2] 「MUST NOT 复用 run_git/run_git_rc」约束的是**文本层语义**
    （text/errors/strip 四者各自可造假等值），不是 subprocess 调用本身：三者共用 `_git_run`
    取 timeout + env 清理 + 环境级失败映射，本函数仍走 text=False 拿原始字节，语义无损。
    """
    r = _git_run(root, args, text=False)
    return r.returncode, r.stdout


DESIGN_WATCHED_SUBTREE = "specs/"      # 监视集里唯一的子树（其余三项是固定文件名）


def change_base(change):
    """change 目录前缀单一源。

    [harden-gate-git-layer Task4 fix] 判定本体（`is_stale`）与诊断
    （`guard_design_freshness`）都要拼这个前缀。散成两份字面量 ⇒ 目录布局若变，
    诊断命令会静默指向错路径而判定仍对（Standards 轴点穿的漂移面）。此处收单一源。
    """
    return f"openspec/changes/{change}/"


def design_pathspecs(base):
    """design 域监视集的 pathspec 列表（供 `ls-tree -- <pathspec>...`）。

    [harden-gate-git-layer Task3 · tasks 2.1；sweep-pool-debt D2] 单一源：监视集成员判据只此
    一处。`tasks.md` **不在其中**（D2：移出监视集，纯勾选框翻转豁免层随之整体退役）。
    """
    return [base + n for n in DESIGN_WATCHED_NAMES] + [base + DESIGN_WATCHED_SUBTREE]


def ls_tree_map(root, ref, pathspecs=(), recursive=True):
    """`git ls-tree [-r] -z <ref> -- <pathspecs>` → `{path_bytes: (mode, type, oid)}`。

    [harden-gate-git-layer Task3 · ADR-2 · tasks 2.1/2.1b/2.4] 判据本体的取数口径。两域共用:
      - **design 域**（`recursive=True` + 监视集 pathspecs）：递归展开到每个 blob。
      - **code 域**〔Task5 · tasks 2.3〕（`recursive=False` + 无 pathspecs）：取**仓库顶层
        条目**的浅层快照。tree 条目 oid 递归摘要整棵子树 ⇒ 深层源码改动经其顶层 tree oid
        反映，无需 `-r`。调用方在 Python 侧按条目名排除 `openspec` 后求等值，**MUST NOT**
        用负向 pathspec `':!openspec'`（继承 `GIT_ICASE_PATHSPECS`，已实测证伪）。

    **`-z` MUST NOT 省略**：它不只是换分隔符——**它同时关闭 git 默认的路径 C-quote**，
    而 C-quote 正是本 change 缺陷 6（控制字符 / 非 ASCII 路径被弄花后逃出监视集）的成因。
    省掉 `-z` ⇒ 新代码路径原样踩回该缺陷。

    **解析口径**（`ls-tree -z` 的输出格式有界、良定义，∴ 可正确手写解析，不撞基准 5）：
    按 `\\0` 切记录，每条记录按**首个 `\\t`** 切分为 `<mode> <type> <oid>` 与 path；
    **path 部分保持原始字节，不解码、不反转义**（解码会让不同字节序列在 U+FFFD 处趋同）。

    **rc≠0 = 真读失败** ⇒ `GateIndeterminate`（仓损坏 / 权限 / ref 不可达）。
    **rc=0 + 某路径不在结果里 = 合法的「缺失」信号**，由调用方按「映射不等 ⇒ stale」处理，
    **MUST NOT** 混作读取失败——二者是不同的事，前者可判（判 stale），后者不可判。
    """
    flags = ("-r", "-z") if recursive else ("-z",)
    rc, out = run_git_bytes(root, "ls-tree", *flags, ref, "--", *pathspecs)
    if rc != 0:
        raise GateIndeterminate(
            f"git ls-tree 读 {ref} 的监视集失败（rc={rc}）——仓损坏 / 权限 / ref 不可达",
            CAUSE_READ_FAILED)
    entries = {}
    for record in out.split(b"\0"):
        if not record:
            continue                       # 末尾 NUL 切出的空 token
        meta, sep, path = record.partition(b"\t")
        fields = meta.split()
        if not sep or len(fields) != 3:
            # 协议外形态 ⇒ 看不清 ⇒ 不可判（MUST NOT 当空集：空集会与另一侧比出假等值）
            raise GateIndeterminate(
                f"git ls-tree 输出形态不可解析（ref={ref}）", CAUSE_READ_FAILED)
        entries[path] = tuple(fields)
    return entries


# [sweep-pool-debt] `read_blob_bytes`（取单文件 blob 原始字节，原供 tasks.md 勾选框豁免层
# 的内容读取用）已随该豁免层整体退役而删除——is_stale 不再需要读取任何单文件内容，等值
# 判定只走 manifest digest 比较（DT-2）。`archived_verify_state` 的 `git show` 归档读路径
# 不依赖本函数，不受影响。


# ────────────────────────────── fenced code block 围栏识别（单一源） ──────────────────────────
# [fix1 Important-1；sweep-pool-debt 收窄为两个消费点] 本仓 fence 追踪点（_line_scoped_hits /
# _parse_plan——`_normalize_checkbox_lines` 已随 tasks.md 勾选框豁免层整体退役）**全部**
# 经由下面这一组函数 + FenceTracker 判定围栏，MUST NOT 再各自
# 手抄 `line.lstrip().startswith("```")`——旧手抄口径只认 ``` ⇒ `~~~` 块内的实质改动被当成
# 「块外普通行」，在归档锚读侧是假 SHIPPED。
#
# 口径 = CommonMark fenced code block 的**有界**词法（数得完，故可手写；见 CLAUDE.md 基准 5）：
#   开启符：行首（去 ASCII 空白后）连续 ≥3 个同种字符，`` ` `` 或 `~`；
#   闭合符：与开启符**同种**、长度 **≥** 开启符长度、其后只余空白（故 ```` ``` ```` 关不掉
#           `~~~`，三 backtick 也关不掉四 backtick 开的块）；
#   info string（如 ```python）只出现在开启行，不影响识别。
# MUST NOT 在此之上再解析 markdown 的其它结构（表格 / 嵌套列表 / 引用块）——那是无界语法面。
_ASCII_WS = " \t\v\f\r\n"
_FENCE_CHARS = ("`", "~")


def fence_delim(line):
    """一行 str → 围栏符 (char, count, tail) 或 None（不是围栏形状）。

    tail = 围栏字符游程之后的剩余内容（判闭合时须 strip 后为空）。
    """
    s = line.lstrip(_ASCII_WS)
    if not s or s[0] not in _FENCE_CHARS:
        return None
    ch = s[0]
    n = len(s) - len(s.lstrip(ch))
    if n < 3:
        return None
    return ch, n, s[n:]


def fence_delim_bytes(line):
    """一行 bytes → 同 `fence_delim`。**单一源就是 `fence_delim`**——本函数只做形态转换。

    latin-1 是字节保序映射：任意字节都能解码、且 ASCII 区语义不变 ⇒ 转换零信息损失，
    两个形态不可能口径分叉（不是手抄副本，是同一份实现的两个入口）。
    """
    return fence_delim(line.decode("latin-1"))


class FenceTracker:
    """逐行喂入的围栏状态机。`inside` = 当前行是否落在 fenced code block 内部。

    `feed(line)` 返回该行是否**是围栏行本身**（开启或闭合）；围栏行既不在块内也不是普通内容，
    各调用点按自己的语义决定保留还是丢弃。EOF 时 `inside` 为真 = 围栏未闭合（调用方保守）。
    """

    def __init__(self):
        self.open = None                   # None=块外；(char, count)=块内，记开启符

    @property
    def inside(self):
        return self.open is not None

    def feed(self, line, is_bytes=False):
        d = fence_delim_bytes(line) if is_bytes else fence_delim(line)
        if d is None:
            return False
        ch, n, tail = d
        if self.open is None:
            self.open = (ch, n)            # 开启：任意 info string 均可
            return True
        och, on = self.open
        if ch == och and n >= on and not tail.strip():
            self.open = None               # 闭合：同种 + 不短于开启符 + 尾部只余空白
            return True
        return False                       # 块内出现的异种/过短围栏形状 ⇒ 只是普通内容行


# ── HTML 注释块（`<!--` … `-->`）追踪 ────────────────────────────────────────
# 〔sweep-pool-debt〕本类**不是** tasks.md 勾选框豁免层的私有件——它是与 `FenceTracker` 同族的
# 通用词法状态机，仓内**跨子系统共享单一源**（`hack/tests/test_decision_memo_gate.py` 复用它
# 判定 decision-memo.md 的 ATX 标题是否落在 HTML 注释块内，与本文件的失鲜判定无关）。
# 勾选框豁免层退役时 MUST NOT 连带删除本类——那会击穿另一个子系统的单一源引用。
# 该词法**有界**（两个固定 token 配对，无嵌套——CommonMark/HTML 里 `<!--` 不嵌套），故可手写。
class HtmlCommentTracker:
    """逐行喂入的 HTML 注释块状态机。`feed` 返回**该行行首**是否已落在注释内部。

    行首锚定的调用方只关心行首状态，故 feed 的返回值即调用点所需的全部信息。
    """

    def __init__(self):
        self.open = False

    def feed(self, line, is_bytes=False):
        start_inside = self.open
        o, c = (b"<!--", b"-->") if is_bytes else ("<!--", "-->")
        i = 0
        while True:
            if not self.open:
                j = line.find(o, i)
                if j < 0:
                    break
                self.open, i = True, j + len(o)
            else:
                j = line.find(c, i)
                if j < 0:
                    break
                self.open, i = False, j + len(c)
        return start_inside


def is_stale(root, rel, scope, change):
    """〔sweep-pool-debt D2/D3/D9〕内容指纹单一源判定。scope: 'design'|'code'。
    返回 `(stale, freshness)` 二元组。

    等值判定只走 digest（DT-2）：报告 frontmatter 的内容锚 `reviewed_sha` 本身就是
    "被批准盘面"的监视域 manifest digest；HEAD 侧重算同一监视域的 manifest digest 与
    之比较——不再把锚值当 git ref 解析（旧实现曾以锚 sha 取 `ls_tree_map`，锚已改为
    不可解析为 git 对象的内容摘要，此路径整体删除）。

    design 域仅盯本 change 四件套路径（proposal/design 与 specs/，tasks.md 已移出
    监视集〔D2〕）——不可套用整个 openspec/changes/{change}/：该目录还装着 cr/verify/
    hand-off 等正常尾流产物，套用整目录会让收尾提交把 design-approved 误判陈旧（链自锁）。
    """
    sha, _anchor_manifest = _read_anchor(root, rel)
    if scope == "design":
        # [harden-gate-git-layer Task3 · ADR-2] **比内容，不枚举路径**：HEAD 侧重算同一
        # 监视集的 manifest digest，与锚 digest 比较——新增/删除/rename/修改/mode 变更/
        # 类型变更天然全覆盖（manifest 含 path 维），且不需要另做双侧并集。
        base = change_base(change)
        specs = design_pathspecs(base)
        head_entries = ls_tree_map(root, "HEAD", specs)
        _head_mb, head_digest = fingerprint_entries(head_entries)
        return (head_digest != sha), ("stale" if head_digest != sha else "fresh")
    # scope == "code"
    # [harden-gate-git-layer Task5 · ADR-2] 比**仓库顶层条目的浅层快照**——HEAD 取一次
    # 非递归 `ls-tree`，排除 `openspec` 记账条目后求 manifest digest，与锚 digest 比较。
    # tree 条目 oid 递归摘要整棵子树 ⇒ 顶层某目录内任意深度的源码改动都会翻转其顶层
    # tree oid ⇒ 被捕获（无需 `-r`）。
    #
    # 收益（design.md 威胁模型两行 · 本判据唯一正面收益）：
    #   ① 代码审后经 merge 提交 resolve 引入的源码改动 ⇒ 该源码所属顶层条目 oid 变 ⇒ stale。
    #   ② `git mv` 把源码搬进 `openspec/` ⇒ 源路径所属顶层条目（或顶层源文件本身）消失/变化
    #      ⇒ manifest 不等 ⇒ stale（迁入的目标在 openspec 内、被排除，但**离开源顶层这一侧**仍暴露）。
    #
    # 🔴 **MUST NOT 用整棵树的 sha**：done 写 `verify-report.md`（在 openspec/ 内）即改变整树
    #   sha ⇒ 正常收尾流程第一步就假阳判失鲜（已实测证伪）。∴ 排除 openspec 后按剩余顶层条目比。
    # 🔴 **MUST NOT 用负向 pathspec** `':!openspec'`：继承外部可控的 `GIT_ICASE_PATHSPECS`
    #   （已实测证伪）。排除在 Python 侧按条目名做（`p != b"openspec"`），git pathspec 语义不参与。
    # rc≠0 由 `ls_tree_map` 抛 `GateIndeterminate`（→ UNKNOWN(6)），读失败不折成空集假等值。
    head_digest = code_digest_at(root, "HEAD")
    return (head_digest != sha), ("stale" if head_digest != sha else "fresh")


def code_digest_at(root, ref):
    """`ref` 上 code 域（仓库顶层条目、排除 openspec）的内容指纹 digest——`is_stale` code 分支与
    归档态交付核对（B2）共用，单一源。"""
    top = ls_tree_map(root, ref, recursive=False)
    return fingerprint_entries({p: v for p, v in top.items() if p != b"openspec"})[1]


def _content_anchor_from_text(text):
    """报告文本 → 互证通过的 64 位内容锚 sha；缺锚 / 旧 40-hex / 不互证 / 坏 frontmatter → None。
    （归档读点专用：归档文本来自 `git show`，不经 live 读点的 `_read_anchor`。）"""
    state, err = parse_ship_gate_frontmatter(text)
    if err is not None:
        return None
    sha, manifest = state.get("reviewed_sha"), state.get("reviewed_manifest")
    if not (isinstance(sha, str) and len(sha) == 64 and isinstance(manifest, str)):
        return None
    try:
        mb = base64.b64decode(manifest, validate=True)
    except Exception:
        return None
    return sha if hashlib.sha256(mb).hexdigest() == sha else None


def archived_code_mismatch(root, verify_text, ref):
    """〔B2〕归档 verify 报告锚定的「已验证代码」vs `ref` 上的代码域指纹：一致 → None；否则 → 原因。

    归档态不再有 active 报告可求失鲜：归档提交若夹带了已暂存的源码、或归档后工作分支又提交了
    代码，没有这道核对就会被当作已验证内容判 SHIPPED / 合入目标分支。"""
    sha = _content_anchor_from_text(verify_text)
    if sha is None:
        return ("归档 verify-report 缺有效的 64 位内容锚（reviewed_sha/reviewed_manifest），"
                "无法确认待交付代码就是已验证代码；旧格式归档请人工核对后手动处理")
    if code_digest_at(root, ref) != sha:
        return (f"{ref[:7] if len(ref) == 40 else ref} 上 openspec/ 外的代码与 verify 锚定的已验证代码不一致"
                "（归档提交夹带了未验证源码，或归档后又提交了代码）→ MUST NOT 判完成/合并；"
                "撤出这些改动，或回到 active 状态重新 verify")
    return None




def _line_scoped_hits(text, candidates):
    """文本级行锚定核心（零正则）：候选须独占一行（strip 后等值），忽略 fenced code block。
    返回 (hits[按 candidates 原序去重], unbalanced[EOF 时围栏未闭合])。
    [impl-review-fix FIX-5；T75] 现役唯一调用方 = archived_verify_state（归档 dual-read 兜底旧
    inline）；live decide() 侧的 inline 读半场已随 Task6 迁 frontmatter 退役，其专属读点函数
    随 T75 一并删除（不再留孤儿）。fence 翻转口径同 _parse_plan
    （共用单一源 fence_delim/FenceTracker，``` 与 ~~~ 两族均识别）。"""
    cand = set(candidates)
    hit = set()
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        s = line.strip()
        if s in cand:
            hit.add(s)
    return [a for a in candidates if a in hit], fence.inside


# [mlh-p5][shared-yaml-subset-parser R9] frontmatter 状态解析：结构预扫描仍是手写 stdlib
# （duplicate-key/tab-indent，R11），**取值**委托给外部 yq(mikefarah) 二进制（`_yq()`）——
# 不 `import yaml`，零依赖不变量指的是不引入 Python 侧 YAML 解析库依赖，非不依赖任何外部工具
# （同 git 的外部二进制先例）。live 读与归档 git-show 文本读共用此单一核心（防漂移，D4）。
FIELD_ENUMS = {
    "design_approved": (True, False),   # bool
    "verify": ("PASS", "FAIL"),
    "code_review": ("pass", "blocked"),
}

# [harden-gate-git-layer Task1 · tasks 1.1/1.2] 字段校验从「有限枚举」升级为「字段 → 校验函数」。
# 理由：`reviewed_sha` 的值域是「任意 40 位 hex」，装不进 FIELD_ENUMS 的元组——直接往
# FIELD_ENUMS 加字段会让每个真 sha 都判 out-of-domain（= 新锚永远读不到）。
# FIELD_ENUMS 保留为枚举字段的数据源（三 producer 模板契约测试仍按它比对定义域）。
_FULL_OID_CHARS = frozenset("0123456789abcdef")


def _is_full_oid(val):
    """〔sweep-pool-debt D3/D4 · DT-1 校验分层〕`reviewed_sha` 的**语法级**校验——
    40（旧 commit-OID 格式，容归档 34 份存量报告自然通过解析）或 64（内容 manifest
    digest，新格式）位小写 hex；拒：缩写 SHA、`HEAD` 及一切符号式 revision、大写 /
    非 hex 字符 / 其它长度。

    本层**只做语法**，不判定"是不是内容锚的正确格式"——那是 live 读点 `_read_anchor`
    的语义级职责（MUST 恰为 64 位 + 与 `reviewed_manifest` 互证）。解析核不为归档/live
    两种模式分叉（承 A4 共核纪律），故此处必须两种长度都放行，否则归档存量 40-hex 报告
    会在解析层就被判 out-of-domain → 坏 frontmatter → SHIPPED 判定大面积回归。
    """
    return (isinstance(val, str) and len(val) in (40, 64)
            and set(val) <= _FULL_OID_CHARS)


_BASE64_LINE_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def _is_base64_manifest_line(val):
    """〔sweep-pool-debt D3/D4〕`reviewed_manifest` 的**语法级**校验——单行合法 base64
    字符集 + 长度为 4 的倍数（标准 base64 编码天然性质）。空字符串合法（对应零字节监视域
    manifest 的合法编码——`anchor_writeback.py` 生产路径已对空监视域 fail-loud 拒写，
    这里放行空串只是为了不让"空监视域"这个理论上合法的 digest 在解析层被误判语法非法；
    producer 侧的空域防线在写锚脚本，不在这里）。**不解码、不做互证**——互证（解码后
    sha256 == reviewed_sha）是 live 读点 `_read_anchor` 的语义级职责，解析核只判
    "看起来像不像一段合法 base64"。"""
    if not isinstance(val, str) or len(val) % 4 != 0:
        return False
    if val == "":
        return True
    return bool(_BASE64_LINE_RE.match(val))


def _enum_validator(allowed):
    def check(val):
        return val in allowed
    return check


# 「本 schema 认识哪些字段」的单一注册表（parse 用它判 field 是否本 schema、并做值校验）。
FIELD_VALIDATORS = {field: _enum_validator(vals) for field, vals in FIELD_ENUMS.items()}
FIELD_VALIDATORS["reviewed_sha"] = _is_full_oid
FIELD_VALIDATORS["reviewed_manifest"] = _is_base64_manifest_line


def parse_ship_gate_frontmatter(text):
    """解析报告 frontmatter 的 ship-gate 状态。返回 (state, error)：
      state: {field: value}（已过 FIELD_VALIDATORS 校验）；{} = absent（无 frontmatter / 无 ship-gate 键）
      error: None（干净）或 (field|'frontmatter', category)
             category ∈ duplicate-key|out-of-domain|bad-type|tab-indent
    D2 只认文件首块：首行须 '---'（去 BOM）；正文 --- 横线不参与。
    D3 坏≠无：absent(state={},error=None) vs 坏(error!=None) 由调用方分流退出码。
    D5 重复键→duplicate-key（枚举全部同名键计数，非取最后一个）。

    [shared-yaml-subset-parser] 分两段：① 原始文本预扫描（R11）只做**结构诊断**——
    定位首块边界、检测顶层 `ship-gate:` 头 / 直接子字段的 duplicate-key 与 tab-indent、
    判断顶层头是否为规范空 map 形（`ship-gate:` 独占一行）。这几类诊断 yq 给不出：
    实测 yq 对重复键静默取最后值（exit 0）、对 tab 缩进只报笼统 go-yaml 词法错误、对
    flow-style `ship-gate: {verify: PASS}` 会解出与 block-style 相同的 dict（丢失「是否
    规范块头」这个信息）。② 预扫描通过后，**取值**委托给 `_yq()`——真 YAML 语义（布尔
    类型、引号剥离、注释剥离、嵌套结构隔离）交给它，比手搓 partition/strip 更正确
    （如 `note:` 下嵌套的 `design_approved` 天然不会被解到顶层，无需再手动分层跳过）。

    [impl-review-fix FIX-2] 顶层 `ship-gate:` 后带非空内容（内联标量/inline map）→ bad-type
    （非 absent），防归档路径把它当 absent 回退 inline 造成假 SHIPPED——本函数在①阶段
    以文本形式判定（`header.rstrip() != "ship-gate:"`），故 flow-style 内联 map 同样落
    bad-type（不会因为 yq 把它解析成合法 dict 而被误采信，见上段）。
    [已知不覆盖，见 Compliance 段] 引号值不再严格区分（`verify: "PASS"` 与 `verify: PASS`
    经真 YAML 解析等价，均判 in-domain）——这是切换到 yq 真解析器的必然代价，旧手搓扫描器
    的「引号即坏」是手搓副作用而非业务不变量，测试断言已同步调整（见 impl-report）。
    """
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines()               # 统一 \r\n/\n（值不残留 \r）
    if not lines or lines[0].strip() != "---":
        return {}, None                     # absent：无首块 frontmatter
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        # [T74] 首行 --- 但全文无第二个 --- → 首块不闭合 → 不构成 frontmatter block，
        # 首行 --- 视作正文/markdown 水平线 → absent（走既有无锚语义），非坏、非 fail-closed。
        # 与「D2 只认文件首块」定义统一：无闭合 --- 不成块。
        # [R11] 这一步是**边界检测**，不是 YAML 值解析——yq 的 `--front-matter=extract` 不要求
        # 闭合 `---`（实测：会把首行之后的全部内容当一份 YAML 文档处理，`###` 之类行被当
        # 注释吞掉），若不在此短路直接调 yq，"未闭合" 会被误判为"已解析成功"。
        return {}, None
    block = lines[1:end]
    # 找顶层 ship-gate: 键，统计出现次数（重复→坏）。
    # [impl-review-fix FIX-2/FIX-4][R11] 顶层探测识别**任何以 ship-gate: 起始的行**（不再只认
    # 整行 == "ship-gate:" 的规范空 map 头）：tab 缩进 → tab-indent 坏（FIX-4，与字段行 tab
    # 检测对称，yq 对此只报笼统词法错误、给不出 tab-indent 这个分类）；空格缩进 = 嵌套键
    # （非顶层），忽略；0 缩进 = 真顶层键——若其后 rstrip 还有非空内容（内联标量/inline map，
    # 如 `ship-gate: []`/`ship-gate: true`）→ bad-type（FIX-2，杜绝归档误回退 inline）。
    top_hdrs = []                            # [(index, line)]，0 缩进的顶层 ship-gate: 行
    for i, ln in enumerate(block):
        if not ln.lstrip().startswith("ship-gate:"):
            continue
        indent_ws = ln[:len(ln) - len(ln.lstrip())]
        if "\t" in indent_ws:
            return {}, ("frontmatter", "tab-indent")   # FIX-4：tab 缩进顶层键
        if indent_ws:
            continue                         # 空格缩进 = 嵌套键，非顶层，忽略
        top_hdrs.append((i, ln))
    if len(top_hdrs) == 0:
        return {}, None                     # absent：有 frontmatter 但无 ship-gate 键
    if len(top_hdrs) > 1:
        return {}, ("ship-gate", "duplicate-key")
    header_idx, header = top_hdrs[0]
    if header.rstrip() != "ship-gate:":     # FIX-2：非规范空 map 头（带内联标量值）→ 坏
        return {}, ("ship-gate", "bad-type")
    # [R11] 直接子字段的 duplicate-key/tab-indent 预扫描：只计数/查 tab，不解析取值
    # （取值交给下方 `_yq()`）。缩进层级判定（FIX-1 的分层跳过）仍需要，因为本段只做
    # **结构诊断**（哪些行算"直接子字段"），与"这些字段的值是什么"（yq 的职责）分离。
    start = header_idx + 1
    seen = {}
    direct_indent = None
    for ln in block[start:]:
        if ln.strip() == "":
            continue
        if not ln[:1].isspace():
            break                           # 回到 0 缩进 = ship-gate 块结束
        # [impl-review-fix FIX-3a] 块内独占注释行（strip 后以 # 起始）跳过——放在 tab/冒号检测之前
        if ln.strip().startswith("#"):
            continue
        indent_ws = ln[:len(ln) - len(ln.lstrip())]
        indent = len(indent_ws)
        if direct_indent is None:
            direct_indent = indent          # 首个非空非注释子行定直接子键层级
        if indent > direct_indent:
            continue                         # FIX-1：嵌套子树（深于直接层级），跳过不扫
        if "\t" in indent_ws:
            return {}, ("frontmatter", "tab-indent")
        body = ln.strip()
        if ":" not in body:
            return {}, ("frontmatter", "bad-type")
        field, _, _raw = body.partition(":")
        field = field.strip()
        if field not in FIELD_VALIDATORS:
            continue                         # 非本 schema 字段（外来 metadata），忽略
        seen[field] = seen.get(field, 0) + 1
        if seen[field] > 1:
            return {}, (field, "duplicate-key")

    # ── 预扫描通过（结构干净）：委托 yq 做真正的 YAML 取值 ──
    try:
        parsed = _yq('."ship-gate"', text=text, front_matter=True, default={})
    except RuntimeError:
        # yq 语法级解析失败（如字段值内未闭合引号）——预扫描管不到值内部语法，交给 yq
        # 自己报错；本函数只需把"取不出"折成 bad-type，不需要复述 yq 的原始错误文本
        # （错误文本对 (field, category) 这个契约无意义，且会让同一坏因产生不同措辞）。
        return {}, ("frontmatter", "bad-type")
    if not isinstance(parsed, dict):
        # [R5/F4] 理论不可达的双保险——`_yq()` 已对 front_matter 模式做过 dict 校验；
        # 本函数自己的①阶段头形检测（FIX-2）本就先于此拦下所有非规范头形态。
        return {}, ("ship-gate", "bad-type")

    state = {}
    for field, val in parsed.items():
        if field not in FIELD_VALIDATORS:
            continue                         # 非本 schema 字段/嵌套子树，忽略（yq 的真解析
                                              # 已天然把嵌套字段留在其父键下，不会冒到顶层）
        coerced = _coerce_ship_gate_value(field, val)
        if coerced is _BAD_TYPE:
            return {}, (field, "bad-type")
        if not FIELD_VALIDATORS[field](coerced):
            return {}, (field, "out-of-domain")
        state[field] = coerced
    return state, None


_BAD_TYPE = object()


def _coerce_ship_gate_value(field, val):
    """`val` 现为 yq 真解析出的类型化值（bool/str/…），非旧版的原始文本片段。"""
    if field == "design_approved":
        if isinstance(val, bool):
            return val
        return _BAD_TYPE                     # "yes"/1/"True" 等非规范 bool 经 YAML 解析后
                                              # 落成字符串/整数，非 Python bool → 坏
    return val                               # verify/code_review/reviewed_sha：交枚举/正则校验


# [T26/SR-1] 熔断判据（anchor_set / breaker_no_progress 纯函数）已删除：生产路径从未接入
# （只有测试引用），熔断实际由执行者比对**连续两次 gate 输出**（verdict + 相关报告
# frontmatter 状态）判定，见 g-done SKILL「铁律 2」。留着死代码只会让人误以为有机械熔断。


# ── 决策纪要门（B6）：送设计审之前，本 change 必须有 g-spec 相位 B 定稿的 decision-memo.md ──
# 此前该门只存在于 gearbox 自身的 pytest（扫本仓 openspec/），消费仓绕过 g-spec 建的 change
# 一路无人拦——文档却宣称「机械门」。判据与 g-spec C.1 前三判同口径：文件存在、两个必填
# 小节非空、frontmatter `decision_hash` 非空（= 相位 B 收敛两步已走完）。hash 重算（防定稿后
# 手改）仍由 g-spec C.1 负责：那是生成前的身份核验，gate 这里只守「纪要真实存在且已定稿」。
MEMO_FILENAME = "decision-memo.md"
MEMO_REQUIRED_SECTIONS = ("## 拍板决策", "## 承重约束")
_ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:\s|$)")


def _atx_level(line):
    m = _ATX_RE.match(line)
    return len(m.group(1)) if m else None


def _memo_section_body(text, heading):
    """`heading` 行到下一个同级或更高级 ATX 标题之间的正文；不存在 → None。
    fenced code block / HTML 注释块内的行不参与标题判定（复用本文件两个追踪器，单一源）。"""
    level = _atx_level(heading)
    lines = text.splitlines()
    fence, comment = FenceTracker(), HtmlCommentTracker()
    visible = []
    for line in lines:
        is_fence_line = fence.feed(line)
        in_comment = comment.feed(line)
        visible.append(not is_fence_line and not fence.inside and not in_comment)
    start = next((i for i, l in enumerate(lines)
                  if visible[i] and _atx_level(l) == level and l.strip() == heading), None)
    if start is None:
        return None
    end = len(lines)
    for i in range(start + 1, len(lines)):
        lv = _atx_level(lines[i])
        if visible[i] and lv is not None and lv <= level:
            end = i
            break
    return "\n".join(lines[start + 1:end])


def decision_memo_problems(change_dir):
    """→ [] 表示纪要过门；否则返回缺口列表（每条可直接照做）。"""
    memo = Path(change_dir) / MEMO_FILENAME
    if not memo.is_file():
        return [f"{MEMO_FILENAME} 不存在（相位 B 未产出决策纪要）"]
    text = _read_report_text(memo, "决策纪要")
    if text.startswith("﻿"):
        text = text[1:]
    problems = []
    for heading in MEMO_REQUIRED_SECTIONS:
        body = _memo_section_body(text, heading)
        if body is None:
            problems.append(f"{MEMO_FILENAME} 缺必填小节「{heading}」")
        elif not re.sub(r"<!--.*?-->", "", body, flags=re.DOTALL).strip():
            problems.append(f"{MEMO_FILENAME} 必填小节「{heading}」为空")
    lines = text.splitlines()
    closed = bool(lines) and lines[0].strip() == "---" and any(l.strip() == "---" for l in lines[1:])
    front = {}
    if closed:
        try:
            front = _yq(".", text=text, front_matter=True, default={})
        except RuntimeError:
            problems.append(f"{MEMO_FILENAME} 的 frontmatter 不可解析")
            front = None
    if front is not None:
        value = front.get("decision_hash") if isinstance(front, dict) else None
        if not (isinstance(value, str) and value.strip()):
            problems.append(f"{MEMO_FILENAME} 的 frontmatter 缺 decision_hash（纪要未定稿：相位 B 收敛两步未走完）")
    return problems


def emit(verdict, exit_code, next_step, reason, **extra):
    human = f"[ship-gate] {verdict}"
    if next_step:
        human += f" → next={next_step}"
    human += f" — {reason}"
    print(human)
    print(json.dumps({"verdict": verdict, "next": next_step,
                      "reason": reason, **extra}, ensure_ascii=False))
    sys.exit(exit_code)


# [harden-gate-git-layer Task4 · ADR-3 · tasks 2.5/2.6/2.7] 求值窗口的**唯一**实现点。
#
# 🔴 为什么是「窗口内 emit 的包装」而不是「step 7 之后加一次检查」：
# `RUN_PLAN`(step 6) 这条路径在到达 step 7 之前就 `emit()`，而 `emit()`
# 内部是 `sys.exit()` —— 硬 early-return。把检查放在 step 7 之后，这条路径**完全逃出检查**，
# 方向 fail-open（正是本 change 要治的那类洞）。∴ 检查 MUST 挂在**两个分支各自的 emit 之前**。
#
# 反向的捷径同样错：把检查放在最前（= 旧实现 `:1263` 的位置，unconditional）等于没做窗口限定——
# 代码审期/收尾期修订四件套（全仓 14 个历史提交、`opsx:verify` step 7 明文允许）会被误拦。
#
# 窗口 = `RUN_PLAN` / `CONTINUE_IMPL` 两个「进入实现期」的判定。窗口右边界是
# 「代码审报告出现」而非「最后一个任务打勾」——代码审过程中本来就会改代码与文档。
def design_drift(root, change, report):
    """design 锚之后监视集（proposal/design/specs）的内容变化 → `(stale, paths, detail)`。

    判定走 `is_stale`（单一源）；只有失鲜时才对锚 manifest 与 HEAD 侧求差集点名路径
    （DT-2：锚是内容摘要、不是 git ref，MUST NOT 拼 `git diff <sha>`）。
    fresh ⇒ `(False, [], "")`。供窗口内闸门（`guard_design_freshness`）与实现后的非阻塞
    `design_drift` 提示（B1）共用，防两处口径漂移。
    """
    rel = str(report.relative_to(root))
    design_stale, _freshness = is_stale(root, rel, "design", change)
    if not design_stale:
        return False, [], ""
    _sha, anchor_manifest = _read_anchor(root, rel)
    base = change_base(change)
    specs = design_pathspecs(base)
    head_entries = ls_tree_map(root, "HEAD", specs)
    anchor_entries = _manifest_entries_from_bytes(anchor_manifest)
    diff_paths = sorted(
        p for p in set(anchor_entries) | set(head_entries)
        if anchor_entries.get(p) != head_entries.get(p))
    paths = [os.fsdecode(p) for p in diff_paths]
    points = []
    for path_str in paths:
        commit = run_git(root, "log", "-1", "--format=%H", "--", path_str)
        points.append(f"{path_str}（最近改动提交 {commit[:7] if commit else '未知'}）")
    detail = "；".join(points) if points else f"（差异路径不可枚举，监视集：{shlex.join(specs)}）"
    return True, paths, detail


def guard_design_freshness(root, change, report):
    """窗口内求值 design 域失鲜；stale ⇒ `REFUSE_START` 并**带出锚值**〔ADR-4〕。

    fresh 或不失鲜 ⇒ 原样返回，由调用方继续 emit 它自己的判定。
    """
    stale, _paths, detail = design_drift(root, change, report)
    if not stale:
        return
    # [ADR-4] 锚值 MUST 可见：撞门者不必先去翻报告 frontmatter 抄 sha。
    sha = read_reviewed_sha(root, str(report.relative_to(root)))
    # 默认处置**只**推荐重跑设计门——MUST NOT 在此提重锚脚本：它是显式越权口
    # （impl-review 尾流修订协议的组成步骤），写进常规失鲜的默认指引等于把受控协议的
    # 组成步骤变成撞门者的自赦通道（spec「重锚脚本 MUST NOT 出现在默认处置指引中」）。
    emit("REFUSE_START", EXIT_REFUSE, None,
         "design-approved 之后监视集内容已变 → 拍板失鲜，改设计须重审"
         "（重跑 /g-review spec 后由人重新拍板补锚）。触发点：" + detail,
         reviewed_sha=sha)


def emit_windowed(root, change, report, verdict, exit_code, next_step, reason, **extra):
    """求值窗口内的 `emit`：先过 design 域失鲜闸门，再 emit 本分支的判定。

    两个入口（`RUN_PLAN` / `CONTINUE_IMPL`）**各自**调用本函数 —— 这是
    「两分支各自接入、各自无旁路」的实现形态：拆掉任何**一处**的包装，只有该分支的用例变红。
    """
    guard_design_freshness(root, change, report)
    emit(verdict, exit_code, next_step, reason, **extra)


# [harden-gate-git-layer Task3 · ADR-4 · tasks 2.8] `_stale_trigger_hint` / `StaleResult.trigger`
# 已随帧比较整簇退役：触发点诊断原本**依附于帧遍历**（要 sha + subject），帧遍历没了之后，
# 为凑齐这段诊断而保留一条枚举通路，等于把刚砍掉的推断面从后门放回来。且该能力在 code 域
# 从未真正接通过（两个 code 域调用点本就二元解包丢弃 trigger）。
# 取代者 = `emit` 输出 `reviewed_sha`（录下来的常量，打印零推断成本）+ reason 拼出可执行的
# `git diff <reviewed_sha> HEAD -- …`（Task4 接入）。


# [mlh-p5 Task2/D3；Task6 退役 live inline] live 读点分流：frontmatter 有效→state；坏→UNKNOWN(6)；
# absent→None 交调用方走既有无锚语义（**不再回退 inline**）。坏 frontmatter 的退出码映射集中于此
# （越域/重复键/坏语法/类型不符→UNKNOWN，歧义须人裁、防 exit0 重跑死循环）。
def _fail_closed_on_bad(err, label):
    field, cat = err
    # [harden-gate-git-layer Task1 fix1 · F1] 锚字段自身语法非法 ⇒ 走 ANCHOR_INVALID 专属诊断。
    # 背景：三个 live 读点都先经 live_ship_gate_state，坏 frontmatter 在此就 emit 了通用 UNKNOWN，
    # 于是 read_reviewed_sha 里的 CAUSE_ANCHOR_INVALID 分支在生产路径上永不执行——撞门者拿到的是
    # 「坏 frontmatter」这句通用话，没有 cause_category、没有「订正为完整 commit OID」的指引，
    # 直接违反 Compliance「五类失败原因各给可行动诊断」。抛 GateIndeterminate 由 main() 唯一映射点
    # 统一转 UNKNOWN(6)+cause_category（MUST NOT 在此自行 emit，否则退出码映射散成多处）。
    # 〔sweep-pool-debt D3/D4〕`reviewed_manifest` 与 `reviewed_sha` 是同一把内容锚的两半、
    # 密码学互锁——manifest 字段自身语法非法（如非法 base64）与 sha 语法非法 MUST 走同一条
    # ANCHOR_INVALID 专属诊断，否则锚的另一半坏掉时撞门者只拿到通用「frontmatter 坏」话术，
    # 没有「重跑写锚脚本」这条可行动指引（同上条 F1 要修的缺口，对称地补齐第二个锚字段）。
    if field in ("reviewed_sha", "reviewed_manifest"):
        raise GateIndeterminate(
            f"{label} 报告的 ship-gate frontmatter 中 {field} 值非法（类别={cat}）",
            CAUSE_ANCHOR_INVALID)
    emit("UNKNOWN", EXIT_UNKNOWN, None,
         f"{label} frontmatter 坏（字段={field} 类别={cat}）→ fail-closed 无有效状态，请人工修复")  # D12 reason 点名 field+category


def live_ship_gate_state(path, label):
    """live 读某报告的 ship-gate 状态 dict。frontmatter 有效→state；坏→UNKNOWN(6) 停（不回退）；
    absent（无 frontmatter / 无 ship-gate 键）→返回 None，调用方走既有无锚语义（Task6 退役 live
    inline 回退，live 只读 frontmatter）。与归档 git-show 文本读共用 parse_ship_gate_frontmatter
    单核（防漂移，D4；归档侧仍 dual-read inline，live 侧不）。"""
    if not path.is_file():
        return None
    text = _read_report_text(path, f"{label} 报告文件")   # [impl-review-fix F3]
    state, err = parse_ship_gate_frontmatter(text)
    if err is not None:
        _fail_closed_on_bad(err, label)      # 坏永不回退，直接 fail-closed（emit 不返回）
    if state:
        return state                         # 有效键
    return None                              # absent → 调用方回退 inline


def _unclosed_frontmatter_hint(path):
    """[T74 1.5/spec-review Q1=A；design ADR-5] live 读点上层**独立轻量结构诊断**：
    报告首行为 '---' 但全文无第二个 '---'（首块不闭合，parse 判 absent）→ 返回结构提示串
    供 emit reason 追加。纯诊断——MUST NOT 改 parse 返回签名、MUST NOT 改 verdict/退出码、
    MUST NOT 探测意图（≠candidate②）。文件不存在 / 首行非 '---' / 已闭合 → 返回 ''（无提示）。
    与 parse 首块判据同口径（去 BOM、strip 后等值、只认第 2 行起首个 '---'），防诊断与解析漂移。
    [impl-review-fix F3] 「MUST NOT 改 verdict/退出码」约束的是**读取成功后**的正常路径；
    读取本身失败（TOCTOU：调用方早前 `live_ship_gate_state` 已确认过 is_file()，此处二次读取
    间隙文件被删/改权限）时，与其它报告读点一致 fail-closed 到 UNKNOWN(6)，好过让裸 OSError
    逸出成契约外的退出码 1——这不是本函数在"判定"什么，只是不重复制造一个新的逸出口。"""
    if not path.is_file():
        return ""
    text = _read_report_text(path, f"报告 {path.name}")
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    if any(lines[i].strip() == "---" for i in range(1, len(lines))):
        return ""                            # 已闭合 → 非本诊断场景（坏/有效由 parse 处置）
    return "（结构提示：首行为 `---` 但未见闭合 `---`，已按正文处理；欲声明状态请补闭合行）"


TASK_TITLE_RE = re.compile(r"^### Task (\d+):", re.M)   # 计数用；锚行才禁正则
# [T36/SR-4] canonical shape 权威源 = 本 TAG_RE。**parser 契约实际只执行到 `task<N>-` 前缀**
# （命名空间组可选、向后兼容裸 task<N>- 旧格式）；`<slug>` 是**建议性**约定（可读性/去重），
# TAG_RE 不校验其存在或形状〔impl-review-fix CR-3：勿把 <slug> 读成 parser 强制契约〕。
# workflow.md 的格式串样例、g-ship/SKILL.md
# 的引用式派发句均须与此正则保持一致；test_producer_parser_contract 钉死 producer(checkpoint-commit.sh
# 落的标签串) ↔ parser(本 TAG_RE) 的一致性。checkpoint-commit.sh 本身 format-agnostic（只裹
# `checkpoint($step)`，不校验形状），**非格式源**。
# SR-4 checklist：改此正则前先 grep workflow.md 里的格式串样例是否需要同步更新。
TAG_RE = re.compile(r"checkpoint\((?:([a-z0-9][a-z0-9-]*):)?task(\d+)-")  # [T32] 可选命名空间组


# [harden-implement-review-loop D5 / adr/0033 · Task 3 · remove-superpowers-pipeline Task2]
# 计划文件名单一源：`PLAN_FILENAMES` 是仓内唯一的候选文件名清单，`resolve_plan_path` 是唯一
# 的定位 helper，MUST NOT 手抄第二份候选列表。文件名**只用于定位**、不参与任何路由判定——
# tickets 已是唯一实现管线（adr/0042），`impl_route.py` 的路由半场（含曾被引用的
# `resolve_pipeline`）已随 Task1 整体切除，本仓不再有路由权威这个概念。
#
# 遗留旧名兜底：`tickets.md` 缺席 ∧ 遗留旧名 `superpowers-plan.md`（tickets 轨迁移前的计划
# 文件名）单独存在 ⇒ 视为迁移残留，fail-closed 判 UNKNOWN + 人工清理提示——不静默忽略后
# 导致该 change 被重复出票〔设计门 Q1 拍板〕。`superpowers-plan.md` MUST NOT 被当作可用计划
# 文件返回，它只触发这一条兜底诊断。
#
# 🔴 在途 plan MUST NOT 被重命名（design Migration Plan 逐字）：`plan_first_sha` 用
# `git log --diff-filter=A`，不跟随重命名——改名会把完成判据窗口起点推到改名 commit，
# 使改名前的全部 checkpoint 标签落到窗口外、已完成 ticket 被判未完成。resolver 本身不
# 试图侦测/修复这个窗口重置（那需要重命名跟踪，超出本 change 范围）；`stray_done_tag_commits`
# 检测的是该风险的**结果**（窗口外完成标签），而非改名这个动作本身，见下方大段说明。
PLAN_FILENAMES = ("tickets.md",)              # 单名（resolver 函数形状保留，供 gate/测试共用）
LEGACY_PLAN_FILENAME = "superpowers-plan.md"  # 仅用于遗留旧名兜底探测，不参与定位


class LegacyPlanNameFound(Exception):
    """`tickets.md` 缺席、遗留旧名 `superpowers-plan.md` 单独存在——fail-closed，提示人工清理。"""


def resolve_plan_path(change_dir):
    """在 `change_dir` 下探测计划文件：`tickets.md` 存在 ⇒ 返回之；`tickets.md` 缺席但遗留
    旧名 `superpowers-plan.md` 存在 ⇒ raise `LegacyPlanNameFound`（调用方按 fail-closed
    UNKNOWN 处置，提示人工清理——迁移残留不静默忽略）；两者皆缺 ⇒ 返回 `None`（调用方按
    RUN_PLAN 处置）。
    """
    change_dir = Path(change_dir)
    hits = [change_dir / name for name in PLAN_FILENAMES if (change_dir / name).is_file()]
    if hits:
        return hits[0]
    legacy = change_dir / LEGACY_PLAN_FILENAME
    if legacy.is_file():
        raise LegacyPlanNameFound(
            "计划文件名遗留：" + str(change_dir) + " 下 " + PLAN_FILENAMES[0]
            + " 缺席，但发现遗留旧名 " + LEGACY_PLAN_FILENAME
            + "，请人工清理（迁移到 " + PLAN_FILENAMES[0] + " 或删除该文件）")
    return None


def plan_task_ids(plan):
    # [spec-review-amendment B4/D5] plan 声明的任务号集（去重）。完成判据按**集合归属**
    # （plan_ids ⊆ done_ids）而非基数（len(done) < n）——否则计划外任务号（遗留/错号/
    # merge 内提交的 checkpoint(task9-)）会顶替缺失的计划内号让基数达标而假齐（假✅）。
    # [impl-review-fix CR-F2] fence-aware：fenced 代码块内的 `### Task N:` 示例标题不算任务
    # （与复选框同 fence 口径，经共享 _parse_plan——前向引用，运行时已定义，模块级合法）。
    text = plan.read_text(encoding="utf-8", errors="replace")
    return set(_parse_plan(text)[0])


def plan_task_count(plan):
    return len(plan_task_ids(plan))


def plan_first_sha(root, plan_rel):
    out = run_git(root, "log", "--diff-filter=A", "--format=%H", "--", plan_rel)
    # [impl-review-fix] 取首行（最新一次新增记录，git log 默认新→旧序）而非末行：
    # plan 被删后重建场景，重建视为该 plan 的新生命周期，窗口应锚定最新一次 A 记录，
    # 否则窗口会回溯到已作废的旧生命周期首次新增点，混入重建前的历史提交。
    return out.splitlines()[0] if out else ""


# [impl-review-fix FIX-1] 完成标签识别的**单一源**：窗口内计数（`done_task_ids`）与窗口外
# 检出（`stray_done_tag_commits`）共用同一份「字面前缀 + TAG_RE 锚定匹配 + 命名空间归属」
# 判据，MUST NOT 各自手抄第二份正则或第二份过滤规则。
def _tag_task_id(subject, change, require_namespace=False):
    """单条 commit subject → 完成标签的任务号字符串；不是本 change 的完成标签则 None。

    `require_namespace=True` 时**裸标签**（`checkpoint(task<N>-`，无命名空间）一律不认——
    窗口外的裸标签无从归属（本仓 main 上大量存在别的 change 的遗留裸标签），拿它当归属证据
    会把每个 change 全数误报。窗口内则保留 A1 向后兼容（裸标签按窗口计入）。
    """
    # [impl-review-fix] 先判字面前缀再锚定匹配：`Revert "checkpoint(task2-b): y"`
    # 这类 revert 提交消息里 checkpoint( 子串不在行首，不应计入完成集
    # （TAG_RE.search 不锚位置会把它误计，match 从位置 0 锚定则天然排除）。
    # [ship-gate-hardening-2 T32/A-F1] 前缀过滤 MUST 放宽为 "checkpoint("——旧硬前缀
    # "checkpoint(task" 会把命名标签 checkpoint(<ns>:task 在 TAG_RE.match 前整条跳过，
    # 令 T32 静默失效并吞掉本 change 自己的命名完成号。
    if not subject.startswith("checkpoint("):
        return None
    m = TAG_RE.match(subject)
    if not m:
        return None
    ns, num = m.group(1), m.group(2)
    if ns is None:
        return None if require_namespace else num
    return num if ns == change else None   # 命名空间不匹配 → 排除（假阴安全，不新增假阳）


# [impl-review-fix FIX-1] 🔴 在途 plan MUST NOT 被重命名（design Migration Plan 逐字）。
# 旧实现 `plan_was_renamed` 用 `git log --follow` 的**内容相似度**重命名检测去判「有没有
# 发生过改名」，三种失效模式均已由 fixture 实测证实（见 test_plan_resolver.py 同名用例）：
#   ① **误报 → 永久自锁**：同一 commit 里「删掉 change A 的 tickets.md + 新建 change B 的
#      tickets.md」会被 git 按相似度配对成改名（本 change 强制所有 tickets.md 用同一套
#      `### Task N:` / `Blocked-by:` / `R-ID:` 模板 ⇒ 相似度天然过线），于是 B 那个**从未
#      被改过名**的新 plan 判 True；而提示「请改回原文件名」**无原名可改回**，用户唯一出路
#      是历史重写（本仓明禁 `-i`，且会击穿 `reviewed_sha` 审计锚）。
#   ② **漏报 → 防护被绕过**：改名拆成两次提交（先 `git rm` 提交、后新建提交）——git 的重命名
#      配对**只在单个 commit 的 diff 内**做，跨 commit 无从判断 ⇒ False。而这正是要防的场景本身。
#   ③ **漏报 → 防护被绕过**：`git mv` + **同提交大幅编辑** → 相似度跌破阈值 ⇒ False。而
#      「改名 + 大幅编辑同提交」恰是 superpowers-plan.md → tickets.md 迁移的天然形态
#      （迁移正需要给每个 Task 段补 `R-ID:` / `Blocked-by:`）。
# 两个修法互相冲突（调低相似度阈值 `-M1%` 能救 ③ 却加重 ①），这本身证伪了启发式路线
# ——拿模糊启发式去回答一个需要精确答案的问题（CLAUDE.md 基准 5 的警号）。
#
# ∴ **不再检测「有没有发生过改名」（原因），改为直接检测「危害有没有发生」（结果）**：
# 本 change 是否存在落在完成判据窗口 `[plan_first_sha, HEAD]` **之外**的完成标签提交。
# 有 ⇒ 窗口起点是错的（不论成因是改名、两步改名、还是删除重建）⇒ fail-closed 判 UNKNOWN。
#
# 这是**精确判据而非启发式**：① 新开 change 的命名空间下不存在早于其 plan 创建的完成标签
# ⇒ 不误报；②③ 改名前打的标签必然落在新窗口起点之前 ⇒ 检出；且比旧判据**更强**——覆盖
# 一切导致窗口起点错误的成因，不只是改名。
def stray_done_tag_commits(root, sha, change):
    """→ 落在完成判据窗口 `[sha, HEAD]` 之外、且属于 `change` 命名空间的完成标签提交 sha 列表。

    「窗口外」= **从 `sha` 可达、但不是 `sha` 自身**的提交。HEAD 的历史恰好等于
    「`sha` 可达集」∪「`sha..HEAD`」，二者互补 ∴ 无需再列一遍 HEAD 全史做差集。
    """
    out = run_git(root, "log", sha, "--no-merges", "--format=%H %s")
    stray = []
    for line in out.splitlines():
        commit, _, subject = line.partition(" ")
        if commit == sha:
            continue                       # sha 自身 = 窗口闭区间左端，在窗口内
        if _tag_task_id(subject, change, require_namespace=True) is not None:
            stray.append(commit)
    return stray


def done_task_ids(root, sha, change):
    # [spec-review-amendment B1] 窗口闭区间 [sha, HEAD]：{sha}..HEAD 排他 + sha 自身 subject。
    # checkpoint 的 add -A 会把未提交的 tickets.md 与 task1 锚打进同一 commit（即 sha），
    # 排他 {sha}..HEAD 会漏数 task1；追加解析 sha 自身 subject（同前缀+TAG_RE 规则）补齐。
    # [ship-gate-hardening-2 T32] change 命名空间归属：命名标签 checkpoint(<ns>:task<N>-)
    # 仅当 ns==change（精确==，非前缀）计入；裸标签 checkpoint(task<N>-) 走窗口计入（A1 兼容）。
    msgs = run_git(root, "log", f"{sha}..HEAD", "--no-merges", "--format=%s")
    lines = msgs.splitlines()
    self_subject = run_git(root, "log", "-1", "--format=%s", sha)
    if self_subject:
        lines.append(self_subject)
    ids = set()
    for line in lines:
        # [impl-review-fix FIX-1] 归属判据经共享单一源 `_tag_task_id`（窗口内保留 A1 兼容：
        # 裸标签按窗口计入 ⇒ require_namespace 取缺省 False）。
        num = _tag_task_id(line, change)
        if num is not None:
            ids.add(num)
    return ids


# [ship-gate-hardening-2 T34 + impl-review-fix CR-F1/F2] 复选框辅通道按 Task 分段绑定。
# 旧全局 checkboxes_all 全文子串判"无任何 - [ ]"即放行所有 task——无复选框的 task（仅散文）
# 会被全局放行（假✅）。CR-F1/F2〔代码审对抗镜+outside-voice 两声共识〕：Task 标题与复选框
# MUST 共享**同一个全文 fence 状态**（单遍 _parse_plan）——旧版"先切段、每段各自重置 in_fence"
# 会让悬空/跨段围栏泄漏（段内未闭合 ``` 吞掉真实未勾项 → 假✅）、且标题正则对围栏无感知
# （fenced 示例标题被当真 task/误判重号）。二者统一到一次带 fence 状态的整文扫描。
#
# [sweep-pool-debt] 本 pattern 曾与 bytes 版 `CHECKBOX_BYTES_RE`（勾选框归一化专用）同源
# 派生；bytes 版随 tasks.md 勾选框豁免层整体退役已删除，此处只保留 plan 解析仍需的 str 版。
CHECKBOX_RE_PATTERN = r"^\s*-\s+\[([ xX])\]"
CHECKBOX_RE = re.compile(CHECKBOX_RE_PATTERN)   # 行锚定复选框（非全文子串）


def _parse_plan(text):
    # [T34/impl-review-fix] fence-aware 单遍解析（Task 标题与复选框统一围栏口径）。
    # fenced code block（``` 围栏）内的行对 Task 标题与复选框**均不可见**（CR-F1/F2）。
    # 返回 (task_order[出现序,含重号], boxes_by_task{num:[checked_bool]}, any_checkbox, unbalanced)。
    # unbalanced=True 表示 EOF 时围栏未闭合（悬空 ```）——plan 无法可靠解析（CR-F1）。
    task_order = []
    boxes_by_task = {}
    any_checkbox = False
    cur = None
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        tm = TASK_TITLE_RE.match(line)
        if tm:
            cur = tm.group(1)
            task_order.append(cur)
            boxes_by_task.setdefault(cur, [])
            continue
        cm = CHECKBOX_RE.match(line)
        if cm:
            any_checkbox = True
            if cur is not None:   # 前言段（首个 Task 前）的框不归任何 task，忽略
                boxes_by_task[cur].append(cm.group(1) in ("x", "X"))
    return task_order, boxes_by_task, any_checkbox, fence.inside


# g-implement 的停点约定：票失败时在 tickets.md 该票段内写一行 `BLOCKED: <原因>`。
# gate（CONTINUE_IMPL 前）与 impl_route frontier 共用本解析，避免两份口径。
BLOCKED_LINE_RE = re.compile(r"^\s*(?:[-*]\s+)?\**BLOCKED\**\s*[:：]\s*(.*?)\s*$")


def plan_blocked_tickets(text):
    """→ {票号: 原因}。fence-aware（与 _parse_plan 同口径）；首个 Task 前的 BLOCKED 行不归任何票。
    删除该行 = 人已处理阻塞，票恢复可派发。"""
    blocked = {}
    cur = None
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        tm = TASK_TITLE_RE.match(line)
        if tm:
            cur = tm.group(1)
            continue
        bm = BLOCKED_LINE_RE.match(line)
        if bm and cur is not None:
            blocked[cur] = bm.group(1) or "（未写原因）"
    return blocked


def checkbox_done_ids(plan):
    # 只返回全部验收框已勾的票号供结构检查；gate 的完成判据另取提交标签。
    text = plan.read_text(encoding="utf-8", errors="replace")
    _, boxes, _, _ = _parse_plan(text)
    return {num for num, states in boxes.items() if states and all(states)}


def plan_has_any_checkbox(plan):
    # [T34] 全 plan 有无（行锚定、非代码块内）复选框——供计划结构检查与测试使用。
    text = plan.read_text(encoding="utf-8", errors="replace")
    return _parse_plan(text)[2]


def plan_has_duplicate_task(plan):
    # [T34/codex#3+对抗B-1c] 重号 `### Task <n>:` 检测（fence-aware）：set 折叠重号会掩盖
    # "一段全勾一段未勾"的假✅；fenced 里的示例标题不算（CR-F2）。
    text = plan.read_text(encoding="utf-8", errors="replace")
    order = _parse_plan(text)[0]
    return len(order) != len(set(order))


def plan_unbalanced_fence(plan):
    # [impl-review-fix CR-F1] EOF 时围栏未闭合（悬空 ```）→ 悬空围栏吞真实项 → fail-safe UNKNOWN。
    text = plan.read_text(encoding="utf-8", errors="replace")
    return _parse_plan(text)[3]


# ────────────────────── 第四道 plan 校验：收尾票（harden-implement-review-loop Task5） ──────────
# [D3/D3b · spec-review-amendment H12/M17 · remove-superpowers-pipeline Task2 起无条件生效]
# plan MUST 恰含一张「实现验证」收尾 ticket（`R-ID: all`）且其 `Blocked-by` ⊇ 全部功能
# ticket 号，否则 UNKNOWN——由 `resolve_plan_path` 定位到的 plan 恒为 `tickets.md`
# （单名 resolver，见其上方注释），本校验不再按文件名分流，旧名 grandfather 跳过分支已随
# 双名探测一并退役。**MUST NOT 被解读为轨道路由**——gate 不读 config/marker 即可执行本校验。
CLOSING_TICKET_R_ID = "all"
# [基准 5：无界语法禁手搓] R-ID 逐 task 提取是本文件目前唯一的「R-ID 字面值」消费点，沿用与
# Blocked-by（impl_route.BLOCKED_BY_RE）同构的「行内前缀 + 加粗可选」写法，仅认这一个字面槽位，
# 不是通用 Markdown 解析器。
_R_ID_RE = re.compile(r"\*{0,2}R-ID:\*{0,2}\s*(.*)$")


def _plan_task_r_ids(text):
    """按 `### Task N:` 分段提取每段首个 `R-ID:` 行的原始值（fence-aware，口径同 `_parse_plan`：
    同一份 FenceTracker + TASK_TITLE_RE）。返回 {task_num_str: raw_value}。仅供
    `plan_closing_ticket_check` 识别「R-ID: all」收尾票用。
    """
    result = {}
    cur = None
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        tm = TASK_TITLE_RE.match(line)
        if tm:
            cur = tm.group(1)
            continue
        if cur is not None and cur not in result:
            m = _R_ID_RE.search(line.strip())
            if m:
                result[cur] = m.group(1).strip()
    return result


def _plan_task_titles_and_bodies(text):
    """按 `### Task N:` 分段提取每段标题（冒号后原文）与段内非 fenced 正文（fence-aware，
    口径同 `_plan_task_r_ids`：同一份 FenceTracker + TASK_TITLE_RE）。返回
    {task_num_str: (title, body_text)}。仅供 `plan_closing_ticket_check` 校验收尾票格式用；
    正文只收 fence 外的行——fenced 块里引用的「聚合」字样不得让格式校验假通过。"""
    titles = {}
    bodies = {}
    cur = None
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        tm = TASK_TITLE_RE.match(line)
        if tm:
            cur = tm.group(1)
            titles[cur] = line[tm.end():]
            bodies[cur] = []
            continue
        if cur is not None:
            bodies[cur].append(line)
    return {tid: (titles[tid], "\n".join(bodies[tid])) for tid in titles}


def _load_parse_blocked_by():
    """惰性 sibling-import `g-implement/scripts/impl_route.py::parse_blocked_by`
    （镜像该文件反向 import 本模块 `FenceTracker` 的手法，见其头注 [impl-review-fix F4]）。

    **MUST 惰性**（函数内 import，不放模块顶层）：本模块此刻已运行到 `decide()`（运行期），自身
    早已执行完毕——此时 import `impl_route`（它又会 sibling-import 本模块）不构成循环导入，
    Python 按模块名解析（`__main__` 直跑场景下会得到本模块的第二份独立实例，同 impl_route.py
    被直接调用时的既有形态一致，无害）；若放在模块顶层，本模块自身尚未执行完时就会触发真循环
    导入。

    基准 5（无界语法禁手搓）：Blocked-by 拓扑解析复用既有单一源 `impl_route.parse_blocked_by`，
    MUST NOT 在本文件手抄第二份。
    """
    scripts_dir = Path(__file__).resolve().parents[2] / "g-implement" / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from impl_route import parse_blocked_by, TopoError  # type: ignore
    return parse_blocked_by, TopoError


def plan_closing_ticket_check(plan):
    """第四道 plan 校验。返回 `(ok, note)`：

    - `ok=True`：`note` 是空串（无条件校验，不再有旧名 grandfather 分支）。
    - `ok=False`：`note` 是拒绝原因，调用方按 UNKNOWN(6) fail-closed 处置。
    """
    text = plan.read_text(encoding="utf-8", errors="replace")
    plan_ids = plan_task_ids(plan)   # 复用既有单一源（set of str），fence-aware
    if not plan_ids:
        return True, ""   # 标题 0 已由更早的判据拦截（UNKNOWN），这里不重复判

    r_ids = _plan_task_r_ids(text)
    closing = [tid for tid in plan_ids
               if r_ids.get(tid, "").lower() == CLOSING_TICKET_R_ID]
    if not closing:
        return False, ("plan 不含「实现验证」收尾 ticket"
                        "（未见任一 Task 段的 R-ID 标注为 all，见 design「收尾票的定位」节）")
    if len(closing) > 1:
        return False, (
            "plan 含多张声明 R-ID: all 的 ticket（Task "
            + ", ".join(sorted(closing, key=int)) + "），收尾票须唯一")
    closing_id = closing[0]

    # [T289] 收尾票格式约束——spec impl-orchestration 已 MUST：收尾 ticket 为「实现验证」票、
    # 验收标准为运行本 change 聚合测试套件；此前只验 R-ID: all + Blocked-by 覆盖，
    # 任意普通功能票伪标 R-ID: all 即可冒充收尾票绕过聚合回归。
    title, body = _plan_task_titles_and_bodies(text).get(closing_id, ("", ""))
    if "实现验证" not in title:
        return False, (
            f"声明 R-ID: all 的 Task {closing_id} 标题（{title.strip() or '空'}）不含「实现验证」"
            "——收尾票须为「实现验证」票，普通功能票 MUST NOT 标 R-ID: all"
            "（见 design「收尾票的定位」节）")
    if "聚合" not in body:
        return False, (
            f"收尾 ticket（Task {closing_id}）验收标准未提及聚合测试套件——"
            "其验收 SHALL 为运行本 change 聚合测试套件（单元+集成+e2e）并全部通过")

    try:
        parse_blocked_by, TopoError = _load_parse_blocked_by()
    except Exception as exc:                                  # noqa: BLE001
        return False, (
            f"收尾票校验无法加载 Blocked-by 拓扑解析器：{type(exc).__name__}: {exc}")
    try:
        deps = parse_blocked_by(text)
    except TopoError as exc:
        return False, f"收尾票校验无法解析 plan 的 Blocked-by 拓扑：{exc}"

    functional_ids = {int(tid) for tid in plan_ids} - {int(closing_id)}
    closing_blocked_by = deps.get(int(closing_id), set())
    missing = functional_ids - closing_blocked_by
    if missing:
        return False, (
            f"收尾 ticket（Task {closing_id}）的 Blocked-by 未覆盖全部功能 ticket 号，"
            f"缺: {sorted(missing)}")
    return True, ""


# [spec-review-amendment H4] branch_state() 已移除：D3 终态判据改 change 域可达性
# （archived_dirs_in_tree + base 树），不再用「当前 HEAD 分支是否并进 base」这一全局近似；
# final 路径（active 存在）恒 RUN_VERIFY 不判 SHIPPED，故也无需 branch_state。detached HEAD
# 对 D3 判定无关（凭 base 树可达仍可 SHIPPED）——旧「detached→UNKNOWN」契约随之废止。


# defer 对账门核验声明的 ID、池文件与 new/reuse 来源，不依赖退役度量锚。

def _fence_outside_text_lines(text):
    """`text` 按行产出 fenced code block 之外的行（str 版）。复用单一源 `FenceTracker`
    （与 `_line_scoped_hits`/`_parse_plan` 同口径——``` 与 ~~~
    两族围栏均识别），供下方锚检测 + defer 台账表格解析共用：围栏内的锚样例/表格样例
    MUST NOT 计入判定。
    """
    fence = FenceTracker()
    for line in text.splitlines():
        if fence.feed(line) or fence.inside:
            continue
        yield line


# ── defer 台账（GFM 表格，有界子集：仅认本仓报告模板会用的「每行首尾 pipe」形态，不追求
#    覆盖任意第三方 markdown 的转义 pipe / 无首尾 pipe 等变体——基准 5，只审自家 producer 产物）──
_TICKET_ID_RE = re.compile(r"^(T\d+|B\d+)$")
_TABLE_ROW_RE = re.compile(r"^\s*\|(.*)\|\s*$")


def _is_table_sep(line):
    """GFM 表格分隔行判据：整行须是 pipe 行，且去外层 pipe 后只含 `-`/`:`/`|`/空白且含 `-`。"""
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return False
    inner = m.group(1)
    return bool(inner) and "-" in inner and set(inner) <= set(" :-|")


def _split_table_row(line):
    return [c.strip() for c in _TABLE_ROW_RE.match(line).group(1).split("|")]


def _defer_ledger_entries(text):
    """扫 report 全文（fence 外）全部 GFM 表格，取表头列名（大小写/首尾空白不敏感）=="id"
    的那一列，产出每条数据行的 (原始 id, 来源)。无「来源」列的旧表按 new 处理；
    有该列却缺值时保留空串，交调用方拒绝。

    台账行判别窄化：只对**声明了 id 列**的表格数据行生效——无 id 列的表格（如 Findings 表）、
    普通段落（含聚合摘要句「defer K 项 → buglist/todolist」这类无 pipe 的散文）一律不产出，
    MUST NOT 全行子串搜索（描述列提及的旧票号、聚合摘要句的 "defer" 字面均不触发本函数）。
    """
    lines = list(_fence_outside_text_lines(text))
    n = len(lines)
    out = []
    i = 0
    while i < n:
        if _TABLE_ROW_RE.match(lines[i]) and i + 1 < n and _is_table_sep(lines[i + 1]):
            header = _split_table_row(lines[i])
            id_col = next((idx for idx, c in enumerate(header) if c.lower() == "id"), None)
            source_col = next((idx for idx, c in enumerate(header) if c == "来源"), None)
            j = i + 2
            rows = []
            while j < n and _TABLE_ROW_RE.match(lines[j]):
                rows.append(_split_table_row(lines[j]))
                j += 1
            if id_col is not None:
                out.extend((r[id_col] if id_col < len(r) else "",
                            (r[source_col] if source_col < len(r) else "") if source_col is not None else "new")
                           for r in rows)
            i = j
        else:
            i += 1
    return out


def _defer_ledger_id_cells(text):
    return [raw for raw, _source in _defer_ledger_entries(text)]


def _pool_metadata(path):
    """读 issues 池文件 frontmatter。复用既有 `_yq()` 的通用
    front-matter 提取（MUST NOT 手搓第二个 frontmatter 解析器——`parse_ship_gate_frontmatter`
    专认顶层 `ship-gate:` 键，池文件 schema 不同，走 `_yq` 的通用路径而非那个专属解析器）。
    表达式取整份 frontmatter（`.`）而非 `.source_change` 直接取子字段——`_yq()` 对
    `front_matter=True` 校验解出结果须为 dict（防坏块被当合法标量采信），子字段表达式解出
    的是标量（str），会误撞这道校验而 raise；取整 dict 后在 Python 侧 `.get()` 规避。
    读取/解析失败 → None，由调用方拒绝引用。
    """
    try:
        state = _yq(".", file=path, front_matter=True, default={})
    except RuntimeError:
        return None
    if not isinstance(state, dict):
        return None
    return state


def guard_defer_ledger(root, change, report_path):
    """B26 defer 对账门。扫报告全部「id」列表格数据行，逐行校验：id 格式合法（整格恰为单个
    T<n>/B<n>）→ 对应池文件**文件系统存在**（`Path.glob`，MUST NOT 走 git 跟踪清单——门在
    commit 前跑，recorder 刚写的池文件可能尚未 `git add`）。new 只查 open 且 source_change
    须等于当前 change；reuse 查 open/closed 中唯一文件并核验 id/pool，保留历史来源。
    任一不满足 ⇒ 返回失败 reason 串（调用方按 STEP_IN_PROGRESS 处置）。

    无「id」列表格（旧散文台账/本轮无 defer）⇒ 视为零待对账项，直接放行——本门不判断
    「有没有 defer」这件事本身，只对账已声明的 id。
    """
    text = _read_report_text(report_path, "code-review 报告")
    for raw, source in _defer_ledger_entries(text):
        if not _TICKET_ID_RE.match(raw):
            return (f"defer 台账行 id 列内容非法（{raw!r}，须整格恰为单个 T<n>/B<n> id）"
                     "——请确认该行 recorder add 已成功并把返回 id 原样写入 id 列")
        if source not in ("new", "reuse"):
            return f"defer 台账 id={raw} 来源须为 new 或 reuse，不得留空或猜测"
        states = ("open", "closed") if source == "reuse" else ("open",)
        hits = [path for state in states
                for path in (root / "openspec" / "issues" / state).glob(f"**/{raw}.md")]
        if not hits:
            return (f"defer 台账 id={raw} 对应池文件 openspec/issues/open/**/{raw}.md "
                     "文件系统不存在——recorder add 可能失败或未落盘")
        if len(hits) != 1:
            return f"defer 台账 id={raw} 对应多个池文件，拒绝歧义引用"
        metadata = _pool_metadata(hits[0])
        if metadata is None:
            return f"defer 台账 id={raw} 池文件 frontmatter 不可解析"
        if source == "reuse" and (metadata.get("id") != raw or
                                  metadata.get("pool") != ("bug" if raw.startswith("B") else "todo")):
            return f"defer 台账 id={raw} 复用池文件的 id/pool 不匹配"
        source_change = metadata.get("source_change")
        if source == "new" and source_change != change:
            return (f"defer 台账 id={raw} 池文件 source_change={source_change!r} "
                     f"≠ 当前 change {change!r}（疑似误抄/复用既有票号，或池文件坏）")
    return None


def decide(root, change):
    # ── git 健全性前置：run_git 吞错会让下游静默失效（D9 等判定悄悄全假）──
    # [impl-review-fix] 先验 git 可用且 --root 确为 git 仓，防止后续所有 run_git
    # 调用因非仓/git 缺失而返回空串，被误判为"文件未提交"等正常态。
    if not run_git(root, "rev-parse", "--git-dir"):
        emit("UNKNOWN", EXIT_UNKNOWN, None,
             "git 不可用或 --root 非 git 仓，无法读盘面")
    cdir = root / "openspec" / "changes" / change
    import branch_context as bc
    if cdir.exists():
        try:
            context = bc.read(root, cdir)
            if context and run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD") != context["work_branch"]:
                raise ValueError("当前不在本 change 的 work_branch，禁止在错误分支继续")
        except (ValueError, OSError) as exc:
            emit("UNKNOWN", EXIT_UNKNOWN, None, f"分支约定无效：{exc}")
    # ── D3 归档终态短路〔B3 + D3 硬化 H1-H6〕: active 缺席时纯 git 域查归档 ──
    # 顺序关键：短路必须在设计门 pre-flight 与 freshness 之前——归档 commit 的 --name-only
    # 会列出 active 路径删除记录，若先跑 freshness 会引入新误报；短路后该路径天然不可达。
    if not cdir.exists():
        # 〔A2〕archive 已发生、归档尚未提交：先于纯 git 域短路识别（否则判「change 不存在」）。
        pending = uncommitted_archive_dirs(root, change)
        if len(pending) > 1:
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 f"工作树里有多个未提交的归档目录（{'、'.join(pending)}），无法判定本次归档 → 人工清理多余目录")
        if pending:
            directory = root / "openspec/changes/archive" / pending[0]
            rel_dir = directory.relative_to(root).as_posix()
            try:
                context = bc.read(root, directory)
                if context and run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD") != context["work_branch"]:
                    raise ValueError("当前不在本 change 的 work_branch，禁止在错误分支提交归档")
            except (ValueError, OSError) as exc:
                emit("UNKNOWN", EXIT_UNKNOWN, None, f"分支约定无效：{exc}")
            vpath = directory / "verify-report.md"
            vtext = _read_report_text(vpath, "归档 verify 报告") if vpath.is_file() else ""
            vstate, verr = parse_ship_gate_frontmatter(vtext)
            if verr is not None or vstate.get("verify") != "PASS":
                emit("UNKNOWN", EXIT_UNKNOWN, None,
                     f"未提交的归档目录 {rel_dir} 缺有效 verify=PASS 锚，不能提交归档；"
                     "核对是否在 verify PASS 之前就跑了 archive")
            mismatch = archived_code_mismatch(root, vtext, "HEAD")
            if mismatch:
                emit("UNKNOWN", EXIT_UNKNOWN, None, mismatch)
            emit("ARCHIVE_UNCOMMITTED", EXIT_OK, "g-done",
                 f"已 openspec archive、归档尚未提交（{rel_dir}）→ 从 archive 第 3 步 delta 核验继续，"
                 "通过后进入 commit", archive_dir=rel_dir)
        base = base_ref(root)
        head_dirs = archived_dirs_in_tree(root, "HEAD", change)   # H2 纯 git 域(工作树无关)
        base_dirs = archived_dirs_in_tree(root, base, change) if base else set()
        for archive_dir in sorted(head_dirs):
            directory = root / "openspec/changes/archive" / archive_dir
            rel_dir = directory.relative_to(root).as_posix()
            try:
                context = bc.read(root, directory, "HEAD")
            except (ValueError, OSError) as exc:
                emit("UNKNOWN", EXIT_UNKNOWN, None, f"归档分支约定无效：{exc}")
            rc, _ = run_git_rc(root, "cat-file", "-e",
                               f"HEAD:openspec/changes/archive/{archive_dir}/.skip-merge")
            # 〔B2〕归档提交 = 最早引入该归档目录的提交；其代码须恰为 verify 锚定的已验证代码。
            first_archive_commit = (run_git(root, "log", "--format=%H", "--reverse", "HEAD", "--", rel_dir)
                                    .splitlines() or [""])[0]
            if context:
                vtext = run_git_rc(root, "show", f"HEAD:{rel_dir}/verify-report.md")[1]
            if context and rc != 0:
                if archived_verify_state(root, "HEAD", archive_dir) != "pass":
                    emit("UNKNOWN", EXIT_UNKNOWN, None, "归档缺有效 verify=PASS，不能结束或合并")
                common = dict(archive_dir=rel_dir, **context)
                if context["merge_target"] is None:
                    mismatch = archived_code_mismatch(root, vtext, first_archive_commit)
                    if mismatch:
                        emit("UNKNOWN", EXIT_UNKNOWN, None, mismatch)
                    emit("SHIPPED", EXIT_OK, None, "已提交归档；未请求合并，留在工作分支。未 push",
                         merge_not_requested=True, completed_in_place=context["work_branch"] == context["source_branch"], **common)
                try:
                    target = bc.target_ref(root, context["merge_target"])
                except ValueError as exc:
                    emit("UNKNOWN", EXIT_UNKNOWN, None, str(exc))
                archive_commit = run_git(root, "log", "-1", "--format=%H", "HEAD", "--", rel_dir)
                merged, _ = run_git_rc(root, "merge-base", "--is-ancestor", archive_commit, target)
                if merged == 0:
                    emit("SHIPPED", EXIT_OK, None, "归档已并入本 change 指定目标。未 push", **common)
                # 待合并的是 work_branch 的 HEAD：其代码须仍是已验证代码（含归档后新增提交的情形）。
                mismatch = archived_code_mismatch(root, vtext, "HEAD")
                if mismatch:
                    emit("UNKNOWN", EXIT_UNKNOWN, None, mismatch)
                emit("RUN_VERIFY", EXIT_OK, "g-done", "已归档，继续合并到本 change 指定目标", **common)
            if rc != 0:
                continue
            state = archived_verify_state(root, "HEAD", archive_dir)
            if state != "pass":
                emit("UNKNOWN", EXIT_UNKNOWN, None,
                     "跳过 merge 的归档缺少有效 verify=PASS 锚，不能判完成")
            if context:
                mismatch = archived_code_mismatch(root, vtext, first_archive_commit)
                if mismatch:
                    emit("UNKNOWN", EXIT_UNKNOWN, None, mismatch)
            emit("SHIPPED", EXIT_OK, None,
                 "归档完成 + verify=PASS；按已提交的 .skip-merge 跳过合并。未 push",
                 merge_skipped=True, archive_dir=f"openspec/changes/archive/{archive_dir}")
        if base is None:
            if head_dirs:
                emit("UNKNOWN", EXIT_UNKNOWN, None,
                     "归档存在于 HEAD 树但默认分支不可解析，无法判是否已并 → 判定不能")
            emit("REFUSE_START", EXIT_REFUSE, None,
                 "change 不存在（active 与 archive 均无）")
        # H1/BR-2: SHIPPED 须归档在 base 树 且 archived verify 锚 tri-state 判定
        base_states = [archived_verify_state(root, base, d) for d in base_dirs]
        if "conflict" in base_states:
            # 归档 verify-report 并存 PASS/FAIL 冲突锚 → 同 active 路径冲突锚判 UNKNOWN 语义〔CV-1〕
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 "归档 verify-report 并存 PASS/FAIL 冲突锚 → 判定不能，请人工裁决删其一")
        if "pass" in base_states:
            emit("SHIPPED", EXIT_OK, None,
                 "全通（归档后重跑识别）：归档已并 base + verify=PASS 锚。"
                 "未 push（手动控制）；toolkit 源仓请 push 后新会话 /g-upgrade 激活")
        if base_dirs:
            # 归档已并 base 但无 verify=PASS 锚（空壳/未验/仅 FAIL）→ fail-safe 不判 SHIPPED〔H1/Q3〕
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 "归档已并 base 但缺 verify=PASS 锚（空壳/未验）→ fail-safe 不判 SHIPPED，请人工核验")
        if head_dirs:
            # H4: detached 无关，凭 base 树可达；仅在 HEAD 树=归档未并 base
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 "旧归档未并入默认分支且缺分支约定，先确认起点和合并目标；禁止自动猜测")
        emit("REFUSE_START", EXIT_REFUSE, None,
             "change 不存在（active 与 archive 均无）")
    # ── pre-flight：设计门（D7 起跑不越门）─────────────────────────
    # [mlh-p5 Task6 D1] live 只读 frontmatter（inline 回退已退役）：design_approved 优先；
    # absent（无 frontmatter / 无 ship-gate 键）→ sr_state=None → design_ok=False → REFUSE_START
    # （既有无锚语义，不回退 inline）；坏 frontmatter → live_ship_gate_state 内 UNKNOWN(6) 已 emit。
    report = cdir / "spec-review-report.md"
    sr_state = live_ship_gate_state(report, "spec-review")   # 坏→UNKNOWN(6) 已 emit；absent→None
    design_ok = sr_state is not None and sr_state.get("design_approved") is True
    if not design_ok:
        # 〔B6〕送设计审之前先要有 g-spec 相位 B 定稿的决策纪要——否则绕过 g-spec 建的 change
        # 可以一路过设计门。next=g-spec 仅供展示：g-spec 需要人参与拷问，g-done 只停不代跑。
        memo_problems = decision_memo_problems(cdir)
        if memo_problems:
            emit("REFUSE_START", EXIT_REFUSE, "g-spec",
                 "缺合格的决策纪要，不能送设计审：" + "；".join(memo_problems)
                 + " → 先跑 /g-spec 完成相位 B（拷问收敛并定稿纪要）")
        emit("REFUSE_START", EXIT_REFUSE, None,
             "未过设计门：spec-review-report.md 缺失或无 design_approved 锚；"
             "先完成设计门。若拍板已发生请人工补锚（显式越权留痕）——"
             # 〔impl-review-fix M9〕原文案列 design_approved+reviewed_sha 两字段、暗示可手写
             # 补齐，而 _read_anchor 实际要求 reviewed_sha+reviewed_manifest 同时存在
             # （二者密码学互锁，MUST NOT 手写）；改为直接指向权威写锚脚本的调用方式，三字段
             # （design_approved/reviewed_sha/reviewed_manifest）由脚本同批原子计算写入，
             # 撞门者按此文案操作不会再落入「手写完两个字段仍缺 reviewed_manifest」的二次踩坑。
             "跑 `anchor_writeback.py --change <name> --report spec-review-report.md "
             "--domain design --set design_approved=true --expected-ref <送审提交>`（同一次写入落盘 "
             "design_approved + reviewed_sha + reviewed_manifest 三字段，锚值由脚本计算，MUST NOT 手写；"
             "送审提交 = 设计审报告记录的、人实际审阅的那个提交，之后设计若再改脚本会拒写）"
             + _unclosed_frontmatter_hint(report))
    # [harden-gate-git-layer Task4 · ADR-3 · tasks 2.5] **求值窗口**：design 域失鲜原本在此处
    # 无条件全阶段求值。现改为只在三个「进入实现期」的分支各自 emit 之前求值
    # （`emit_windowed` 单一实现点）——判据只在它保护的风险真实存在的阶段求值。
    # 这里**有意留空**：任何把检查加回本位置的改动都等于取消窗口限定（见 emit_windowed 头注释）。
    # ── verify 冲突锚早检（坏 frontmatter → UNKNOWN，保步序早停）──
    # [mlh-p5 Task6 D1] live 只读 frontmatter（inline 回退已退役）：坏 frontmatter（含重复
    # verify 键=冲突的等价形态 duplicate-key）→ live_ship_gate_state 内 UNKNOWN(6) emit 早停；
    # 有效单值 / absent 不早停（absent = 无锚语义，留待 step9 判 STEP_IN_PROGRESS）。此调用仅
    # 为副作用（触发坏→UNKNOWN 早检以保步序），返回值有意丢弃。
    vfile = cdir / "verify-report.md"
    if vfile.is_file():
        live_ship_gate_state(vfile, "verify")   # 坏→UNKNOWN(6) 早停；live 只读 frontmatter
    # ── step 6/7：plan 与完成判据〔Q2 窗口主锚〕──────────────────
    # [harden-implement-review-loop Task3 · D5/adr-0033 · remove-superpowers-pipeline Task2]
    # 计划文件名经共享 resolver 定位（单名 tickets.md）；tickets.md 缺席且遗留旧名
    # superpowers-plan.md 单独存在 → fail-closed UNKNOWN（人工清理提示，设计门 Q1）。
    try:
        plan = resolve_plan_path(cdir)
    except LegacyPlanNameFound as exc:
        emit("UNKNOWN", EXIT_UNKNOWN, None, str(exc))
    if plan is None:
        # [Task4 · tasks 2.6] 窗口入口①
        emit_windowed(root, change, report,
                      "RUN_PLAN", EXIT_OK, "g-implement",
                      "计划文件缺（tickets.md 未找到）")
    # [impl-review-fix CR-F1] 未闭合 fenced code block（悬空 ```）→ 悬空围栏会吞掉真实
    # 未勾项与 Task 标题（假✅/漏 task）→ plan 无法可靠解析 → fail-safe UNKNOWN（先于其余判据）。
    if plan_unbalanced_fence(plan):
        emit("UNKNOWN", EXIT_UNKNOWN, None,
             "plan 有未闭合的 fenced code block(```)，悬空围栏吞真实项，完成判据无法可靠解析")
    plan_ids = plan_task_ids(plan)
    n = len(plan_ids)
    if n == 0:
        emit("UNKNOWN", EXIT_UNKNOWN, None,
             "plan 无 '### Task <n>:' 标题（上游模板漂移？），完成判据不能")
    # [ship-gate-hardening-2 T34] 重号 Task 段 → UNKNOWN（set 折叠掩盖一段全勾一段未勾的假✅）
    if plan_has_duplicate_task(plan):
        emit("UNKNOWN", EXIT_UNKNOWN, None,
             "plan 出现重号 '### Task <n>:' 段（手改/复制粘贴），完成判据不可判"
             "——重号折叠会掩盖某段未完成的假✅")
    plan_rel = str(plan.relative_to(root))
    # [harden-implement-review-loop Task5 · H12/M17 · remove-superpowers-pipeline Task2]
    # 第四道校验：收尾票存在性 + Blocked-by 覆盖（无条件生效，见函数注释）。
    plan_ok, plan_note = plan_closing_ticket_check(plan)
    if not plan_ok:
        emit("UNKNOWN", EXIT_UNKNOWN, None, plan_note)
    sha = plan_first_sha(root, plan_rel)
    # [impl-review-fix FIX-1] 🔴 窗口起点自校验：本 change 有完成标签落在 [sha, HEAD] **之外**
    # ⇒ 窗口起点是错的（在途 plan 被重命名 / 两步改名 / 删除重建皆归此），fail-closed 判 UNKNOWN
    # 而非静默漏数放行（旧行为：改名前的完成信号被窗口重置排除、gate 却仍判 CONTINUE_IMPL）。
    # 详见 `stray_done_tag_commits` 头注释（含旧启发式判据的三种实测失效模式）。
    # `sha` 为空 = plan 未提交 ⇒ 根本没有窗口，交由下方未提交计划分支拒绝。
    if sha:
        stray = stray_done_tag_commits(root, sha, change)
        if stray:
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 f"检测到本 change 有 {len(stray)} 个完成标签提交（如 {stray[0][:7]}）落在完成判据"
                 f"窗口 [{sha[:7]}, HEAD] 之外，窗口起点不可信、已完成 ticket 会被判未完成并可能重派；"
                 f"通常是在途 plan（{plan.name}）被重命名 / 删除重建所致"
                 "（MUST NOT 重命名在途 plan，见 design Migration Plan）。"
                 "请把 plan 恢复为其首次提交时的路径，或人工确认后处理")
    # 复选框可先于 checkpoint 落盘；只有已提交的完成标签可以推进恢复执行。
    done = done_task_ids(root, sha, change) if sha else set()
    done_in_plan = done & plan_ids            # [spec-review-amendment B4] 只认计划内号
    if plan_ids - done:                       # 计划内有未完成号 → 未齐（集合归属,非基数）
        if not sha:
            emit("UNKNOWN", EXIT_UNKNOWN, None,
                 (plan_note + "；" if plan_note else "") + "plan 未提交，完成标签窗口不可判；先提交出票产物")
        # 〔A4〕g-implement 的停点 = 在票段内写 `BLOCKED: <原因>`。gate 与 frontier 此前都看不见它，
        # 重调 /g-done 会把同一张被阻塞的票原样重派、「2 轮上限」从零计——停在这里交人。
        blocked = {k: v for k, v in plan_blocked_tickets(
            plan.read_text(encoding="utf-8", errors="replace")).items() if k in plan_ids - done}
        if blocked:
            guard_design_freshness(root, change, report)     # 与窗口内两入口同序：设计失鲜优先
            listing = "；".join(f"Task {k}：{blocked[k]}" for k in sorted(blocked, key=int))
            emit("IMPL_BLOCKED", EXIT_BLOCKED, None,
                 f"实现被阻塞（{listing}）→ 停并交人：人处理阻塞原因后删除 tickets.md 中对应的 "
                 "`BLOCKED:` 行并提交，再重调 /g-done；MUST NOT 自动重派被阻塞的票",
                 blocked_tasks=sorted(blocked, key=int), done_tasks=sorted(done_in_plan, key=int))
        # [Task4 · tasks 2.6] 窗口入口②
        emit_windowed(root, change, report,
                      "CONTINUE_IMPL", EXIT_OK, "g-implement",
                      (plan_note + "；" if plan_note else "")
                      + f"实现进度 {len(done_in_plan)}/{n}（窗口 [{sha[:7] or '-'}, HEAD] 闭区间，集合归属）",
                      done_tasks=sorted(done_in_plan, key=int))
    # ── 〔B1〕实现后的设计漂移：窗口外不阻塞，但 MUST 让人看见 ─────────────────
    # 设计失鲜只在 RUN_PLAN / CONTINUE_IMPL 两个入口拦（代码审期/收尾期修订四件套是合法的，
    # 见 emit_windowed 头注释）。代价是：实现完成后改 design/specs（甚至新增 Requirement）
    # 会被静默带进 verify 与 archive。这里不改窗口，只在后段所有判定的 JSON 里带出
    # `design_drift`（变化路径）并在 reason 追加提示，由 g-done SKILL 停下交人二选一。
    # 设计锚不可读（旧格式等）时不追加提示——窗口内闸门已对它做过 fail-closed 判定。
    try:
        drift_stale, drift_paths, drift_detail = design_drift(root, change, report)
    except GateIndeterminate:
        drift_stale, drift_paths, drift_detail = False, [], ""
    drift_extra = {"design_drift": drift_paths or [drift_detail]} if drift_stale else {}
    drift_note = (f"（⚠ 设计门批准后 design/specs 有改动，见 design_drift：{drift_detail}；"
                  "须交人重审或明确确认）") if drift_stale else ""

    def late(verdict, exit_code, next_step, reason, **extra):
        emit(verdict, exit_code, next_step, reason + drift_note, **drift_extra, **extra)

    # ── step 8：code-review 门 ─────────────────────────────────
    cr = cdir / "code-review-report.md"
    if not cr.is_file():
        late("RUN_CODE_REVIEW", EXIT_OK, "g-code-review",
             (plan_note + "；" if plan_note else "") + "实现完成，进入代码审")
    # [mlh-p5 Task6 D1] live 只读 frontmatter（inline 回退已退役）：code_review 优先
    # （pass→'pos'/blocked→'neg'）；坏→UNKNOWN(6) 已 emit；absent→None→STEP_IN_PROGRESS（无锚语义）。
    cr_front = live_ship_gate_state(cr, "code_review")   # [impl-review-fix FIX-5] label 用下划线，与字段名一致
    if cr_front is not None:
        cv = cr_front.get("code_review")
        cr_state = "pos" if cv == "pass" else "neg" if cv == "blocked" else None
    else:
        cr_state = None                          # absent → 无锚 → STEP_IN_PROGRESS
    cr_rel = str(cr.relative_to(root))
    if cr_state == "neg":
        # 〔A4〕blocked 之后修复已提交（代码域相对 blocked 结论已失鲜）⇒ 重跑代码审，而不是
        # 永远停在 BLOCKED_UPSTREAM（此前修完也解不开，next=null，自动链路卡死）。
        # 报告缺锚（手写 blocked、未经写锚脚本）⇒ 无从判失鲜，维持 BLOCKED_UPSTREAM。
        try:
            blocked_stale, blocked_fresh = is_stale(root, cr_rel, "code", change)
        except GateIndeterminate as exc:
            if exc.category != CAUSE_ANCHOR_MISSING:
                raise
            blocked_stale, blocked_fresh = False, None
        if blocked_stale:
            late("RERUN_STALE", EXIT_OK, "g-code-review",
                 "code-review 判 blocked 之后已有 openspec/ 外新提交（blocker 修复）→ 重跑代码审",
                 freshness=blocked_fresh, reviewed_sha=read_reviewed_sha(root, cr_rel))
        late("BLOCKED_UPSTREAM", EXIT_BLOCKED, None,
             "code-review 判 blocked：按报告修复 P0/P1 并提交代码后重调 /g-done"
             "（代码变化后 gate 判 RERUN_STALE 自动重跑代码审）；需人决策的 blocker 原样交人")
    if cr_state is None:
        late("STEP_IN_PROGRESS", EXIT_OK, "g-code-review",
             "code-review-report.md 在但无锚行 → 该步进行中，重跑"
             + _unclosed_frontmatter_hint(cr))
    # 结论有效后先对账 defer，再检查代码新鲜度。
    defer_problem = guard_defer_ledger(root, change, cr)
    if defer_problem:
        late("STEP_IN_PROGRESS", EXIT_OK, "g-code-review", defer_problem)
    cr_stale, cr_fresh = is_stale(root, cr_rel, "code", change)
    cr_stale_note = None
    if cr_stale:
        # 陈旧判定优先级须让位于「verify=FAIL 之后修代码重验」链路：verify 已判 FAIL
        # 时不要求先重跑 code-review（否则陈旧 FAIL 卡死），留给 step9 判 RERUN_STALE。
        # [mlh-p5 Task6 D1] live 只读 frontmatter（inline 回退已退役）：frontmatter verify==FAIL
        # 优先；坏→UNKNOWN(6) 已在上方 verify 早检 emit（此处同文件不会再遇坏）；absent→非 FAIL。
        vf_peek = cdir / "verify-report.md"
        vp_front = live_ship_gate_state(vf_peek, "verify")
        verify_already_failed = vp_front is not None and vp_front.get("verify") == "FAIL"
        if not verify_already_failed:
            # [impl-review-fix F2] ADR-4：三处 stale 的 emit 都须带 reviewed_sha（补锚值是必要
            # 组成，不是可选优化）——此前只有 design 域（guard_design_freshness）带了，code/verify
            # 两域漏带。`is_stale` 内部已读过一次该报告的锚，这里复用同一 `read_reviewed_sha`
            # 再读一次取值（与 design 域 guard_design_freshness 同一模式，非新造路径），
            # 让撞门者不必先翻报告 frontmatter 抄 sha 就能核对具体差异。
            cr_sha = read_reviewed_sha(root, cr_rel)
            late("RERUN_STALE", EXIT_OK, "g-code-review",
                 "code-review 结论后存在 openspec/ 外提交 → 结论陈旧，重审", freshness=cr_fresh,
                 reviewed_sha=cr_sha)
        # verify 已 FAIL：本轮不在此处抢跳，但把 cr 陈旧状态记下，
        # 传给 step9 的 VERIFY_FAIL 输出（〔任务4 fix 轮 F1〕，避免陈旧信息在此处丢失）。
        cr_stale_note = "（注意：code-review 结论亦已陈旧，修复后需重跑代码审）"
    # ── step 9：verify 终门 ────────────────────────────────────
    vf = cdir / "verify-report.md"
    if not vf.is_file():
        late("RUN_VERIFY", EXIT_OK, "g-done", "进入收尾（verify→hand-off→archive→merge）")
    # [mlh-p5 Task6 D1] live 只读 frontmatter（inline 回退已退役）：verify 优先（PASS→'pos'/
    # FAIL→'neg'）；坏→UNKNOWN(6) 已在 verify 早检 emit；absent→None→STEP_IN_PROGRESS（无锚语义）。
    vf_front = live_ship_gate_state(vf, "verify")
    if vf_front is not None:
        vv = vf_front.get("verify")
        v_state = "pos" if vv == "PASS" else "neg" if vv == "FAIL" else None
    else:
        v_state = None                           # absent → 无锚 → STEP_IN_PROGRESS
    # [harden-gate-git-layer Task1 · ADR-1] 无结论 ⇒ 不求失鲜：`reviewed_sha` 与结论字段
    # **同一次写入落盘**，故「报告在但无结论」这一合法中间态本就没有锚可读——若仍先跑 is_stale，
    # 该态会被判「缺锚 → UNKNOWN(6)」，把一个正常的 STEP_IN_PROGRESS 变成判定不能。
    # 次序改为与上方 code-review 读点一致（先定结论、再求失鲜）。原 OV-2 关心的「未闭合结构
    # 提示不被 stale 分支吞掉」由下面 STEP_IN_PROGRESS 分支自带的 hint 承载，语义不丢。
    if v_state is None:
        late("STEP_IN_PROGRESS", EXIT_OK, "g-done",
             "verify-report.md 在但无锚行 → 该步进行中，重跑"
             + _unclosed_frontmatter_hint(vf))
    v_stale, v_fresh = is_stale(root, str(vf.relative_to(root)), "code", change)
    if v_stale:
        # [impl-review-fix F2] 同上：ADR-4 要求 verify 域 RERUN_STALE 同带 reviewed_sha。
        v_sha = read_reviewed_sha(root, str(vf.relative_to(root)))
        late("RERUN_STALE", EXIT_OK, "g-done",
             "verify 结论后存在 openspec/ 外提交 → 结论陈旧（FAIL 修复后重验不卡死 / PASS 不背书新代码）",
             freshness=v_fresh, reviewed_sha=v_sha)
    if v_state == "neg":
        # 〔A3〕FAIL 只在代码变化后自动失鲜重验；缺口只在 openspec/ 内（证据/报告/勾选）时代码指纹
        # 不变，重调永远停在这里——reason MUST 给出这条恢复路径（经人确认后整份重做 verify）。
        reason = ("verify FAIL：停并上抛缺口清单（报告内）。代码缺口 → 修复并提交代码后重调（自动判 "
                  "RERUN_STALE 重验）；缺口只在 openspec/ 内（证据/报告/tasks 勾选）→ 经人确认补齐后"
                  "按 g-done「verify」整节重跑：重新捕获 verified_ref、整份重写 verify-report.md 并重新写锚")
        extra = {}
        if cr_stale_note:
            reason += cr_stale_note
            extra["cr_freshness"] = "stale"
        late("VERIFY_FAIL", EXIT_VFAIL, None, reason, **extra)
    # ── final：active 存在 + verify PASS → 收尾未完（绝不 SHIPPED）─────
    # [spec-review-amendment H1/HRTG-1] active 目录仍在 = archive 尚未发生（真 archive 移走
    # active）→ 本态至多「待收尾」。真 SHIPPED（归档后）由 decide 开头的 D3 短路识别
    # （active 缺席 + base 树可达 + archived verify=PASS 锚）。旧逻辑凭 archive glob 存在性
    # 判 SHIPPED 会被旧/同名 archive 误触发（HRTG-1 假 SHIPPED），故 active 存在时不判 SHIPPED。
    handoff = (cdir / "hand-off.md").is_file()
    late("RUN_VERIFY", EXIT_OK, "g-done",
         f"verify PASS，收尾未完（hand-off={handoff}；archive+merge 由 g-done，"
         "归档后 SHIPPED 由 gate 短路识别）", freshness=v_fresh)


# [harden-gate-git-layer Task1 · tasks 3.6 · design.md 五行表] 每类原因给**各自可行动**的补救动作。
# MUST NOT 用一句「git 调用失败」打天下——五者的补救动作完全不同，而 UNKNOWN 在 /g-ship
# 链序里的处置正是「停并转述 reason」，reason 空洞 = 撞门者被裸退出码打发。
_INDETERMINATE_ADVICE = {
    CAUSE_GIT_UNAVAILABLE: "git 不在 PATH 或不可执行 → 检查环境、安装 git 后重跑",
    # [T194] 上界值**插值引用同一常量**，MUST NOT 硬编码字面量——两者天然漂移
    # （改 GIT_TIMEOUT_SECONDS 而忘了改文案 ⇒ 撞门者按错误的秒数去判断是不是真挂起）。
    CAUSE_GIT_TIMEOUT: f"git 调用超时（>{GIT_TIMEOUT_SECONDS}s）→ 检查磁盘或网络文件系统是否挂起",
    CAUSE_ANCHOR_MISSING: "该报告缺 reviewed_sha / reviewed_manifest 内容锚字段"
                          " → 重跑写锚脚本（anchor_writeback.py）补锚（结论字段与锚须同一次写入落盘）",
    CAUSE_ANCHOR_INVALID: "reviewed_sha 非 64 位小写 hex（旧 40-hex 格式锚 / 缩写 / HEAD / 坏值），"
                          "或与 reviewed_manifest 不互证"
                          " → 重跑写锚脚本（anchor_writeback.py）重新计算并写入内容锚",
    CAUSE_READ_FAILED: "读取失败（仓损坏 / 权限）→ 检查仓完整性",
    CAUSE_YQ_UNAVAILABLE: "yq 未安装或版本不对（须 mikefarah/yq，非 kislyuk/yq）"
                          " → 按错误信息中的安装方式装好后重跑",

}


def _indeterminate_reason(exc):
    advice = _INDETERMINATE_ADVICE.get(exc.category, "原因未分类 → 人工排查")
    return f"判定不能：{exc.cause}。{advice}"


def main(argv=None):
    p = argparse.ArgumentParser(description="g-done 盘面判官（只读）")
    p.add_argument("--change")
    p.add_argument("--default-branch", action="store_true", help="只读输出统一解析的默认分支与完整 ref（JSON）")
    p.add_argument("--root", default=None)
    a = p.parse_args(argv)
    if not a.change and not a.default_branch:
        p.error("需要 --change 或 --default-branch")
    # [harden-gate-git-layer Task1 · tasks 3.6] `GateIndeterminate` → UNKNOWN(6) 的**唯一**映射点，
    # 〔impl-review-fix F1〕捕获范围是**判定逻辑**（仓根解析 + `decide()`），不是 main() 整个函数体：
    # 上一行 `p.parse_args(argv)` 在 try 之外——`--change` 缺失等用法错误会以 `SystemExit(2)`
    # 逸出契约集 {0,3,4,5,6}，这是**有意**的：argparse 用法错误是「调用方没按契约调用」，不是
    # 「gate 判不出」，两者语义不同，MUST NOT 把 parse_args 塞进 try 让 SystemExit 也走 UNKNOWN(6)
    # ——那会把「你调错了」伪装成「我判不出」，掩盖真正的调用方错误。
    # [Task2] `--root` 缺省时的仓根解析**本身就是一次 git 调用** ⇒ MUST 在 try 内：
    # 放在 try 外时「git 不在 PATH」这条最常见的失败会从第一行就逸出成退出码 1，
    # 恰好绕过为它准备的整套诊断（守卫写了、但主路径够不着 = 假绿的经典形态）。
    try:
        root = Path(a.root) if a.root else Path(
            run_git(Path.cwd(), "rev-parse", "--show-toplevel") or Path.cwd())
        if a.default_branch:
            ref = base_ref(root)
            if ref is None:
                emit("UNKNOWN", EXIT_UNKNOWN, None, "默认分支不可解析，核对 origin/HEAD 与本地分支")
            print(json.dumps({"branch": default_branch(root), "ref": ref}, ensure_ascii=False))
            return
        decide(root, a.change)
    except GateIndeterminate as exc:
        emit("UNKNOWN", EXIT_UNKNOWN, None, _indeterminate_reason(exc),
             cause_category=exc.category)


if __name__ == "__main__":
    main()
