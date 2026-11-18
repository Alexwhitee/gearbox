"""delta_sync_check.py：归档后核对 delta 已同步进主 spec（T390）。"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "delta_sync_check.py"


def _spec(*names):
    body = "".join(f"### Requirement: {n}\n\n系统 SHALL 做 {n}。\n\n#### Scenario: s\n- **WHEN** x\n- **THEN** y\n\n"
                   for n in names)
    return f"# cap Specification\n\n## Purpose\np\n\n## Requirements\n\n{body}"


def _layout(tmp_path, delta_text, main_text=None, cap="cap"):
    root = tmp_path / "openspec"
    archive = root / "changes" / "archive" / "2026-10-21-demo"
    (archive / "specs" / cap).mkdir(parents=True)
    (archive / "specs" / cap / "spec.md").write_text(delta_text, encoding="utf-8")
    (root / "specs").mkdir(parents=True)
    if main_text is not None:
        (root / "specs" / cap).mkdir()
        (root / "specs" / cap / "spec.md").write_text(main_text, encoding="utf-8")
    return archive


def _run(archive):
    return subprocess.run([sys.executable, str(SCRIPT), "--archive-dir", str(archive)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def test_fully_synced_delta_passes(tmp_path):
    delta = ("## ADDED Requirements\n\n### Requirement: 新增\n\nSHALL\n\n"
             "## MODIFIED Requirements\n\n### Requirement: 修改\n\nSHALL\n\n"
             "## REMOVED Requirements\n\n### Requirement: 删掉\n\n"
             "## RENAMED Requirements\n\n- FROM: `### Requirement: 旧名`\n- TO: `### Requirement: 新名`\n")
    r = _run(_layout(tmp_path, delta, _spec("新增", "修改", "新名")))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "✓" in r.stdout


def test_each_gap_kind_is_reported(tmp_path):
    delta = ("## ADDED Requirements\n\n### Requirement: 漏了\n\nSHALL\n\n"
             "## MODIFIED Requirements (补充) [spec-review-amendment]\n\n### Requirement: 追加了两份\n\nSHALL\n\n"
             "## REMOVED Requirements\n\n### Requirement: 没删\n\n"
             "## RENAMED Requirements\n\n- FROM: `### Requirement: 旧名`\n- TO: `### Requirement: 新名`\n")
    r = _run(_layout(tmp_path, delta, _spec("追加了两份", "追加了两份", "没删", "旧名")))
    assert r.returncode == 1
    for needle in ("ADDED 未同步：漏了", "出现 2 次（应替换而非追加）：追加了两份",
                   "REMOVED 仍在主 spec：没删", "RENAMED 旧名仍在主 spec：旧名",
                   "RENAMED 新名在主 spec 出现 0 次：新名"):
        assert needle in r.stdout, r.stdout


def test_new_capability_without_main_spec_is_reported(tmp_path):
    r = _run(_layout(tmp_path, "## ADDED Requirements\n\n### Requirement: 新能力\n\nSHALL\n", None))
    assert r.returncode == 1
    assert "主 spec 不存在" in r.stdout


def test_removed_only_delta_without_main_spec_passes(tmp_path):
    r = _run(_layout(tmp_path, "## REMOVED Requirements\n\n### Requirement: 早没了\n", None))
    assert r.returncode == 0, r.stdout


def test_requirement_lines_inside_code_fence_are_ignored(tmp_path):
    delta = ("## ADDED Requirements\n\n### Requirement: 真的\n\nSHALL\n\n```markdown\n"
             "### Requirement: 示例里的\n```\n")
    r = _run(_layout(tmp_path, delta, _spec("真的")))
    assert r.returncode == 0, r.stdout


def test_rename_name_with_backticks_inside(tmp_path):
    delta = ("## RENAMED Requirements\n\n- FROM: `### Requirement: R12 — 7 份 `_yq()` 一致性`\n"
             "- TO: `### Requirement: R12 — `_yq()` 一致性`\n")
    r = _run(_layout(tmp_path, delta, _spec("R12 — `_yq()` 一致性")))
    assert r.returncode == 0, r.stdout


def test_missing_archive_dir_is_usage_error(tmp_path):
    r = _run(tmp_path / "nope")
    assert r.returncode == 2


# ── 嵌套 capability：schema 鼓励 `identity/user-auth` 这类分层路径，只扫一层会整条漏检、报假 ✓ ──

def test_nested_capability_is_checked(tmp_path):
    r = _run(_layout(tmp_path, "## ADDED Requirements\n\n### Requirement: 登录\n\nSHALL\n",
                     None, cap="identity/user-auth"))
    assert r.returncode == 1, r.stdout
    assert "identity/user-auth: 主 spec 不存在" in r.stdout


def test_nested_capability_synced_passes(tmp_path):
    archive = _layout(tmp_path, "## ADDED Requirements\n\n### Requirement: 登录\n\nSHALL\n", None,
                      cap="identity/user-auth")
    main = tmp_path / "openspec" / "specs" / "identity" / "user-auth"
    main.mkdir(parents=True)
    (main / "spec.md").write_text(_spec("登录"), encoding="utf-8")
    r = _run(archive)
    assert r.returncode == 0, r.stdout


# ── MODIFIED 正文核对：名字归档前就在主 spec 里，只核名字恒过；须比对归档前（HEAD）的需求块 ──

def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})


def _git_layout(tmp_path, before_body, after_body):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "core.autocrlf", "false")
    spec = lambda body: f"# cap\n\n## Requirements\n\n### Requirement: 修改\n\n{body}\n\n### Requirement: 其它\n\nx\n"
    delta = f"## MODIFIED Requirements\n\n### Requirement: 修改\n\n{after_body}\n"
    archive = _layout(tmp_path, delta, spec(before_body))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "before archive")
    (tmp_path / "openspec" / "specs" / "cap" / "spec.md").write_text(spec(after_body), encoding="utf-8")
    return archive


def test_modified_body_replaced_passes(tmp_path):
    archive = _git_layout(tmp_path, "系统 SHALL 旧行为。", "系统 SHALL 新行为。")
    r = _run(archive)
    assert r.returncode == 0, r.stdout


def test_modified_name_only_sync_is_reported(tmp_path):
    archive = _git_layout(tmp_path, "系统 SHALL 旧行为。", "系统 SHALL 新行为。")
    # 手动同步漏改正文：主 spec 回到归档前原样
    (tmp_path / "openspec" / "specs" / "cap" / "spec.md").write_text(
        "# cap\n\n## Requirements\n\n### Requirement: 修改\n\n系统 SHALL 旧行为。\n\n"
        "### Requirement: 其它\n\nx\n", encoding="utf-8")
    r = _run(archive)
    assert r.returncode == 1, r.stdout
    assert "MODIFIED 正文与 HEAD（归档前）相同" in r.stdout and "修改" in r.stdout


def test_modified_check_skipped_when_main_spec_absent_at_base(tmp_path):
    # 非 git 目录（或该 ref 无此文件）⇒ 无从比较，只做名字核对，不误报
    archive = _layout(tmp_path, "## MODIFIED Requirements\n\n### Requirement: 修改\n\nSHALL\n", _spec("修改"))
    r = _run(archive)
    assert r.returncode == 0, r.stdout
