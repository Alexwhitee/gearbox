"""`setup.sh install_agents()` 的退役清理契约。

【背景】g-spec 的三个子代理定义（g-local-researcher / g-spec-writer / g-web-researcher）已随子代理
派发一起退役，`g-spec/agents/` 整个源目录已删除。`install_agents()` 保留的唯一职责是**撤下本安装器
以前铺出去的定义**：源集合为空 ⇒ manifest（`.g-agents`）里记着的名字全是废弃项；本仓布局的悬空链
一并清掉。`$CLAUDE_HOME/agents/` 是**全局命名空间**——第三方的真实文件与有效软链一律不碰。

【怎么跑】`tmp_path` 当**假 HOME** 真跑 `bash setup.sh`（摘掉继承来的 CLAUDE_CONFIG_DIR，落点即
`<假 HOME>/.claude/agents`）。🔴 每个用例都断言真实 `~/.claude/agents/` 的快照前后不变。

【本文件照不到的面（诚实边界）】Windows 分支（copy + manifest 归属）由
`g-init/tests/test_setup_claude_home.py` 的跨平台迷你源仓用例覆盖；本模块的断言针对 Unix 软链形态。
"""
import os
import subprocess
from pathlib import Path

import pytest

from test_support.windows import bash_executable, bash_path

if os.name == "nt":
    pytest.skip(
        "this module's assertions target the Unix symlink path; the Windows copy branch is"
        " covered by g-init/tests/test_setup_claude_home.py",
        allow_module_level=True,
    )

REPO = Path(__file__).resolve().parents[2]
SETUP = REPO / "setup.sh"
SRC_DIR = REPO / "g-spec" / "agents"
REAL_AGENTS = Path(os.path.expanduser("~")) / ".claude" / "agents"
RETIRED = ("g-local-researcher.md", "g-spec-writer.md", "g-web-researcher.md")


def _real_agents_snapshot():
    """真实 agents 目录的 (名字 → 软链指向/`<file>`) 快照。目录不存在 → None。"""
    if not REAL_AGENTS.is_dir():
        return None
    out = {}
    for p in sorted(REAL_AGENTS.iterdir()):
        out[p.name] = os.readlink(p) if p.is_symlink() else "<file>"
    return out


def _run_setup(home):
    """用假 HOME 跑一次 setup.sh，返回 CompletedProcess。"""
    env = dict(os.environ)
    env["HOME"] = str(home)
    env.pop("G_HOME", None)              # 否则 install_g 会写到真实 ~/.g
    env.pop("CLAUDE_CONFIG_DIR", None)   # 否则 skills/agents 与 retire-hooks 都会落到继承来的配置目录
    return subprocess.run([bash_executable(), bash_path(SETUP)], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=300, encoding="utf-8", errors="replace")


@pytest.fixture
def fake_home(tmp_path):
    """跑 setup.sh 前后各拍一次真实 agents 目录 —— 被动过就红。"""
    before = _real_agents_snapshot()
    home = tmp_path / "home"
    home.mkdir()
    yield home
    assert _real_agents_snapshot() == before, \
        "真实 ~/.claude/agents/ 被测试改动了 —— install_agents() 里有不走 $HOME 的路径"


def _agents_dir(home):
    return home / ".claude" / "agents"


def _old_checkout(tmp_path):
    """另一个（旧）checkout：三个定义的源文件仍在 —— 链有效，孤儿清理的悬空判据碰不到它们。"""
    old = tmp_path / "old-g-skills" / "g-spec" / "agents"
    old.mkdir(parents=True)
    for name in RETIRED:
        (old / name).write_text("---\nname: x\ntools: Bash, Write\n---\n旧定义\n", encoding="utf-8")
    return old


def test_source_dir_is_retired():
    assert not SRC_DIR.exists(), "g-spec/agents/ 应已删除（子代理派发已退役）"


def test_fresh_install_lays_no_agent_definitions(fake_home):
    r = _run_setup(fake_home)
    assert r.returncode == 0, r.stdout + r.stderr
    dest = _agents_dir(fake_home)
    assert not dest.exists() or not list(dest.glob("*.md"))
    assert "✓ agents/" not in r.stdout


def test_previous_install_listed_in_manifest_is_retired(fake_home, tmp_path):
    """旧版 setup 铺出的有效链 + manifest ⇒ 全部撤下；源文件不动；第三方条目不动。"""
    dest = _agents_dir(fake_home)
    dest.mkdir(parents=True)
    old = _old_checkout(tmp_path)
    for name in RETIRED:
        os.symlink(str(old / name), dest / name)
    (dest / ".g-agents").write_text("\n".join(RETIRED) + "\n", encoding="utf-8")
    (dest / "third-party.md").write_text("mine\n", encoding="utf-8")
    live_foreign_dir = tmp_path / "someone-else-repo" / "g-spec" / "agents"
    live_foreign_dir.mkdir(parents=True)
    (live_foreign_dir / "their-live-agent.md").write_text("third party\n", encoding="utf-8")
    live_foreign = dest / "their-live-agent.md"
    os.symlink(str(live_foreign_dir / "their-live-agent.md"), live_foreign)

    r = _run_setup(fake_home)
    assert r.returncode == 0, r.stdout + r.stderr

    for name in RETIRED:
        assert not (dest / name).is_symlink() and not (dest / name).exists(), f"{name} 没被撤下"
        assert f"agents/{name} @ {dest}" in _cleaned_section(r.stdout), f"{name} 没进 cleaned 汇总"
        assert (old / name).is_file(), "清理把**源文件**删了 —— 只该撤下名册里的链"
    assert (dest / "third-party.md").read_text(encoding="utf-8") == "mine\n"
    assert live_foreign.is_symlink() and live_foreign.is_file(), \
        "误删了别人仓里同布局的**有效**链 —— manifest 里从来没有它"


def test_dangling_own_links_are_cleaned_foreign_ones_kept(fake_home, tmp_path):
    """首趟（尚无 manifest）：本仓布局的悬空链被清；不是本仓路径形状的悬空链、有效第三方链不碰。"""
    dest = _agents_dir(fake_home)
    dest.mkdir(parents=True)
    gone = dest / "g-spec-writer.md"
    os.symlink(str(SRC_DIR / "g-spec-writer.md"), gone)                 # 源目录已删 → 悬空
    foreign_dangling = dest / "someone-elses.md"
    os.symlink("/nonexistent/elsewhere.md", foreign_dangling)
    live_foreign_dir = tmp_path / "someone-else-repo" / "g-spec" / "agents"
    live_foreign_dir.mkdir(parents=True)
    (live_foreign_dir / "their-live-agent.md").write_text("third party\n", encoding="utf-8")
    live_foreign = dest / "their-live-agent.md"
    os.symlink(str(live_foreign_dir / "their-live-agent.md"), live_foreign)

    r = _run_setup(fake_home)
    assert r.returncode == 0, r.stdout + r.stderr

    assert not gone.is_symlink() and not gone.exists(), "悬空孤儿链没被清"
    assert f"agents/{gone.name} @ {dest}" in r.stdout
    assert foreign_dangling.is_symlink(), "清了别人的悬空链 —— 守卫太宽"
    assert live_foreign.is_symlink() and live_foreign.is_file(), \
        "清了一条**有效**的第三方链 —— 那是真实数据丢失，MUST NOT"


def test_an_occupied_dest_does_not_abort_setup(fake_home):
    """落点被占为普通文件：没东西可铺也没东西可清，MUST NOT 中止 setup.sh，占位文件不动。"""
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "agents").write_text("被别的东西占了\n", encoding="utf-8")

    r = _run_setup(fake_home)

    assert r.returncode == 0, "落点被占竟中止了整个 setup.sh：\n" + r.stdout + r.stderr
    assert (fake_home / ".claude" / "agents").is_file(), "占位文件被动了"
    assert (fake_home / ".g" / "hack").is_dir(), "install_g 没跑到 —— 整条安装链被带崩"


def test_a_readonly_dest_degrades_to_skip_and_does_not_abort_setup(fake_home):
    """落点只读 ⇒ 悬空孤儿链 `rm` 失败 ⇒ skip + 汇总，MUST NOT 中止 setup。"""
    if os.geteuid() == 0:
        pytest.skip("root 无视目录写权限位 —— 这条只在非 root 下有区分力")

    dest = _agents_dir(fake_home)
    dest.mkdir(parents=True)
    orphan = dest / "g-gone-agent.md"
    os.symlink(str(SRC_DIR / "g-gone-agent.md"), orphan)
    os.chmod(dest, 0o555)
    try:
        r = _run_setup(fake_home)
    finally:
        os.chmod(dest, 0o755)   # 还原，否则 tmp_path 清理也进不去

    assert r.returncode == 0, "落点只读竟中止了整个 setup.sh：\n" + r.stdout + r.stderr
    assert f"agents/{orphan.name} @ {dest}" in _skipped_section(r.stdout), \
        "悬空孤儿链清不掉却没进 skipped 汇总 —— 只剩一行裸 rm 错误"
    assert f"✗ agents/{orphan.name} @ {dest}" not in r.stdout, "清理失败却报进了 cleaned 段"
    assert orphan.is_symlink(), "只读落点里的条目居然被动了"
    assert (fake_home / ".g" / "hack").is_dir(), "install_g 没跑到 —— 整条安装链被带崩"


def test_rerun_is_idempotent(fake_home, tmp_path):
    """撤完之后再跑：不产生 agents 的 skip / cleaned。"""
    dest = _agents_dir(fake_home)
    dest.mkdir(parents=True)
    old = _old_checkout(tmp_path)
    os.symlink(str(old / RETIRED[0]), dest / RETIRED[0])
    (dest / ".g-agents").write_text(RETIRED[0] + "\n", encoding="utf-8")
    first = _run_setup(fake_home)
    assert first.returncode == 0, first.stdout + first.stderr

    second = _run_setup(fake_home)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "agents/" not in _skipped_section(second.stdout)
    assert "agents/" not in _cleaned_section(second.stdout)


def test_setup_does_not_install_or_register_global_guards(fake_home):
    """hook 安装侧不进 setup.sh：分支守卫只由 `g-init init/update` 装与注册；子代理守卫已退役。
    setup.sh 会调 retire-hooks（只摘退役项），所以 settings.json 可能存在，但不得含二者。"""
    result = _run_setup(fake_home)
    assert result.returncode == 0, result.stdout + result.stderr
    names = ("ff0-branch-guard.py", "subagent-permission-guard.py")
    found = [p for name in names for p in fake_home.rglob(name)]
    assert found == [], f"setup.sh 不该安装 guard：{found}"
    settings = fake_home / ".claude" / "settings.json"
    if settings.is_file():
        text = settings.read_text(encoding="utf-8")
        for name in names:
            assert name not in text, f"settings.json 不该注册 {name}"


def _section(stdout, header):
    """取 setup.sh 汇总里某一段（`skipped (N):` / `cleaned orphans (N):`）的正文。"""
    lines = stdout.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(header):
            body = []
            for nxt in lines[i + 1:]:
                if not nxt.strip() or not nxt.startswith("    "):
                    break
                body.append(nxt)
            return "\n".join(body)
    return ""


def _skipped_section(stdout):
    return _section(stdout, "skipped (")


def _cleaned_section(stdout):
    return _section(stdout, "cleaned orphans (")
