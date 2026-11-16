"""scratch 消费仓 update 幂等回归，所有写入均在临时目录。"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _run_gear_init(root, mode, home):
    """在子进程里跑 `g-init/scripts/init.py <mode> --root <root>`，
    `CLAUDE_CONFIG_DIR` 重定向到假 home，避免 `ensure_global_hooks()` 碰真实 `~/.claude`。
    """
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    env.pop("HOME_OVERRIDE", None)
    script = REPO / "g-init" / "scripts" / "init.py"
    return subprocess.run(
        [sys.executable, str(script), mode, "--root", str(root)],
        cwd=str(root), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


class TestScratchConsumerUpdateIdempotent:
    """`copy_bundle` 明写「hack 脚本不再铺进仓」（init.py `run()` 的 report 一行）——
    scratch 消费仓的 update 幂等性因此与本 change 的 codex 采集内容无关，是通用 update
    回归；ticket brief 交付行为 1 明确要求覆盖，一并做在这里。
    """

    def test_update_twice_produces_no_diff(self, tmp_path):
        home = tmp_path / "home"
        home.mkdir()
        repo = tmp_path / "consumer"
        repo.mkdir()
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t")
        _git(repo, "config", "user.name", "t")

        r_init = _run_gear_init(repo, "init", home)
        assert r_init.returncode == 0, r_init.stdout + r_init.stderr
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "init")

        r_update1 = _run_gear_init(repo, "update", home)
        assert r_update1.returncode == 0, r_update1.stdout + r_update1.stderr
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "update1", "--allow-empty")

        r_update2 = _run_gear_init(repo, "update", home)
        assert r_update2.returncode == 0, r_update2.stdout + r_update2.stderr

        status = _git(repo, "status", "--porcelain").stdout
        assert status.strip() == "", f"二次 update 产生了差异：\n{status}"
