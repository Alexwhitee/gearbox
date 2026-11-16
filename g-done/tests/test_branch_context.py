"""按变更保存起点：真实分支、归档、合并和 CLI 续跑。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import _git, commit_all, head_sha, mkchange
from test_gate_preflight import run_gate
import branch_context as bc

SCRIPT = Path(bc.__file__)


def cli(repo, action, *args, change="demo"):
    return subprocess.run([sys.executable, str(SCRIPT), action, "--root", str(repo),
                           "--change", change, *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def start(repo, in_place=False, target=None):
    (repo / "app.py").write_text("v1\n")
    commit_all(repo, "master baseline")
    _git(repo, "checkout", "-b", "a")
    (repo / "a-only.py").write_text("branch a feature\n")
    commit_all(repo, "a differs from default")
    base = head_sha(repo)
    if not in_place:
        _git(repo, "checkout", "-b", "feat/demo")
    directory = mkchange(repo)
    result = cli(repo, "init", "--source", "a", "--base", base)
    assert result.returncode == 0, result.stderr
    if target:
        assert cli(repo, "set-target", "--target", target).returncode == 0
    return directory, base


def archive(repo, directory):
    (directory / "verify-report.md").write_text("<!-- ship-gate: verify=PASS -->\n")
    destination = repo / "openspec/changes/archive/2026-11-11-demo"
    destination.parent.mkdir(parents=True, exist_ok=True)
    directory.rename(destination)
    commit_all(repo, "archive verified change")
    return destination


def test_explicit_return_to_starting_branch_not_default(repo):
    directory, base = start(repo, target="a")
    main = _git(repo, "rev-parse", "main").stdout
    (repo / "app.py").write_text("v2\n")
    destination = archive(repo, directory)
    code, state, _ = run_gate(repo)
    assert code == 0 and state["verdict"] == "RUN_VERIFY"
    assert state["merge_target"] == "a" and state["base_sha"] == base
    _git(repo, "checkout", state["merge_target"])
    _git(repo, "merge", "--ff-only", state["work_branch"])
    _, state, _ = run_gate(repo)
    assert state["verdict"] == "SHIPPED"
    assert _git(repo, "branch", "--show-current").stdout.strip() == "a"
    assert _git(repo, "rev-parse", "main").stdout == main
    assert (destination / bc.CONTEXT_FILE).is_file()


def test_in_place_finishes_on_a_without_touching_default(repo):
    directory, base = start(repo, in_place=True)
    main = _git(repo, "rev-parse", "main").stdout
    (repo / "app.py").write_text("v2\n")
    archive(repo, directory)
    for _ in range(2):
        code, state, _ = run_gate(repo)
        assert code == 0 and state["verdict"] == "SHIPPED"
        assert state["completed_in_place"] is True and state["merge_target"] is None
    assert _git(repo, "branch", "--show-current").stdout.strip() == "a"
    assert _git(repo, "rev-parse", "main").stdout == main
    assert state["base_sha"] == base != head_sha(repo)


def test_explicit_other_target_survives_archive_and_resume(repo):
    directory, base = start(repo)
    _git(repo, "branch", "release", "a")
    result = cli(repo, "set-target", "--target", "release")
    assert result.returncode == 0, result.stderr
    archive(repo, directory)
    result = cli(repo, "show")
    assert json.loads(result.stdout)["merge_target"] == "release"
    _, state, _ = run_gate(repo)
    assert state["verdict"] == "RUN_VERIFY" and state["merge_target"] == "release"
    assert state["base_sha"] == base
    _git(repo, "checkout", "release")
    _git(repo, "merge", "--ff-only", "feat/demo")
    assert run_gate(repo)[1]["verdict"] == "SHIPPED"
    assert _git(repo, "rev-parse", "a").stdout.strip() == base


def test_explicit_target_after_in_place_archive_requests_merge(repo):
    directory, _ = start(repo, in_place=True)
    _git(repo, "branch", "release")
    destination = archive(repo, directory)
    assert run_gate(repo)[1]["completed_in_place"]
    assert cli(repo, "set-target", "--target", "release").returncode == 0
    # gate 仍只读已提交的归档约定，不因工作树编辑而提前改变终态。
    assert run_gate(repo)[1]["completed_in_place"]
    commit_all(repo, "explicitly request release merge")
    assert run_gate(repo)[1]["merge_target"] == "release"
    assert json.loads((destination / bc.CONTEXT_FILE).read_text())["source_branch"] == "a"


def test_missing_target_never_falls_back_to_main(repo):
    directory, _ = start(repo, target="a")
    archive(repo, directory)
    _git(repo, "branch", "-D", "a")
    code, state, _ = run_gate(repo)
    assert code == 6 and state["verdict"] == "UNKNOWN"
    assert "不存在" in state["reason"]


def test_wrong_active_branch_is_rejected(repo):
    start(repo)
    commit_all(repo, "save context")
    _git(repo, "checkout", "-b", "other")
    code, state, _ = run_gate(repo)
    assert code == 6 and "work_branch" in state["reason"]
    assert cli(repo, "set-target", "--target", "main").returncode == 6


def test_init_is_idempotent_but_never_overwrites_origin(repo):
    directory, base = start(repo)
    path = directory / bc.CONTEXT_FILE
    original = path.read_bytes()
    assert cli(repo, "init", "--source", "a", "--base", base).returncode == 0
    commit_all(repo, "advance work branch")
    result = cli(repo, "init", "--source", "a", "--base", head_sha(repo))
    assert result.returncode == 6 and "拒绝" in result.stderr
    assert path.read_bytes() == original


@pytest.mark.parametrize("field,value", [("base_sha", "HEAD"), ("base_sha", "0" * 40),
                                         ("merge_target", "--bad"), ("work_branch", "../outside")])
def test_invalid_context_blocks_gate(repo, field, value):
    directory, _ = start(repo)
    path = directory / bc.CONTEXT_FILE
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    code, state, _ = run_gate(repo)
    assert code == 6 and "分支约定" in state["reason"]


def test_legacy_unmerged_archive_does_not_guess_default(repo):
    directory, _ = start(repo)
    (directory / bc.CONTEXT_FILE).unlink()
    archive(repo, directory)
    code, state, _ = run_gate(repo)
    assert code == 6 and "禁止自动猜测" in state["reason"]
    assert cli(repo, "show").returncode == 6


def test_legacy_archive_can_be_explicitly_recovered_without_guessing(repo):
    directory, base = start(repo)
    (directory / bc.CONTEXT_FILE).unlink()
    archive(repo, directory)
    result = cli(repo, "init", "--source", "a", "--base", base, "--target", "a")
    assert result.returncode == 0, result.stderr
    assert run_gate(repo)[1]["verdict"] == "UNKNOWN"
    commit_all(repo, "record confirmed legacy branch choice")
    assert run_gate(repo)[1]["merge_target"] == "a"


def test_branch_context_needs_no_default_branch(repo):
    directory, _ = start(repo, target="a")
    _git(repo, "branch", "-D", "main")
    archive(repo, directory)
    code, state, _ = run_gate(repo)
    assert code == 0 and state["merge_target"] == "a"


def test_invalid_explicit_target_leaves_context_unchanged(repo):
    directory, _ = start(repo)
    original = (directory / bc.CONTEXT_FILE).read_bytes()
    assert cli(repo, "set-target", "--target", "absent").returncode == 6
    assert (directory / bc.CONTEXT_FILE).read_bytes() == original


def test_remote_only_target_is_resolved_without_default_fallback(repo):
    directory, _ = start(repo)
    _git(repo, "update-ref", "refs/remotes/origin/release", "HEAD")
    assert cli(repo, "set-target", "--target", "release").returncode == 0
    archive(repo, directory)
    code, state, _ = run_gate(repo)
    assert code == 0 and state["merge_target"] == "release"
    assert bc.target_ref(repo, "release") == "refs/remotes/origin/release"


def test_new_feature_default_finishes_without_merging_a(repo):
    directory, base = start(repo)
    main = _git(repo, "rev-parse", "main").stdout
    (repo / "app.py").write_text("feature code\n")
    archive(repo, directory)
    for _ in range(2):
        code, state, _ = run_gate(repo)
        assert code == 0 and state["verdict"] == "SHIPPED"
        assert state["merge_not_requested"] is True and state["merge_target"] is None
        assert state["completed_in_place"] is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "feat/demo"
    assert _git(repo, "rev-parse", "a").stdout.strip() == base
    assert _git(repo, "rev-parse", "main").stdout == main


def test_g_reads_legacy_branch_context_after_archive(repo):
    directory, base = start(repo)
    (directory / bc.CONTEXT_FILE).rename(directory / ".sdflow-branch.json")
    original = (directory / ".sdflow-branch.json").read_bytes()
    assert cli(repo, "show").returncode == 0
    assert bc.get(repo, "demo")[1]["base_sha"] == base
    destination = archive(repo, directory)
    code, state, _ = run_gate(repo)
    assert code == 0 and state["verdict"] == "SHIPPED"
    assert (destination / ".sdflow-branch.json").read_bytes() == original
