"""g-done SKILL 文案机械守（内联精简版，吸收原 g-ship 编排）：只钉关键词在场，不重复逻辑测试。"""
import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"
GATE = Path(__file__).resolve().parents[1] / "scripts" / "ship_gate.py"


def text():
    return SKILL.read_text(encoding="utf-8")


def _gate_src():
    return GATE.read_text(encoding="utf-8")


def emitted_verdicts():
    """ship_gate 源码里实际 emit 的全部 verdict（emit / emit_windowed / late 三个出口）。
    从源码取而不是手抄清单：新增 verdict 忘了在链序表里给路由 ⇒ 本守卫当场红。"""
    src = _gate_src()
    found = set(re.findall(r'\b(?:emit|late)\(\s*"([A-Z_]+)"', src))
    found |= set(re.findall(r'emit_windowed\([^"]*?"([A-Z_]+)"', src, re.S))
    return found


def emitted_next_names():
    """ship_gate 源码里作为 next_step 实参出现的全部步骤名（`EXIT_xxx, "<name>"` 形态）。"""
    return set(re.findall(r'EXIT_[A-Z]+,\s*"([a-z][a-z-]*)"', _gate_src()))


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
    assert "连续两次 gate 输出" in t          # 熔断判据由执行者比对，gate 无机械熔断
    assert "重调即续" in t
    assert "`done_tasks` 原样取 gate JSON" in t


def test_extraction_sees_known_verdicts():
    # 恒真锚防线：正则失配会让下面的全覆盖守卫静默变空转。
    assert {"REFUSE_START", "CONTINUE_IMPL", "RUN_VERIFY", "IMPL_BLOCKED",
            "ARCHIVE_UNCOMMITTED", "SHIPPED", "UNKNOWN"} <= emitted_verdicts()
    assert {"g-implement", "g-code-review", "g-done", "g-spec"} <= emitted_next_names()


def test_every_verdict_has_a_route():
    t = text()
    table = t[t.index("## 链序"):t.index("**`next` 名映射**")]
    rows = [ln for ln in table.splitlines() if ln.startswith("| ")]
    for verdict in sorted(emitted_verdicts()):
        assert any(verdict in ln.split("|")[1] for ln in rows), f"链序表缺 {verdict}"


def test_next_name_mapping_covers_gate_internal_names():
    t = text()
    mapping = t[t.index("**`next` 名映射**"):]
    for name in sorted(emitted_next_names()):
        assert f"`{name}`" in mapping, f"`next` 映射缺 {name}"
    # gate 已不再发 g-spec-review（设计失鲜走 REFUSE_START）——映射里留着就是永不触发的死规则
    assert "`g-spec-review`" not in mapping


def test_design_change_after_approval_stops_for_human():
    t = text()
    assert "拍板失鲜" in t and "design_drift" in t
    assert "MUST NOT 自行补锚" in t


def test_code_review_runs_in_fresh_session_by_default():
    t = text()
    row = next(ln for ln in t.splitlines() if ln.startswith("| RUN_CODE_REVIEW"))
    assert "/clear" in row and "本会话执行过本 change 的实现" in row


def test_closeout_steps_present():
    t = text()
    for token in ("hand-off.md", "delta_sync_check.py", "roadmap_writeback_draft.py",
                  "suite-scope", "--skip-specs", "merge --ff-only"):
        assert token in t, f"收尾步骤缺 {token}"


def test_archive_commit_cannot_carry_unverified_code():
    t = text()
    commit = t[t.index("## commit"):t.index("## merge")]
    assert "diff --cached --name-only" in commit
    assert "-- openspec/" in commit


def test_ff_failure_returns_to_work_branch():
    merge = text()[text().index("## merge"):]
    assert "git checkout {work_branch}" in merge


def test_preexisting_red_rows_are_reverified_on_base():
    t = text()
    assert "<base_sha> | <base 复跑命令> | <base 退出码>" in t
    assert "git worktree add" in t


def test_trigger_words_scoped():
    t = text()
    head = t.split("---", 2)[1]   # frontmatter
    assert "/g-done" in head
    assert "发布" not in head      # 避让裸词
