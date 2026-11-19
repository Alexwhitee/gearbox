"""g-spec-driven schema 与 g-spec 生成协议对 OpenSpec CLI 的行为契约。

两层：
- 静态（无需 CLI）：schema 描述里的产物顺序 = `requires` 依赖图的拓扑序；每个入口指令（四个产物 +
  `apply`）恰有一对委派块，产物指向 `/g-spec`，`apply` 指向 `/g-done`——绕过入口直接实现/归档的路径被堵住。
- 真 CLI（未装则 skip，与 test_g_spec_failure_modes 的 openspec_cli 同口径）：钉住 SKILL.md C.4 与
  C.3 `skip_specs` 例外所依赖的 CLI 行为——CLI 哪天改了语义，这里先红，提示回来改指令。
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO / "g-init" / "assets" / "schemas" / "g-spec-driven"
SCHEMA = SCHEMA_DIR / "schema.yaml"
OPENSPEC = shutil.which("openspec")
_CLI_TIMEOUT_S = 60

openspec_cli = pytest.mark.skipif(OPENSPEC is None, reason="openspec CLI 未安装 —— 本组需要真跑 CLI")

DELEGATION_START = "<!-- g:delegation:start -->"
DELEGATION_END = "<!-- g:delegation:end -->"


def _artifact_requires():
    """schema.yaml 的 artifacts → {id: [requires...]}（出现序）。格式由本仓自管、两级缩进固定 ⇒ 有界手写。"""
    order, graph, cur, in_requires = [], {}, None, False
    for line in SCHEMA.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^  - id: (\S+)\s*$", line)
        if m:
            cur, in_requires = m.group(1), False
            order.append(cur)
            graph[cur] = []
            continue
        if cur is None:
            continue
        if re.match(r"^\S", line):                 # 回到顶层键（如 apply:）
            cur, in_requires = None, False
            continue
        rm = re.match(r"^    requires:\s*(\[\])?\s*$", line)
        if rm:
            in_requires = rm.group(1) is None
            continue
        if in_requires:
            dm = re.match(r"^      - (\S+)\s*$", line)
            if dm:
                graph[cur].append(dm.group(1))
            elif re.match(r"^    \S", line):
                in_requires = False
    return order, graph


def _topological_order():
    order, graph = _artifact_requires()
    done, out = set(), []
    while len(out) < len(order):
        ready = [a for a in order if a not in done and set(graph[a]) <= done]
        assert len(ready) == 1, f"依赖图不是单链（描述无法写成唯一顺序），ready={ready} graph={graph}"
        out.append(ready[0])
        done.add(ready[0])
    return out


def test_schema_description_order_is_the_dependency_order():
    chain = _topological_order()
    assert chain == ["proposal", "design", "specs", "tasks"], chain
    desc = re.search(r"^description: (.*)$", SCHEMA.read_text(encoding="utf-8"), re.M).group(1)
    assert " → ".join(chain) in desc, f"schema 描述的产物顺序与依赖图不符：{desc!r} vs {chain}"


def _instruction_blocks():
    """→ {入口名: instruction 原文}：四个产物 + apply。按缩进切块（instruction 为 `|` 字面块）。"""
    text = SCHEMA.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^  - id: (\S+)\n(.*?)(?=^  - id: |^\S)", text, re.M | re.S):
        out[m.group(1)] = m.group(2)
    apply = re.search(r"^apply:\n(.*)\Z", text, re.M | re.S)
    assert apply, "schema 缺 apply 段"
    out["apply"] = apply.group(1)
    return out


def test_every_entry_instruction_carries_exactly_one_delegation_block():
    blocks = _instruction_blocks()
    assert set(blocks) == {"proposal", "specs", "design", "tasks", "apply"}, set(blocks)
    for name, body in blocks.items():
        assert body.count(DELEGATION_START) == 1 and body.count(DELEGATION_END) == 1, f"{name} 委派块不成对"
        start, end = body.index(DELEGATION_START), body.index(DELEGATION_END)
        assert start < end, f"{name} 委派块乱序"
        target = "/g-done" if name == "apply" else "/g-spec"
        assert target in body[start:end], f"{name} 的委派块没有指向 {target}"


def test_apply_instruction_carries_no_task_execution_steps():
    """apply 是绕过 g-done（tickets / 代码审 / gate）的入口：剥掉委派块后不得再给「逐条做 tasks」的指令。"""
    body = _instruction_blocks()["apply"]
    rest = body[body.index(DELEGATION_END) + len(DELEGATION_END):]
    for forbidden in ("work through pending tasks", "mark complete as you go"):
        assert forbidden not in rest, f"apply 委派块之外仍有执行指令：{forbidden!r}"


# ── 真 CLI ──────────────────────────────────────────────────────────────────────

def _cli(root, *args):
    return subprocess.run([OPENSPEC, *args], cwd=str(root), capture_output=True, text=True,
                          timeout=_CLI_TIMEOUT_S, encoding="utf-8", errors="replace")


def _status(root):
    r = _cli(root, "status", "--change", "demo", "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    return d["isComplete"], {a["id"]: a["status"] for a in d["artifacts"]}


@pytest.fixture
def change(tmp_path):
    """装上本仓 g-spec-driven schema 的最小项目 + `openspec new change demo`。"""
    (tmp_path / "openspec" / "schemas").mkdir(parents=True)
    shutil.copytree(SCHEMA_DIR, tmp_path / "openspec" / "schemas" / "g-spec-driven")
    (tmp_path / "openspec" / "config.yaml").write_text("schema: g-spec-driven\n", encoding="utf-8")
    r = _cli(tmp_path, "new", "change", "demo")
    assert r.returncode == 0, r.stderr
    d = tmp_path / "openspec" / "changes" / "demo"
    assert "g-spec-driven" in (d / ".openspec.yaml").read_text(encoding="utf-8")
    return tmp_path, d


_PROPOSAL = "## Why\nx\n\n## What Changes\n- a\n\n## Impact\n- none\n"
_DESIGN = "## Context\nx\n\n## Decisions\n见 decision-memo.md\n"
_TASKS = "## 1. G\n\n- [ ] 1.1 do\n"


@openspec_cli
def test_validate_is_red_before_any_spec_delta_exists(change):
    """C.4 时点约束的前提：proposal + design 写完、specs 未写时 `validate --strict` 必红（无 delta），
    而这两份产物本身是合格的 ⇒ 每份写后就跑 validate 会把合格产物误判为未完成。"""
    root, d = change
    (d / "proposal.md").write_text(_PROPOSAL, encoding="utf-8")
    (d / "design.md").write_text(_DESIGN, encoding="utf-8")
    complete, arts = _status(root)
    assert not complete and arts["proposal"] == "done" and arts["design"] == "done", arts
    r = _cli(root, "validate", "demo", "--strict", "--type", "change")
    assert r.returncode != 0, "specs 未写时 validate 竟然绿 —— C.4 的时点约束可以放宽，回来改 SKILL"
    assert "delta" in (r.stdout + r.stderr).lower()


@openspec_cli
def test_skip_specs_marker_marks_specs_skipped_and_validates(change):
    """C.3 `skip_specs` 例外的前提：追加 `skip_specs: true` ⇒ specs 显示 skipped、tasks 可写；
    三份写齐即 isComplete，零 delta 的 change `validate --strict` 通过。"""
    root, d = change
    (d / "proposal.md").write_text(_PROPOSAL, encoding="utf-8")
    (d / "design.md").write_text(_DESIGN, encoding="utf-8")
    marker = d / ".openspec.yaml"
    marker.write_text(marker.read_text(encoding="utf-8") + "skip_specs: true\n", encoding="utf-8")
    complete, arts = _status(root)
    assert arts["specs"] == "skipped" and arts["tasks"] == "ready", arts
    (d / "tasks.md").write_text(_TASKS, encoding="utf-8")
    complete, arts = _status(root)
    assert complete is True, arts
    assert not (d / "specs").exists()
    r = _cli(root, "validate", "demo", "--strict", "--type", "change")
    assert r.returncode == 0, r.stdout + r.stderr


@openspec_cli
def test_apply_instructions_route_to_g_done(change):
    """`openspec instructions apply`（/opsx:apply 等 CLI 自带入口读的就是它）MUST 先给出委派块。"""
    root, d = change
    marker = d / ".openspec.yaml"
    marker.write_text(marker.read_text(encoding="utf-8") + "skip_specs: true\n", encoding="utf-8")
    for name, body in (("proposal.md", _PROPOSAL), ("design.md", _DESIGN), ("tasks.md", _TASKS)):
        (d / name).write_text(body, encoding="utf-8")
    r = _cli(root, "instructions", "apply", "--change", "demo", "--json")
    assert r.returncode == 0, r.stderr
    instruction = json.loads(r.stdout)["instruction"]
    assert instruction.lstrip().startswith(DELEGATION_START), instruction[:200]
    assert "/g-done" in instruction.split(DELEGATION_END, 1)[0]
