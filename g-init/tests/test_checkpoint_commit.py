"""Tests for assets/hack/checkpoint-commit.sh —— 工作流「过场提交」脚本。
Run with: python3 -m pytest g-init/tests/test_checkpoint_commit.py -v
"""
import subprocess
import pytest
from pathlib import Path

from test_support.windows import bash_executable, bash_path

SCRIPT = Path(__file__).parent.parent / "assets" / "hack" / "checkpoint-commit.sh"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def _init_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    return repo


def _run(cwd, *args):
    return subprocess.run([bash_executable(), bash_path(SCRIPT), *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")


def _subject(repo):
    return _git(repo, "log", "-1", "--pretty=%s").stdout.strip()


class TestCheckpointCommit:
    def test_missing_arg_exits_2(self, tmp_path):
        repo = _init_repo(tmp_path)
        assert _run(repo).returncode == 2

    def test_non_git_dir_exits_2(self, tmp_path):
        d = tmp_path / "notgit"
        d.mkdir()
        assert _run(d, "ff").returncode == 2

    def test_no_changes_skips_without_committing(self, tmp_path):
        repo = _init_repo(tmp_path)
        r = _run(repo, "ff", "desc")
        assert r.returncode == 0
        assert _git(repo, "rev-list", "--all", "--count").stdout.strip() == "0"  # 无提交产生

    def test_commits_untracked_with_conventional_message(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("hi", encoding="utf-8")
        r = _run(repo, "ff", "生成 proposal/design/specs/tasks")
        assert r.returncode == 0
        assert _subject(repo) == "checkpoint(ff): 生成 proposal/design/specs/tasks"

    def test_no_desc_omits_colon(self, tmp_path):
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("hi", encoding="utf-8")
        assert _run(repo, "spec-review").returncode == 0
        assert _subject(repo) == "checkpoint(spec-review)"

    def test_desc_with_shell_metachars_stays_literal(self, tmp_path):
        """注入安全：desc 含 $ / 反引号 / 引号不得被 shell 展开或执行，须逐字进 message。"""
        repo = _init_repo(tmp_path)
        (repo / "a.txt").write_text("hi", encoding="utf-8")
        payload = 'break $HOME `whoami` and "quotes"'
        assert _run(repo, "ff", payload).returncode == 0
        assert _subject(repo) == f"checkpoint(ff): {payload}"


@pytest.mark.parametrize("state", ["staged", "unstaged", "untracked"])
def test_report_checkpoint_rejects_code_changes_without_committing(tmp_path, state):
    repo = _init_repo(tmp_path)
    code = repo / "app.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    before = _git(repo, "rev-parse", "HEAD").stdout
    report = repo / "openspec/changes/demo/verify-report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# PASS\n", encoding="utf-8")
    target = repo / "new.py" if state == "untracked" else code
    target.write_text("VALUE = 2\n", encoding="utf-8")
    if state == "staged":
        _git(repo, "add", "app.py")
    r = _run(repo, "demo:verify", "报告", "--", "openspec/changes/demo/verify-report.md")
    assert r.returncode != 0 and "未提交改动" in r.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout == before
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"


def test_report_checkpoint_preserves_unrelated_staged_documents(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("pass\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "seed")
    report = repo / "openspec/changes/demo/verify-report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# PASS\n", encoding="utf-8")
    unrelated = repo / "openspec/unrelated.md"
    unrelated.write_text("user draft\n", encoding="utf-8")
    _git(repo, "add", "openspec/unrelated.md")
    r = _run(repo, "demo:verify", "报告", "--", "openspec/changes/demo/verify-report.md")
    assert r.returncode == 0, r.stderr
    assert _git(repo, "show", "--pretty=", "--name-only", "HEAD").stdout.strip() == "openspec/changes/demo/verify-report.md"
    assert _git(repo, "diff", "--cached", "--name-only").stdout.strip() == "openspec/unrelated.md"


@pytest.mark.parametrize("path", ["app.py", "openspec/../app.py", "openspec/./report.md"])
def test_report_checkpoint_rejects_outside_or_traversal_paths(tmp_path, path):
    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("pass\n", encoding="utf-8")
    r = _run(repo, "demo:verify", "报告", "--", path)
    assert r.returncode == 2
    assert _git(repo, "rev-list", "--all", "--count").stdout.strip() == "0"
