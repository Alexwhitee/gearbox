"""setup.sh 的 Claude 落点与 Windows 规则根指针：真跑安装器（迷你源仓 + 隔离 HOME），两平台都跑。

- Claude 侧 skills 落点 = ${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills（与 Claude Code、init.py 的 hook
  落点同口径）；~/.agents/skills 不受影响。
- Windows：~/.g/workflow-path 指向任一本工具 checkout 布局即自属、可接管；非自属指针只跳过指针本身，
  hack 脚本照装（曾经整段 return，连 hack 一并跳过）。
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from test_support.windows import bash_executable, bash_path

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def farm(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    shutil.copy2(REPO / "setup.sh", src / "setup.sh")
    (src / "hack").mkdir()
    shutil.copy2(REPO / "hack" / "setup-dependencies.sh", src / "hack" / "setup-dependencies.sh")
    (src / "hack" / "sync_principles.py").write_text("# preflight fixture\n", encoding="utf-8")
    (src / "alpha").mkdir()
    (src / "alpha" / "SKILL.md").write_text("alpha\n", encoding="utf-8")
    (src / "g-init" / "assets" / "workflow").mkdir(parents=True)
    (src / "g-init" / "assets" / "workflow" / "workflow.md").write_text("rules\n", encoding="utf-8")
    (src / "g-init" / "assets" / "hack").mkdir(parents=True)
    (src / "g-init" / "assets" / "hack" / "demo.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    git = ["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@e.invalid"]
    subprocess.run(["git", "init", "-q", str(src)], check=True, capture_output=True)
    subprocess.run(git + ["add", "."], check=True, capture_output=True)
    subprocess.run(git + ["commit", "-qm", "init"], check=True, capture_output=True)
    home = tmp_path / "home"
    home.mkdir()

    def run(claude_config_dir=None):
        env = dict(os.environ, HOME=bash_path(home), USERPROFILE=str(home), G_HOME=bash_path(home / ".g"))
        env.pop("CLAUDE_CONFIG_DIR", None)
        if claude_config_dir is not None:
            env["CLAUDE_CONFIG_DIR"] = str(claude_config_dir)   # Windows 上即原生反斜杠路径
        r = subprocess.run([bash_executable(), bash_path(src / "setup.sh")], cwd=str(src), env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    return src, home, run


def test_claude_skills_follow_claude_config_dir(farm, tmp_path):
    _, home, run = farm
    ccd = tmp_path / "custom-claude"
    run(claude_config_dir=ccd)
    assert (ccd / "skills" / "alpha" / "SKILL.md").is_file()
    assert not (home / ".claude" / "skills").exists(), "设置了 CLAUDE_CONFIG_DIR 仍装进 ~/.claude"
    assert (home / ".agents" / "skills" / "alpha" / "SKILL.md").is_file()


def test_claude_skills_default_to_home_dot_claude(farm):
    _, home, run = farm
    run()
    assert (home / ".claude" / "skills" / "alpha" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "alpha" / "SKILL.md").is_file()


def test_retired_agent_definitions_are_removed_under_claude_home(farm, tmp_path):
    """子代理定义已退役（源仓无 g-spec/agents/）：上一趟本安装器铺出的定义（manifest 有记）被撤下，
    第三方文件不动。Windows 为 copy 形态、Unix 为软链形态，两平台各走各的归属判据。"""
    _, _, run = farm
    ccd = tmp_path / "custom-claude"
    dest = ccd / "agents"
    dest.mkdir(parents=True)
    names = ("g-spec-writer.md", "g-web-researcher.md")
    if os.name == "nt":
        for name in names:
            (dest / name).write_text("old copy\n", encoding="utf-8")
    else:
        old = tmp_path / "old-checkout" / "g-spec" / "agents"
        old.mkdir(parents=True)
        for name in names:
            (old / name).write_text("old\n", encoding="utf-8")
            os.symlink(str(old / name), dest / name)
    # 与 setup.sh 的 printf 同为 LF（write_text 在 Windows 上会写成 CRLF，read -r 读到带 \r 的名字）
    (dest / ".g-agents").write_bytes(("\n".join(names) + "\n").encode("utf-8"))
    (dest / "third-party.md").write_text("mine\n", encoding="utf-8")

    out = run(claude_config_dir=ccd)

    for name in names:
        assert not (dest / name).exists() and not (dest / name).is_symlink(), f"{name} 没被撤下"
        assert f"agents/{name} @" in out
    assert (dest / "third-party.md").read_text(encoding="utf-8") == "mine\n"


windows_only = pytest.mark.skipif(os.name != "nt", reason="workflow-path 指针只在 Windows copy 模式使用")


@windows_only
def test_workflow_path_of_another_checkout_is_taken_over(farm):
    src, home, run = farm
    gear = home / ".g"
    gear.mkdir()
    (gear / "workflow-path").write_text("/d/old/g-skills/g-init/assets/workflow\n", encoding="utf-8")
    out = run()
    assert (gear / "workflow-path").read_text(encoding="utf-8").strip() == \
        bash_path(src / "g-init" / "assets" / "workflow")
    assert "非自属指针" not in out


@windows_only
def test_foreign_workflow_path_is_kept_and_hack_still_installed(farm):
    _, home, run = farm
    gear = home / ".g"
    gear.mkdir()
    (gear / "workflow-path").write_text("/opt/another-tool/rules\n", encoding="utf-8")
    out = run()
    assert (gear / "workflow-path").read_text(encoding="utf-8").strip() == "/opt/another-tool/rules"
    assert "非自属指针" in out
    assert (gear / "hack" / "demo.sh").is_file(), "非自属指针把 hack 安装也一并跳过了"
