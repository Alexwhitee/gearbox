"""retro_report.py — g-retro：从 git 提交历史再生 OpenSpec change 成本复盘（openspec/retro/report.md）。

只读成本维：checkpoint 提交时间线 → 阶段墙钟；spec-review-report.md 的 design_approved 设计门锚
→ 人类门拆分。旧版的价值维（lens-metric 锚）、token 用量（token-log.jsonl）、hr-tg 锚与
per-镜实修率依赖的产出方已随 fan-out / token 快照架构移除，当前流程不再产生这些数据，读侧一并删除。
"""
import argparse
import os
import re
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import tempfile

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-(.+)$")


def discover_changes(root):
    changes_dir = os.path.join(root, "openspec", "changes")
    archive_dir = os.path.join(changes_dir, "archive")
    out = {}
    if os.path.isdir(changes_dir):
        for name in os.listdir(changes_dir):
            p = os.path.join(changes_dir, name)
            if name == "archive" or not os.path.isdir(p):
                continue
            out.setdefault(name, {"active": False, "active_dir": None, "archive_dir": None})
            out[name]["active"] = True
            out[name]["active_dir"] = p
    if os.path.isdir(archive_dir):
        for entry in os.listdir(archive_dir):
            p = os.path.join(archive_dir, entry)
            if not os.path.isdir(p):
                continue
            m = _DATE_PREFIX.match(entry)
            name = m.group(1) if m else entry
            out.setdefault(name, {"active": False, "active_dir": None, "archive_dir": None})
            out[name]["archive_dir"] = p
    return out


def _run_git(root, *args):
    # [T60] git 失败（returncode≠0）向 stderr 留痕——否则「git 报错」与「真无提交」
    # 都表现为空 stdout、静默不可区分（边界解析会把 git 故障误当无历史）。
    # 仍返回 stdout（失败时通常为空）以保持所有调用方契约不变。
    proc = subprocess.run(
        ["git", "-C", root, "-c", "core.quotePath=false", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.stderr.write(
            f"[g-retro] git 失败 (rc={proc.returncode}): git {' '.join(args)}\n"
            f"  stderr: {proc.stderr.strip()}\n")
    return proc.stdout


def git_commits_for_path(root, relpath):
    out = _run_git(root, "log", "--format=%H%x00%ct%x00%s", "--", relpath)
    commits = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x00")
        if len(parts) != 3:
            continue
        sha, ts, subject = parts
        try:
            commits.append({"sha": sha, "ts": int(ts), "subject": subject})
        except ValueError:
            continue
    commits.reverse()  # git log 默认逆序 → 升序
    return commits


def commit_change_dir_count(root, sha):
    out = _run_git(root, "show", "--name-only", "--format=", sha)
    dirs = set()
    for f in out.splitlines():
        m = re.match(r"openspec/changes/(?:archive/\d{4}-\d{2}-\d{2}-)?([^/]+)/", f)
        if m:
            dirs.add(m.group(1))
    return len(dirs)


def seed_mass_shas(root, threshold=3):
    out = _run_git(root, "log", "--format=%H")
    seed = set()
    for sha in out.split():
        if commit_change_dir_count(root, sha) >= threshold:
            seed.add(sha)
    return seed


def boundary_for_change(root, name, info, seed_shas):
    # [impl-review-fix] F1: 致命 bug 修复——归档 change 的 active_dir 在磁盘上已不存在（None），
    # 原实现只 _fetch(active_dir)(None→[]) 再兜底 archive_dir（archive 路径 git log 只看得到
    # rename 后的历史，看不到 rename 前的活动期提交），导致 17/18 归档 change 假性「边界不可解析」。
    # 修法：始终查裸 pre-archive 路径 openspec/changes/<name>（git log 对该 pathspec 历史性可达，
    # 不依赖该目录当前是否还在磁盘/HEAD 上——这是 design D1 的本意）∪ archive 路径（归档 rename
    # 提交只碰 archive 路径），按 sha 去重、按 ts 升序合并。
    def _fetch(relpath):
        if not relpath:
            return []
        cs = git_commits_for_path(root, relpath)
        return [c for c in cs if c["sha"] not in seed_shas]

    by_sha = {}
    for c in _fetch(f"openspec/changes/{name}"):
        by_sha.setdefault(c["sha"], c)
    archive_dir = info.get("archive_dir")
    if archive_dir:
        arel = os.path.relpath(archive_dir, root)
        for c in _fetch(arel):
            by_sha.setdefault(c["sha"], c)
    merged = sorted(by_sha.values(), key=lambda c: c["ts"])

    if len(merged) <= 1:
        return {"commits": merged, "unresolved": True,
                "note": f"边界不可解析（提交数={len(merged)}，seed/单步 change）"}
    return {"commits": merged, "unresolved": False, "note": ""}


# 最长前缀词表：按前缀长度降序尝试匹配 checkpoint(<inner>)
_STAGE_RULES = [
    ("impl-review", "code-review"),
    ("final-review", "code-review"),
    ("sdd-final-review", "code-review"),
    ("spec-review", "spec-review"),
    ("design-gate", "spec-review"),
    ("writing-plans", "impl"),
    ("model-baseline", "impl"),
    # [impl-review-fix] F6: 补前缀——本仓真实存在 checkpoint(done-archive)/checkpoint(done-verify)/
    # 裸 checkpoint(gate) 提交，原词表无匹配落 unknown 桶；F1 修复后归档 change 的 done 阶段提交
    # 会大量出现，须能正确归类。gate 归 spec-review 因 design-gate 已归 spec-review，裸 gate 同族。
    ("done-archive", "done"),
    ("done-verify", "done"),
    ("gate", "spec-review"),
    # `g-` 前缀的 skill 名式 slug。**MUST 各自单列**——匹配是 `startswith`，
    # 「grill」不是 `g-spec-grill` 的前缀，靠既有词表这一族全落 unknown（dogfood 实测）。
    # 相位 B（对抗拷问）同族于 grill；相位 C（生成四件套）同族于 ff（旧三入口里由 ff 承担同一产出）。
    # [impl-review-fix] F1（面治）：`g-code-review`（仓内 3 次）/ `g-spec-review`（1 次）
    # 与上两条**同形**，上一轮只补了 g-spec-* 两条 ⇒ 一并补齐，别再留同族漏网格。
    ("g-spec-grill", "grill"),
    ("g-spec-generate", "ff"),
    ("g-code-review", "code-review"),
    ("g-spec-review", "spec-review"),
    # 2026-11 内联精简：g-review / g-done 的 `<change>:<step>` 新 slug。
    ("code-review", "code-review"),
    ("verify", "done"),
    ("merge-request", "done"),
    ("grill", "grill"),
    ("ff", "ff"),
    ("propose", "other"),
    ("plan", "other"),
    ("roadmap", "other"),
    ("issues", "other"),
]
_CKPT_RE = re.compile(r"^checkpoint\(([^)]*)\)")

# [impl-review-fix fix2] F-B：tail 回退里，**短**规则按 token 匹配而非裸前缀匹配。
# `gate` / `ff` / `plan` 这三条是词不是前缀 —— 裸 startswith 会把 `gateway-refactor` /
# `ffmpeg-upgrade` / `planner` 静默吞进 spec-review / ff / other。4 是当前最短规则族的长度
# （`gate`/`plan` 4 字符、`ff` 2 字符），再长的规则（`grill` 起）自带足够特异性。
_TAIL_STRICT_MAXLEN = 4


def _prefix_hit(candidate, prefix, *, token_boundary):
    """`candidate` 是否命中规则 `prefix`；`token_boundary` 时短前缀须全等或后接 `-`。"""
    if not candidate.startswith(prefix):
        return False
    if token_boundary and len(prefix) <= _TAIL_STRICT_MAXLEN:
        rest = candidate[len(prefix):]
        return rest == "" or rest.startswith("-")
    return True


def map_stage(subject):
    m = _CKPT_RE.match(subject.strip())
    if not m:
        return "unknown"
    inner = m.group(1)
    if inner.startswith("sdflow-"):
        inner = "g-" + inner[len("sdflow-"):]
    # 命名空间任务标签 <change>:task<N>-... → impl
    tail = inner.split(":", 1)[1] if ":" in inner else inner
    if re.match(r"task\d+", tail) or tail.endswith("-impl"):
        return "impl"
    # 最长前缀匹配：规则按前缀长度降序。
    # 先拿整串 `inner` 试（保住 `<change>` 名本身就带阶段词的既有语义），
    # [impl-review-fix] F1：整串无命中 ⇒ **回退用剥掉命名空间的 `tail` 再试一次**。
    # 目标态 producer 就在产出 `checkpoint(<change>:<step>)`（`g-implement/SKILL.md:287`
    # 明写 `checkpoint-commit.sh "<change>:plan"`），旧实现只在 task/-impl 两条判定里剥前缀，
    # 前缀匹配却拿整串比 ⇒ `<step>` 精确等于既有规则的 27 个 checkpoint 全落 unknown。
    # [impl-review-fix fix2] F-B：回退这一跳（且**仅**这一跳）要求短前缀落在 token 边界上，
    # 整串 `inner` 的匹配语义一字未动（change 名本身带阶段词的既有归类照旧）。
    ordered = sorted(_STAGE_RULES, key=lambda r: -len(r[0]))
    for candidate, token_boundary in ((inner, False), (tail, True)):
        for prefix, stage in ordered:
            if _prefix_hit(candidate, prefix, token_boundary=token_boundary):
                return stage
    if inner.endswith("-cross-review") or tail.endswith("-cross-review"):
        return "other"
    return "unknown"


def is_archive_rename(root, sha, name):
    # [impl-review-fix] F5: name in p 是裸子串匹配，foo 会误配 foo-2 的归档路径；
    # 改用目录边界锚定（archive/YYYY-MM-DD-<name>/ 或整段结尾），F1 修复后 pre-archive 全历史
    # 回归、跨 change 提交交集变多，这个雷会被引爆，故一并锚定。
    archive_pat = re.compile(rf"changes/archive/\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(name)}(/|$)")
    out = _run_git(root, "show", "--name-status", "--format=", sha)
    moved_out = False
    into_archive = False
    for line in out.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        status = cols[0]
        paths = cols[1:]
        if status.startswith("R") and len(paths) == 2:
            src, dst = paths
            if f"changes/{name}/" in src and archive_pat.search(dst):
                return True
        if status == "D" and any(f"changes/{name}/" in p and "/archive/" not in p for p in paths):
            moved_out = True
        if status == "A" and any(archive_pat.search(p) for p in paths):
            into_archive = True
    return moved_out and into_archive


# adr/0009(c)：人类门的等待时间单列。两类机器锚：
#   1. grill 类 checkpoint——区间落在 stage=="grill" 上（相位 B 对抗拷问，对话等待）；
#   2. 设计门拍板——spec-review-report.md frontmatter 首次出现 `design_approved: true` 的提交
#      （find_design_approval_sha），其前驱→该提交的区间为人读报告并拍板。
# 判据用 checkpoint 阶段与文件内容，不用 subject 文本。
HUMAN_GATE_GRILL = "grill"
HUMAN_GATE_DESIGN = "design-gate"
_APPROVED_RE = re.compile(r"(?m)^[ \t]*design_approved:[ \t]*true[ \t]*$")


def find_design_approval_sha(root, name):
    """返回该 change 首次把 spec-review-report.md 写成 `design_approved: true` 的提交 sha；
    找不到返回 None。只查归档前路径（拍板发生在归档之前，git 对该 pathspec 历史可达）。"""
    rel = f"openspec/changes/{name}/spec-review-report.md"
    out = _run_git(root, "log", "--reverse", "--format=%H", "-G", "design_approved", "--", rel)
    for sha in out.split():
        # 命中提交可能是删除/改名该文件的提交（该 sha 下路径不存在）⇒ 静默当空，不走 _run_git 的 stderr 留痕
        proc = subprocess.run(["git", "-C", root, "show", f"{sha}:{rel}"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode == 0 and _APPROVED_RE.search(proc.stdout):
            return sha
    return None


def stage_walltimes(root, name, commits, approval_sha=None):
    """
    计算相邻 commit 时间差累加到各阶段的墙钟数。

    [absorb-gstack-autoplan] attribute-to-next：checkpoint 语义 = 工作完成点，
    区间 [cur,nxt) 的墙钟归其**完成点** nxt 的阶段（不是起点 cur 的阶段）——修正既有错账：
    旧口径下 checkpoint(g-spec-generate)→checkpoint(spec-review-autoplan) 区间因
    cur=g-spec-generate 映射 stage="ff" 而把 Step1 广审墙钟误归 ff；新口径下该区间归
    nxt 的阶段（spec-review-autoplan→spec-review），归属正确。

    Args:
        root: 项目根目录
        name: change 名称
        commits: 升序 commit list，每个包含 {"sha", "ts", "subject"}

    Returns:
        {"stages": {stage: minutes}, "total_min": float, "n_ckpt": int, "reorder_suspected": bool}
    """
    stages = {}
    human = {}  # 人类门等待分钟：{HUMAN_GATE_*: min}，已包含在 stages 里，另行拆出
    reorder = False

    # 相邻提交差计入后一个提交（完成点）的阶段
    for i in range(len(commits) - 1):
        cur, nxt = commits[i], commits[i + 1]
        delta_s = nxt["ts"] - cur["ts"]

        # 负数 → 钳 0 且标记 reorder
        if delta_s < 0:
            delta_s = 0
            reorder = True

        # 完成本区间的提交（nxt）的阶段
        if is_archive_rename(root, nxt["sha"], name):
            stage = "done"
        else:
            stage = map_stage(nxt["subject"])

        # 累加到该阶段（秒转分钟）
        stages[stage] = stages.get(stage, 0.0) + delta_s / 60.0

        # 人类门拆分（互斥计一次）：拍板提交优先，其余按 grill 阶段
        if approval_sha and nxt["sha"] == approval_sha:
            human[HUMAN_GATE_DESIGN] = human.get(HUMAN_GATE_DESIGN, 0.0) + delta_s / 60.0
        elif stage == HUMAN_GATE_GRILL:
            human[HUMAN_GATE_GRILL] = human.get(HUMAN_GATE_GRILL, 0.0) + delta_s / 60.0

    # 首提交若是 archive rename，单独标记 done 存在（无前驱 Δ 可归属——对称于旧口径下
    # 末提交的等价边界情形，旧口径末提交从不作为 cur、新口径首提交从不作为 nxt）
    if commits and is_archive_rename(root, commits[0]["sha"], name):
        stages.setdefault("done", 0.0)

    total = sum(stages.values())
    human_total = sum(human.values())
    # 扣除后的阶段墙钟：拍板等待从其所在阶段扣，grill 阶段整体视为人类门
    stages_excl = dict(stages)
    if HUMAN_GATE_DESIGN in human:
        # 拍板提交的阶段（通常 spec-review）按其区间扣；此处按阶段名重算
        for i in range(len(commits) - 1):
            if commits[i + 1]["sha"] == approval_sha:
                st = "done" if is_archive_rename(root, approval_sha, name) \
                    else map_stage(commits[i + 1]["subject"])
                d = max(commits[i + 1]["ts"] - commits[i]["ts"], 0) / 60.0
                stages_excl[st] = max(stages_excl.get(st, 0.0) - d, 0.0)
    if HUMAN_GATE_GRILL in human:
        stages_excl[HUMAN_GATE_GRILL] = max(
            stages_excl.get(HUMAN_GATE_GRILL, 0.0) - human[HUMAN_GATE_GRILL], 0.0)
    return {
        "stages": stages,
        "total_min": round(total, 1),
        "n_ckpt": len(commits),
        "reorder_suspected": reorder,
        "human_gate": {k: round(v, 1) for k, v in human.items()},
        "human_gate_min": round(human_total, 1),
        "stages_excl_human": stages_excl,
        "total_excl_human_min": round(total - human_total, 1),
    }


def _stage_col(wt, stage):
    """[impl-review-fix F12] per-change 表阶段 Δ 列格式化——0 或缺失均显 "—"，
    非 0 时四舍五入 1 位小数，与其余 "—" 空箱口径一致。"""
    v = wt["stages"].get(stage, 0)
    return round(v, 1) if v else "—"


# ============================ 一览（语义化总结）============================
# 阶段内部键→中文可读名。仅影响顶部「一览」段的呈现，不改动下方明细表口径
# （明细表沿用内部键，便于与 checkpoint 提交逐条核对）。
STAGE_LABELS = {
    "spec-review": "设计审", "code-review": "代码审", "impl": "写实现",
    "grill": "grill 死磕", "ff": "ff 生成", "done": "收尾",
    "other": "其他", "unknown": "未归类",
}


def _fmt_dur(minutes):
    """分钟→可读时长：≥60 分显 x.x hr；≥1 分显整数 min；亚分钟保留 1 位小数
    （不 round 成 "0 min" 骗人——0.2min 的 plan 桩 change 如实显 "0.2 min"）。"""
    if minutes >= 60:
        return f"{minutes / 60:.1f} hr"
    if minutes >= 1:
        return f"{round(minutes)} min"
    return f"{minutes:.1f} min"


def semantic_summary(N, K, stage_totals, cost_items, human_total):
    """确定性条件模板：把已算好的聚合组织成「## 一览」（精简指标卡 + 语义化中文段落）。

    **只呈现不决策**（本 skill 宪法）：只做数字的语言化复述与结构性对比
    （占几成 / 相差几倍 / 谁最重），绝不含因果归因或取舍建议——模板里不出现
    「说明 / 意味着 / 因此 / 所以 / 应 / 建议 / 该砍」等解读或决策词。指标卡只放
    纯计数（不放平均值：重尾双峰分布下平均会掩盖真相，与聚合②立意冲突）。
    全部分支确定性；无墙钟 / 单 change / 全部边界不可解析 均有降级句，不崩。
    """
    grand = sum(stage_totals.values())
    total_cell = f"~{_fmt_dur(grand)}" if grand > 0 else "—"
    human_cell = f"~{_fmt_dur(human_total)}" if human_total > 0 else "—"
    card = [
        "| 复盘 change | 总墙钟 | 人类门 | 边界不可解析 |",
        "|---|---|---|---|",
        f"| {N} | {total_cell} | {human_cell} | {K} |",
    ]

    s1 = f"本轮复盘覆盖 **{N} 个 change**"
    if grand > 0:
        s1 += f"，累计流程墙钟约 **{_fmt_dur(grand)}**"
        if human_total > 0:
            s1 += f"（其中人类门约 {_fmt_dur(human_total)}）"
    s1 += "。"
    sents = [s1]

    if grand > 0:
        top = sorted(stage_totals.items(), key=lambda kv: -kv[1])[:2]
        top_str = "、".join(f"{STAGE_LABELS.get(s, s)} {m / grand:.0%}" for s, m in top)
        s2 = f"时间集中在 {top_str}"
        if len(top) == 2:
            s2 += f"（两者合计 {(top[0][1] + top[1][1]) / grand:.0%}）"
        sents.append(s2 + "。")

    valid = [(n, t) for n, t, unresolved in cost_items if t > 0 and not unresolved]
    if len(valid) >= 2:
        hi, lo = max(valid, key=lambda x: x[1]), min(valid, key=lambda x: x[1])
        s3 = (f"单个 change 耗时最重的是 {hi[0]}（约 {_fmt_dur(hi[1])}）、"
              f"最轻的是 {lo[0]}（{_fmt_dur(lo[1])}）")
        # 倍数仅在最轻 change 墙钟 ≥1min 时给：亚分钟 elapsed 是提交时间戳噪声，
        # 拿它当分母算出的倍数无意义（如 0.2min→3769 倍），如实略去不编造。
        if lo[1] >= 1 and hi[1] / lo[1] >= 2:
            s3 += f"，相差约 {round(hi[1] / lo[1])} 倍"
        sents.append(s3 + "。")
    elif len(valid) == 1:
        sents.append(f"仅 {valid[0][0]} 有可解析墙钟（约 {_fmt_dur(valid[0][1])}）。")

    return "\n".join(["## 一览", "", *card, "", "".join(sents), ""])


def build_report(root):
    """组装全项目 change 成本复盘报告（view-only 再生，无持久状态）。

    数据只取当前流程确定会产出的两类机器信号：checkpoint 提交时间线（阶段墙钟）与
    spec-review-report.md 的 `design_approved: true` 设计门锚（人类门拆分）。顶部覆盖计数
    「覆盖 N change / 边界不可解析 K」；per-change 表含 in-progress/archived 状态；
    聚合段①阶段占比②成本双峰。
    """
    changes = discover_changes(root)
    seed = seed_mass_shas(root)
    rows, K = [], 0
    stage_totals = {}
    human_total = 0.0
    for name, info in sorted(changes.items()):
        b = boundary_for_change(root, name, info, seed)
        wt = stage_walltimes(root, name, b["commits"],
                             approval_sha=find_design_approval_sha(root, name)) \
            if not b["unresolved"] else \
            {"stages": {}, "total_min": 0.0, "n_ckpt": len(b["commits"]), "reorder_suspected": False,
             "human_gate": {}, "human_gate_min": 0.0, "stages_excl_human": {},
             "total_excl_human_min": 0.0}
        if b["unresolved"]:
            K += 1
        for stage, minutes in wt["stages"].items():
            stage_totals[stage] = stage_totals.get(stage, 0.0) + minutes
        human_total += wt["human_gate_min"]
        rows.append((name, info, b, wt))
    N = len(changes)

    cost_items = [(nm, w["total_min"], bb["unresolved"]) for nm, _inf, bb, w in rows]
    summary_md = semantic_summary(N, K, stage_totals, cost_items, human_total)

    lines = ["# 全项目 change 成本复盘（view-only 再生）", "",
             f"> 覆盖 {N} change / 边界不可解析 {K}",
             "> 阶段墙钟为「阶段级 elapsed（含人读/拍板/生成时间）」口径（adr/0009），非纯 agent 耗时。",
             "> 「人类门」= grill 阶段区间 + 设计门拍板区间（spec-review-report.md 首次 design_approved: true 的提交），"
             "已含在总墙钟与阶段 Δ 内；「扣除后」列为减去人类门后的值。",
             "> 只统计当前流程确定产出的信号（checkpoint 提交时间线 + 设计门锚）；评审价值维"
             "（逐镜发现数与采纳情况）当前流程没有机读锚，本报告不呈现。",
             "", summary_md]

    lines.append("## per-change 明细")
    lines.append("")
    lines.append("| change | 总墙钟(min) | 人类门(min) | 扣除后总墙钟(min) | spec-rev Δ | spec-rev Δ(扣除后) | "
                 "impl Δ | code-rev Δ | done Δ | #ckpt | 状态 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for name, info, b, wt in rows:
        status = "in-progress" if info["active"] and not info["archive_dir"] else "archived"
        note = "（边界不可解析）" if b["unresolved"] else ""
        lines.append(f'| {name} | {wt["total_min"]}{note} | '
                     f'{wt["human_gate_min"] or "—"} | {wt["total_excl_human_min"]} | '
                     f'{_stage_col(wt, "spec-review")} | '
                     f'{_stage_col({"stages": wt["stages_excl_human"]}, "spec-review")} | '
                     f'{_stage_col(wt, "impl")} | '
                     f'{_stage_col(wt, "code-review")} | {_stage_col(wt, "done")} | '
                     f'{wt["n_ckpt"]} | {status} |')
    lines.append("")

    # 聚合①阶段占比
    lines.append("## 聚合① 阶段占比")
    lines.append("")
    grand_total = sum(stage_totals.values())
    if grand_total > 0:
        lines.append("| 阶段 | 墙钟(min) | 占比 |")
        lines.append("|---|---|---|")
        for stage, minutes in sorted(stage_totals.items(), key=lambda kv: -kv[1]):
            pct = f"{minutes / grand_total:.0%}"
            lines.append(f"| {stage} | {round(minutes, 1)} | {pct} |")
    else:
        lines.append("> 无可用阶段墙钟数据（全部边界不可解析或无 change）。")
    lines.append("")

    # 聚合②成本双峰：总墙钟 x vs code-review 占比 y
    lines.append("## 聚合② 成本双峰（总墙钟 x / code-review 占比% y）")
    lines.append("")
    lines.append("| change | 总墙钟(min) | code-review 占比 |")
    lines.append("|---|---|---|")
    for name, info, b, wt in rows:
        total = wt["total_min"]
        cr = wt["stages"].get("code-review", 0.0)
        pct = f"{cr / total:.0%}" if total else "—"
        lines.append(f"| {name} | {total} | {pct} |")
    lines.append("")

    return "\n".join(lines) + "\n"


def atomic_write(path, text):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            # 新文件与普通创建一致取 0o666 & ~umask，不写死 mode
            um = os.umask(0)
            os.umask(um)
            mode = 0o666 & ~um
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main(argv=None):
    ap = argparse.ArgumentParser(description="g-retro：再生 openspec/retro/report.md（只读成本复盘）")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    md = build_report(root)
    out = os.path.join(root, "openspec", "retro", "report.md")
    atomic_write(out, md)
    print(f"[g-retro] 复盘报告已再生 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
