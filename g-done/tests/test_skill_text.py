"""g-done SKILL 文案机械守（内联精简版，吸收原 g-ship 编排）：只钉关键词在场，不重复逻辑测试。"""
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


def text():
    return SKILL.read_text(encoding="utf-8")


def test_gate_discipline_present():
    t = text()
    assert "每步前后跑 gate" in t and "ship_gate.py" in t
    assert "禁止凭记忆排步序" in t


def test_no_push_and_merge_tristate():
    t = text()
    assert "不自动 push" in t
    assert ".skip-merge" in t and "opt-out" in t and "opt-in" in t


def test_fuse_and_resume():
    t = text()
    assert "熔断" in t and "MUST NOT 无限循环" in t
    assert "重调即续" in t
    assert "`done_tasks` 原样取 gate JSON" in t


def test_every_verdict_has_a_route():
    t = text()
    table = t[t.index("## 链序"):t.index("**`next` 名映射**")]
    rows = [ln for ln in table.splitlines() if ln.startswith("| ")]
    for verdict in ("REFUSE_START", "RUN_PLAN", "CONTINUE_IMPL", "RUN_CODE_REVIEW", "BLOCKED_UPSTREAM",
                    "RUN_VERIFY", "VERIFY_FAIL", "RERUN_STALE", "STEP_IN_PROGRESS", "SHIPPED", "UNKNOWN"):
        assert any(verdict in ln.split("|")[1] for ln in rows), f"链序表缺 {verdict}"


def test_next_name_mapping_covers_gate_internal_names():
    t = text()
    for old in ("g-spec-review", "g-code-review", "g-implement"):
        assert f"`{old}`" in t, f"`next` 映射缺 {old}"


def test_closeout_steps_present():
    t = text()
    for token in ("hand-off.md", "delta_sync_check.py", "roadmap_writeback_draft.py",
                  "suite-scope", "--skip-specs", "merge --ff-only"):
        assert token in t, f"收尾步骤缺 {token}"


def test_trigger_words_scoped():
    t = text()
    head = t.split("---", 2)[1]   # frontmatter
    assert "/g-done" in head
    assert "发布" not in head      # 避让裸词
