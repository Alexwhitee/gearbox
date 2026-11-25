#!/usr/bin/env python3
"""Append read-only resume context to the existing g-done gate output."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

if __name__ == "__main__":
    sys.dont_write_bytecode = True
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass

import branch_context
import ship_gate as gate


HEADER = "## 续跑上下文"


def snapshot(root, plan):
    branch = gate.run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    head = gate.run_git(root, "rev-parse", "--verify", "HEAD")
    if plan.resolve() != plan:
        raise ValueError("票据路径含符号链接，无法安全摘录")
    return branch, head, plan.read_bytes() if plan.is_file() else None


def global_constraints(text):
    """Preserve the canonical section above the first real Task heading."""
    fence = gate.FenceTracker()
    lines = []
    collecting = False
    for line in text.splitlines():
        if not (fence.feed(line) or fence.inside):
            if gate.TASK_TITLE_RE.match(line):
                break
            if line.rstrip() == "## Global Constraints":
                if lines:
                    return ""
                collecting = True
            elif line.startswith(("# ", "## ")):
                collecting = False
        if collecting:
            lines.append(line)
    return "\n".join(lines).rstrip("\n") if any(line.strip() for line in lines[1:]) else ""


def paths(directory, *names):
    return "、".join(f"`{(directory / name).as_posix()}`" for name in names)


def ticket_reports(directory, task_id):
    return [path.relative_to(directory) for path in sorted(
        (directory / "impl-reports").glob(f"task{task_id}-*.md")
    ) if path.is_file()]


def ticket_context(root, directory, payload, state):
    branch, head, raw_plan = state
    context = branch_context.read(root, directory)
    if not context or not head or branch != context["work_branch"]:
        raise ValueError("请先核对本 change 的分支约定并回到工作分支")
    if raw_plan is None:
        raise ValueError("缺少 tickets.md")

    parse_blocked_by, TopoError = gate._load_parse_blocked_by()
    from impl_route import extract_task_text, next_ready

    plan = raw_plan.decode("utf-8")
    try:
        ready = next_ready(parse_blocked_by(plan), map(int, payload["done_tasks"]))
        if not ready:
            raise ValueError("没有依赖已满足的待办票")
        task = extract_task_text(plan, ready[0])
    except TopoError as exc:
        raise ValueError(str(exc)) from exc
    if task is None:
        raise ValueError(f"缺少 Task {ready[0]} 原文")

    relative = directory.relative_to(root)
    lines = [
        f"- 下一张票 Task {ready[0]} · {paths(relative, gate.PLAN_FILENAMES[0])}",
        f"- 票据 SHA-256 `{hashlib.sha256(raw_plan).hexdigest()}`",
    ]
    reports = ticket_reports(directory, ready[0])
    if reports:
        lines.append(f"- 本票报告 {paths(relative, *reports)}")
    constraints = global_constraints(plan)
    if constraints:
        lines.extend(("", constraints))
    else:
        lines.append(f"- 请从 {paths(relative, 'design.md')} 读取全局硬约束")
    lines.extend(("", task.rstrip("\n")))
    return lines


def verify_materials(root, directory, raw_plan):
    relative = directory.relative_to(root)
    reports = ["impl-reports"]
    if raw_plan is not None:
        for tid, rid in gate._plan_task_r_ids(raw_plan.decode("utf-8")).items():
            if rid.lower() == gate.CLOSING_TICKET_R_ID:
                reports = ticket_reports(directory, tid) or [f"impl-reports/task{tid}-*.md"]
                break
    return [
        f"- 验证材料 {paths(relative, 'tasks.md', 'specs/', 'verify-report.md')}",
        f"- 收尾票证据 {paths(relative, *reports)}",
    ]


def render(root, directory, payload, state):
    branch, head, raw_plan = state
    verdict, next_step = payload["verdict"], payload["next"]
    relative = directory.relative_to(root)
    current = branch or ("detached HEAD" if head else "未解析")
    lines = [f"- 当前分支 `{current}`", f"- HEAD `{head or '未解析'}`"]
    if payload.get("archive_dir"):
        archive = Path(payload["archive_dir"])
        lines.append(f"- 归档材料 {paths(archive, 'hand-off.md', 'verify-report.md')}")
        if payload.get("merge_target"):
            lines.append(f"- 合并目标 `{payload['merge_target']}`")
    elif verdict == "RUN_PLAN":
        lines.append(f"- 出票材料 {paths(relative, 'design.md', 'tasks.md', 'specs/')}")
    elif verdict == "CONTINUE_IMPL":
        lines.extend(ticket_context(root, directory, payload, state))
    elif next_step == "g-code-review" or verdict == "BLOCKED_UPSTREAM":
        context = branch_context.read(root, directory)
        if context:
            lines.append(f"- 固定比较基准 `base_sha={context['base_sha']}`")
        materials = paths(relative, "tasks.md", gate.PLAN_FILENAMES[0], "impl-reports", "code-review-report.md")
        lines.append(f"- 代码审材料 {materials}")
    elif verdict == "RUN_VERIFY" and payload.get("freshness") == "fresh":
        lines.append(f"- 交接材料 {paths(relative, 'verify-report.md', 'hand-off.md')}")
    elif next_step == "g-done" or verdict == "VERIFY_FAIL":
        lines.extend(verify_materials(root, directory, raw_plan))
    elif next_step == "g-spec-review" or (verdict == "REFUSE_START" and directory.is_dir()):
        lines.append(f"- 设计审材料 {paths(relative, 'spec-review-report.md')}")
    elif verdict == "UNKNOWN":
        names = (gate.PLAN_FILENAMES[0], "spec-review-report.md", "code-review-report.md", "verify-report.md")
        existing = [name for name in names if (directory / name).is_file()]
        if existing:
            lines.append(f"- 可核对的材料 {paths(relative, *existing)}")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--change", required=True)
    args = parser.parse_args(argv)
    change = args.change
    if (change in ("", ".", "..") or any(char in change for char in ("/", "\\", "\0"))
            or Path(change).name != change):
        parser.error("change 必须是单一目录名")
    try:
        root = args.root.resolve()
    except (OSError, RuntimeError) as exc:
        parser.error(f"无法解析消费仓根：{exc}")
    directory = root / gate.change_base(change)
    plan = directory / gate.PLAN_FILENAMES[0]
    try:
        before = snapshot(root, plan)
        problem = None
    except (OSError, ValueError, RuntimeError, gate.GateIndeterminate) as exc:
        problem = exc

    try:
        result = subprocess.run(
            [sys.executable, "-B", str(Path(gate.__file__).resolve()), "--root", str(root), f"--change={change}"],
            capture_output=True,
        )
    except OSError as exc:
        print(f"续跑上下文不可用：{exc}", file=sys.stderr)
        return gate.EXIT_UNKNOWN
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)

    try:
        if problem is not None:
            raise problem
        payload = json.loads(result.stdout.rstrip().rsplit(b"\n", 1)[-1])
        lines = render(root, directory, payload, before)
        if snapshot(root, plan) != before:
            raise ValueError("读取期间分支、HEAD 或票据内容已变化，请重新读取 gate")
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError, gate.GateIndeterminate) as exc:
        print(f"续跑上下文不可用：{exc}", file=sys.stderr)
    else:
        print(f"\n{HEADER}\n\n" + "\n".join(lines))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
