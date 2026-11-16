from pathlib import Path

_WFDIR = Path(__file__).resolve().parents[2] / "g-init" / "assets" / "workflow"
WF = _WFDIR / "workflow.md"


def test_orchestrator_entry_row():
    """`/g-done` 在步骤表中作为阶段三的唯一顶层步骤（步骤 5）。"""
    t = WF.read_text(encoding="utf-8")
    assert "| 三 | 5 | /g-done" in t
    assert "5.5" not in t, "workflow.md 不该再出现已退役的条件步骤 5.5（embedded-test-sop）"


def test_decision4_no_self_confidence():
    t = WF.read_text(encoding="utf-8")
    assert "有把握自动选" not in t
    assert "MUST NOT 以自评置信硬选" in t


def test_implement_tag_format_matches_gate():
    """完成标签格式：implement 写出的字面形态必须能被 ship_gate.TAG_RE 解析。"""
    import re
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import ship_gate
    impl = (Path(__file__).resolve().parents[2] / "g-implement" / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r'checkpoint-commit\.sh "\{change\}:task<N>-<slug>"', impl)
    assert m, "g-implement 未给出完成标签的字面命令"
    produced = "checkpoint(demo-change:task3-add-api): x"
    hit = ship_gate.TAG_RE.search(produced)
    assert hit and hit.group(1) == "demo-change" and hit.group(2) == "3"
