import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import _git, commit_all, head_sha, write_anchored_report
import resume_context
from test_branch_context import archive, start
from test_gate_impl_progress import approved_change


SCRIPTS = Path(resume_context.__file__).parent
CONSTRAINTS = "## Global Constraints\n\n- MUST 保留已有权限检查。\n"
PLAN = """---
impl-pipeline: tickets
---

~~~~markdown
## Global Constraints
示例约束不进摘录
### Task 99: 示例票
~~~~

{constraints}
### Task 1: 保留订单列表
**Blocked-by:** none
**R-ID:** R1
- [x] 第一张票已提交

### Task 2: 筛选订单
**Blocked-by:** 1
**R-ID:** R2
```markdown
### Task 88: 票内示例保留
```
- [x] 按状态筛选并保留分页
- [x] 拒绝未授权访问

### Task 3: 实现验证
**Blocked-by:** 1,2
**R-ID:** all
- [ ] 聚合测试套件全部通过
"""


def run(repo, script):
    return subprocess.run([sys.executable, "-B", str(SCRIPTS / script), "--root", str(repo),
                           "--change", "demo"], capture_output=True, check=False)


def compare_gate(repo, verdict, exit_code=0):
    direct = run(repo, "ship_gate.py")
    wrapped = run(repo, "resume_context.py")
    assert wrapped.returncode == direct.returncode == exit_code, wrapped.stderr
    assert wrapped.stdout.startswith(direct.stdout)
    assert wrapped.stderr == direct.stderr
    payload = json.loads(direct.stdout.splitlines()[-1])
    assert payload["verdict"] == verdict
    context = wrapped.stdout[len(direct.stdout):].decode("utf-8")
    assert context.strip().startswith(resume_context.HEADER)
    return payload, context


def consumer_state(repo):
    files = {path.relative_to(repo): path.read_bytes() for path in repo.rglob("*")
             if ".git" not in path.relative_to(repo).parts and path.is_file()}
    return files, (repo / ".git/index").read_bytes(), _git(repo, "show-ref", "--head").stdout


@pytest.mark.parametrize("constraints", [CONSTRAINTS, ""])
def test_resume_shows_only_next_ticket_and_preserves_worktree_index_and_refs(repo, constraints):
    start(repo)
    plan = PLAN.format(constraints=constraints)
    before_checkbox = plan.replace("[x] 按状态", "[ ] 按状态").replace("[x] 拒绝", "[ ] 拒绝")
    directory = approved_change(repo, plan=before_checkbox)
    commit_all(repo, "checkpoint(demo:task1-order-list): 已完成")
    (directory / "tickets.md").write_bytes(plan.replace("\n", "\r\n").encode("utf-8"))
    (repo / "app.py").write_text("partial implementation\n", encoding="utf-8")
    reports = directory / "impl-reports"
    reports.mkdir()
    for name in ("task1-order-list.md", "task2-filter-orders.md", "task3-verify.md"):
        (reports / name).write_text("现有证据原文\n", encoding="utf-8")
    before = consumer_state(repo)

    payload, context = compare_gate(repo, "CONTINUE_IMPL")

    assert consumer_state(repo) == before
    assert payload["done_tasks"] == ["1"]
    assert "当前分支 `feat/demo`" in context and head_sha(repo) in context
    assert "### Task 2: 筛选订单" in context
    assert "**Blocked-by:** 1\n**R-ID:** R2" in context.replace("\r\n", "\n")
    assert "### Task 88: 票内示例保留" in context
    assert "按状态筛选并保留分页" in context and "拒绝未授权访问" in context
    assert "task2-filter-orders.md" in context
    assert "task1-order-list.md" not in context and "Task 3" not in context
    assert "示例约束不进摘录" not in context and "现有证据原文" not in context
    assert hashlib.sha256((directory / "tickets.md").read_bytes()).hexdigest() in context
    if constraints:
        assert constraints.strip() in context.replace("\r\n", "\n")
    else:
        assert "design.md` 读取全局硬约束" in context


def test_plan_and_design_gate_use_existing_approval(repo):
    directory, _ = start(repo)
    _, context = compare_gate(repo, "REFUSE_START", 3)
    assert "spec-review-report.md" in context

    approved_change(repo)
    _, context = compare_gate(repo, "RUN_PLAN")
    assert all(name in context for name in ("design.md", "tasks.md", "/specs`"))

    (directory / "design.md").write_text("# 修改已批准设计\n", encoding="utf-8")
    commit_all(repo, "edit design")
    payload, context = compare_gate(repo, "REFUSE_START", 3)
    assert "重审" in payload["reason"] and "spec-review-report.md" in context

    _git(repo, "checkout", "-b", "other")
    payload, context = compare_gate(repo, "UNKNOWN", 6)
    assert "work_branch" in payload["reason"] and "下一张票" not in context


def test_review_and_incomplete_verify_point_to_evidence(repo):
    _, base = start(repo)
    directory = approved_change(repo, plan=PLAN.format(constraints=CONSTRAINTS))
    for number in range(1, 4):
        commit_all(repo, f"checkpoint(demo:task{number}-done): complete")
    _, context = compare_gate(repo, "RUN_CODE_REVIEW")
    assert f"base_sha={base}" in context and "code-review-report.md" in context

    review = "code-review-report.md"
    write_anchored_report(repo, directory, review, head_sha(repo), "code", code_review="blocked")
    _, context = compare_gate(repo, "BLOCKED_UPSTREAM", 4)
    assert review in context

    write_anchored_report(repo, directory, review, head_sha(repo), "code", code_review="pass")
    reports = directory / "impl-reports"
    reports.mkdir()
    (reports / "task3-verify.md").write_text("聚合测试证据\n", encoding="utf-8")
    verify = "verify-report.md"
    (directory / verify).write_text("# 验证报告\n验证中\n", encoding="utf-8")
    payload, context = compare_gate(repo, "STEP_IN_PROGRESS")
    assert payload["next"] == "g-done"
    assert all(name in context for name in (verify, "tasks.md", "/specs`", "task3-verify.md"))

    write_anchored_report(repo, directory, verify, head_sha(repo), "code", verify="FAIL")
    _, context = compare_gate(repo, "VERIFY_FAIL", 5)
    assert verify in context

    write_anchored_report(repo, directory, verify, head_sha(repo), "code", verify="PASS")
    payload, context = compare_gate(repo, "RUN_VERIFY")
    assert payload["freshness"] == "fresh" and "hand-off.md" in context

    (repo / "app.py").write_text("changed after review\n", encoding="utf-8")
    commit_all(repo, "code changes")
    payload, context = compare_gate(repo, "RERUN_STALE")
    assert payload["next"] == "g-code-review" and review in context


@pytest.mark.parametrize("merge", ["target", "leave", "skip"])
def test_archived_context_uses_gate_merge_state(repo, merge):
    directory, _ = start(repo, target=None if merge == "leave" else "a")
    if merge == "skip":
        (directory / ".skip-merge").touch()
    archived = archive(repo, directory)
    before = consumer_state(repo)

    payload, context = compare_gate(repo, "RUN_VERIFY" if merge == "target" else "SHIPPED")

    assert consumer_state(repo) == before
    assert archived.relative_to(repo).as_posix() + "/hand-off.md" in context
    if merge == "target":
        assert "合并目标 `a`" in context
    else:
        flag = "merge_skipped" if merge == "skip" else "merge_not_requested"
        assert payload[flag] and "合并目标" not in context


@pytest.mark.parametrize("changed", ["branch", "head", "plan"])
def test_discards_context_if_snapshot_changes_while_gate_runs(repo, monkeypatch, capsysbinary, changed):
    start(repo)
    directory = approved_change(repo, plan=PLAN.format(constraints=CONSTRAINTS))
    run_child = subprocess.run
    calls = []

    def run_and_change(argv, **kwargs):
        result = run_child(argv, **kwargs)
        if Path(argv[2]).name == "ship_gate.py":
            calls.append(result)
            if changed == "branch":
                _git(repo, "checkout", "-b", "other")
            elif changed == "head":
                commit_all(repo, "concurrent empty checkpoint")
            else:
                with (directory / "tickets.md").open("a", encoding="utf-8") as handle:
                    handle.write("\nchanged during read\n")
        return result

    monkeypatch.setattr(resume_context.subprocess, "run", run_and_change)
    assert resume_context.main(["--root", str(repo), "--change", "demo"]) == 0
    output = capsysbinary.readouterr()
    assert len(calls) == 1 and output.out == calls[0].stdout
    assert "请重新读取 gate" in output.err.decode("utf-8")
