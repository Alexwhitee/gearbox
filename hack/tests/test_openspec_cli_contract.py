"""OpenSpec CLI 端到端契约：按 g-init → g-spec → g-done 实际调用的命令面逐步核对。

为什么需要它：既有用例只对账 `instructions design`（内置 schema）与 validate/status 的局部行为；
`new change`、g-spec-driven 四个产物的 instructions 载荷、`status` 的 artifactPaths、
`archive --json` 与主 spec 合并都没有真 CLI 锚——换 CLI 版本时无从判断主流程还能不能走通。
（npm latest 跳到 2.x 时用户照安装提示拿到的就是未验证大版本，这是本文件的起因。）

两层：
- 版本一致性（无需 CLI）：验证版本在 CI / setup 预检 / README / g-spec 0.1 / init.py 提示里 MUST 同值。
- 端到端（需真 CLI，未装则 skip，与 test_g_spec_failure_modes 的 openspec_cli 同口径）。
升级验证版本：先用新版本跑本文件全绿，再同步改上述各处。
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPENSPEC = shutil.which("openspec")
_TIMEOUT = 120

openspec_cli = pytest.mark.skipif(OPENSPEC is None, reason="openspec CLI 未安装 —— 端到端契约需要真 CLI")

_spec = importlib.util.spec_from_file_location(
    "_g_spec_failure_modes", Path(__file__).with_name("test_g_spec_failure_modes.py"))
_failure_modes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_failure_modes)
assert_instructions_schema = _failure_modes.assert_instructions_schema  # g-spec C.3 §2 的同一份断言

_PIN_SOURCES = {
    ".github/workflows/mechanical-gates.yml": r"@fission-ai/openspec@(\d+\.\d+\.\d+)",
    "hack/setup-dependencies.sh": r'_OPENSPEC_TESTED_VERSION="(\d+\.\d+\.\d+)"',
    "README.md": r"@fission-ai/openspec@(\d+\.\d+\.\d+)",
    "g-spec/SKILL.md": r"@fission-ai/openspec@(\d+\.\d+\.\d+)",
    "g-init/scripts/init.py": r"@fission-ai/openspec@(\d+\.\d+\.\d+)",
}


def _pinned_versions():
    found = {}
    for rel, pattern in _PIN_SOURCES.items():
        hits = re.findall(pattern, (REPO / rel).read_text(encoding="utf-8"))
        assert hits, f"{rel} 里找不到 openspec 验证版本（模式 {pattern}）"
        found[rel] = set(hits)
    return found


def test_tested_version_is_identical_everywhere():
    found = _pinned_versions()
    versions = set().union(*found.values())
    assert len(versions) == 1, f"openspec 验证版本不一致：{found}"


def _run(cmd, cwd, env):
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True,
                          timeout=_TIMEOUT, encoding="utf-8", errors="replace")


def _json(out):
    try:
        return json.loads(out)
    except ValueError:
        m = re.search(r"\{.*\}\s*$", out, re.S)
        return json.loads(m.group(0)) if m else None


@openspec_cli
def test_main_flow_cli_surface_end_to_end(tmp_path):
    version = _run([OPENSPEC, "--version"], tmp_path, os.environ).stdout.strip()
    where = f"openspec {version}（{OPENSPEC}）"
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"))
    root = tmp_path / "proj"
    root.mkdir()

    def cli(*args):
        return _run([OPENSPEC, *args], root, env)

    # g-init：版本门通过 → 铺 g-spec-driven，config 切到 project-local schema
    r = _run([sys.executable, str(REPO / "g-init" / "scripts" / "init.py"), "init", "--root", str(root)], root, env)
    assert r.returncode == 0, f"g-init init 失败：{r.stderr} / {where}"
    assert (root / "openspec/schemas/g-spec-driven/schema.yaml").is_file(), r.stdout

    # g-spec 0.1 预检
    for args in (["context"], ["list"], ["list", "--specs"]):
        r = cli(*args)
        assert r.returncode == 0, f"openspec {' '.join(args)} 非零退出：{r.stderr} / {where}"

    # B.1 ③ 建 change：marker 落在 project-local schema 上
    r = cli("new", "change", "demo")
    marker = root / "openspec/changes/demo/.openspec.yaml"
    assert r.returncode == 0 and marker.is_file(), f"new change 失败：{r.stderr} / {where}"
    assert "g-spec-driven" in marker.read_text(encoding="utf-8"), marker.read_text(encoding="utf-8")

    # 0.3 / C.3：status --json 的 isComplete 与 artifactPaths.<id>.existingOutputPaths
    st = _json(cli("status", "--change", "demo", "--json").stdout)
    assert isinstance(st, dict) and "isComplete" in st, f"status --json 缺 isComplete：{st} / {where}"
    for art in ("proposal", "specs", "design", "tasks"):
        assert "existingOutputPaths" in (st.get("artifactPaths") or {}).get(art, {}), \
            f"status --json 缺 artifactPaths.{art}.existingOutputPaths / {where}"

    # C.3 §1-§3：四个产物的 instructions 载荷 ⊇ SKILL 声明字段，且委派区块成对
    for art in ("proposal", "specs", "design", "tasks"):
        r = cli("instructions", art, "--change", "demo", "--json")
        assert r.returncode == 0, f"instructions {art} 非零退出：{r.stderr} / {where}"
        payload = assert_instructions_schema(r.stdout)
        ins = payload["instruction"]
        assert ins.count("<!-- g:delegation:start -->") == 1 and ins.count("<!-- g:delegation:end -->") == 1, \
            f"instructions {art} 的委派区块不成对 / {where}"

    change = root / "openspec/changes/demo"
    (change / "proposal.md").write_text(
        "## Why\nContract smoke.\n\n## What Changes\n- Add demo capability\n\n## Capabilities\n\n"
        "### New Capabilities\n- `demo-cap`: demo behavior\n\n### Modified Capabilities\n\n## Impact\n- none\n",
        encoding="utf-8")
    (change / "specs/demo-cap").mkdir(parents=True)
    (change / "specs/demo-cap/spec.md").write_text(
        "## Purpose\nDemo capability used only to exercise the OpenSpec CLI contract end to end.\n\n"
        "## ADDED Requirements\n\n### Requirement: Demo greets\nThe system SHALL greet the user.\n\n"
        "#### Scenario: Greeting\n- **WHEN** the user opens the app\n- **THEN** a greeting is shown\n",
        encoding="utf-8")
    (change / "design.md").write_text("## Context\nSmoke.\n\n## Decisions\n见 decision-memo.md\n", encoding="utf-8")
    (change / "tasks.md").write_text("## 1. Demo\n\n- [x] 1.1 Implement greeting\n", encoding="utf-8")

    # C.4：存在态 + 合格态
    st = _json(cli("status", "--change", "demo", "--json").stdout)
    assert isinstance(st, dict) and st.get("isComplete") is True, f"四件套齐全后 isComplete 非 true：{st} / {where}"
    r = cli("validate", "demo", "--strict", "--type", "change")
    assert r.returncode == 0, f"validate --strict 失败：{r.stdout}{r.stderr} / {where}"

    # g-done archive 第 1 步：exit 0 且顶层 archive 非 null；主 spec 合并；delta 核验通过
    r = cli("archive", "demo", "-y", "--json")
    out = _json(r.stdout) if r.returncode == 0 else None
    assert isinstance(out, dict) and out.get("archive") is not None, f"archive --json 契约变化：{r.stdout}{r.stderr} / {where}"
    main_spec = root / "openspec/specs/demo-cap/spec.md"
    assert main_spec.is_file() and "Demo greets" in main_spec.read_text(encoding="utf-8"), f"主 spec 未合并 / {where}"
    archived = sorted((root / "openspec/changes/archive").glob("*-demo"))
    assert len(archived) == 1, f"归档目录形态变化：{archived} / {where}"
    r = _run([sys.executable, str(REPO / "g-done/scripts/delta_sync_check.py"), "--archive-dir", str(archived[0])], root, env)
    assert r.returncode == 0, r.stdout + r.stderr

    # archive fallback 与 proposal 指令用到的只读命令
    assert cli("validate", "demo-cap", "--type", "spec").returncode == 0, where
    r = cli("show", "demo-cap", "--type", "spec", "--json", "--no-scenarios")
    assert r.returncode == 0 and _json(r.stdout) is not None, f"show --json 失败：{r.stderr} / {where}"
