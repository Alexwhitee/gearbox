"""defer 台账存在性、ID 与 source_change 对账；退役 metrics 配置不阻塞内联评审。"""
import sys
from pathlib import Path

import pytest

from conftest import commit_all, mkchange, head_sha, write_report, fingerprint
from test_gate_preflight import run_gate
from test_gate_tail import impl_done
from test_gate_impl_progress import PLAN2_TICKETS

_scripts_path = str(Path(__file__).resolve().parents[1] / "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)
import ship_gate as _sg  # noqa: E402


def _design_anchor(repo, change="demo"):
    return fingerprint(repo, head_sha(repo), "design", change)

def _code_anchor(repo, change="demo"):
    return fingerprint(repo, head_sha(repo), "code", change)


def write_config_metrics(root, value):
    """写 `openspec/config.yaml` 的 `metrics.enabled: <value>`（value 为已格式化好的 YAML
    字面量文本，如 `"true"`/`"false"`/`'"yes"'`）。"""
    d = root / "openspec"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(f"metrics:\n  enabled: {value}\n", encoding="utf-8")


def write_pool_file(root, pool, id_, source_change):
    """写一份最小 issues 池文件（frontmatter 逐字对齐 issues_v2.py 实产格式，见
    `openspec/issues/open/bug/B25.md` 真实样本）。"""
    p = root / "openspec" / "issues" / "open" / pool
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{id_}.md").write_text(
        "---\n"
        f'id: "{id_}"\n'
        f'pool: "{pool}"\n'
        'status: "OPEN"\n'
        'priority: "P2"\n'
        f'source_change: "{source_change}"\n'
        'summary: "test"\n'
        "---\n",
        encoding="utf-8")


def cr_body(*, defer_id=None, extra_table=False):
    parts = ["# code-review 报告\n"]
    if defer_id:
        parts.append(
            "### 修复 / defer 台账\n"
            "| 类型 | id | 说明 |\n"
            "|---|---|---|\n"
            f"| defer | {defer_id} | 示例 defer 项，引用旧票 T105 仅作说明不参与对账 |\n")
    if extra_table:
        parts.append(
            "### Findings（已采纳）\n"
            "| 严重度 | 位置 | 说明 |\n"
            "|---|---|---|\n"
            "| 高 | a.go:1 | 提及旧票 T105 的说明不应被误抓 |\n")
    return "".join(parts)


# ══════════════════════ defer 台账提取（窄化 + fence-aware）══════════════════════

def test_defer_ledger_extracts_id_column_only():
    text = cr_body(defer_id="T900")
    assert _sg._defer_ledger_id_cells(text) == ["T900"]


def test_defer_ledger_description_column_old_id_not_extracted():
    # id 列含真实新 id，说明列提及旧票 T105——只应抓到 id 列那一个。
    text = cr_body(defer_id="B26")
    assert _sg._defer_ledger_id_cells(text) == ["B26"]


def test_defer_ledger_table_without_id_column_not_scanned():
    # Findings 表无 id 列，即便内容提及票号也不落入台账提取。
    text = cr_body(extra_table=True)
    assert _sg._defer_ledger_id_cells(text) == []


def test_defer_ledger_aggregate_summary_sentence_no_pipe_ignored():
    text = "### 修复 / defer 台账\n自动修 2 项[impl-review-fix]；defer 1 项 → buglist/todolist\n"
    assert _sg._defer_ledger_id_cells(text) == []


def test_defer_ledger_fenced_table_ignored():
    text = ("### 修复 / defer 台账\n无实际 defer\n```\n| 类型 | id | 说明 |\n|---|---|---|\n"
            "| defer | T999 | 围栏内锚样例 |\n```\n")
    assert _sg._defer_ledger_id_cells(text) == []


def test_defer_ledger_malformed_id_cell_extracted_as_is():
    text = ("### 修复 / defer 台账\n| 类型 | id | 说明 |\n|---|---|---|\n"
            "| defer | 已入 todolist | 无真实 id |\n")
    assert _sg._defer_ledger_id_cells(text) == ["已入 todolist"]


@pytest.mark.parametrize("value", ["true", "false", '"legacy-value"'])
def test_retired_metrics_config_does_not_require_removed_anchors(repo, value):
    write_config_metrics(repo, value)
    d = impl_done(repo)
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(), code_review="pass")
    commit_all(repo, "code review without retired metric anchors")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RUN_VERIFY"

# ══════════════════════ CLI 端到端：defer 对账门 ══════════════════════

def test_defer_gate_passes_with_valid_id_and_pool_file(repo):
    d = impl_done(repo)
    write_pool_file(repo, "todo", "T900", "demo")
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(defer_id="T900"), code_review="pass")
    commit_all(repo, "cr")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RUN_VERIFY"


def test_defer_gate_blocked_when_id_missing(repo):
    d = impl_done(repo)
    body = ("# code-review 报告\n### 修复 / defer 台账\n| 类型 | id | 说明 |\n|---|---|---|\n"
            "| defer | 已入 todolist | 无真实 id |\n")
    write_report(d, "code-review-report.md", *_code_anchor(repo), body=body, code_review="pass")
    commit_all(repo, "cr")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "STEP_IN_PROGRESS" and js["next"] == "g-code-review"
    assert "id 列内容非法" in js["reason"]


def test_defer_gate_blocked_when_pool_file_missing(repo):
    d = impl_done(repo)
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(defer_id="T901"), code_review="pass")
    commit_all(repo, "cr")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "STEP_IN_PROGRESS"
    assert "文件系统不存在" in js["reason"]


def test_defer_gate_blocked_when_source_change_mismatched(repo):
    d = impl_done(repo)
    write_pool_file(repo, "todo", "T902", "some-other-change")
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(defer_id="T902"), code_review="pass")
    commit_all(repo, "cr")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "STEP_IN_PROGRESS"
    assert "some-other-change" in js["reason"]


def test_defer_gate_passes_when_pool_file_uncommitted(repo):
    # B26 用文件系统存在性判定，MUST NOT 走 git 跟踪清单——池文件写盘但不 add/commit 也应通过。
    # 🔴 `commit_all` 内部 `git add -A`，若在其之前写池文件会被顺手一并提交、测不出「未跟踪」
    # 这个分支——池文件须落在**最后一次** commit_all **之后**，run_gate 执行时才是真未跟踪。
    d = impl_done(repo)
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(defer_id="B900"), code_review="pass")
    commit_all(repo, "cr")   # 报告已提交；池文件此刻尚不存在
    write_pool_file(repo, "bug", "B900", "demo")   # 写盘后不再 commit_all——工作树未跟踪文件
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RUN_VERIFY"


def test_defer_gate_ignores_description_column_old_ticket_reference(repo):
    # 台账窄化负例：id 列合法，说明列提及旧票 T105——不应被误抓进对账（若误抓，T105 池文件
    # 不存在或 source_change 不符会导致本该通过的用例被误拦）。
    d = impl_done(repo)
    write_pool_file(repo, "todo", "T903", "demo")
    write_report(d, "code-review-report.md", *_code_anchor(repo),
                 body=cr_body(defer_id="T903"), code_review="pass")
    commit_all(repo, "cr")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RUN_VERIFY"


# ══════════════════════ 「既有问题」区形态（retest-review-fixes-and-record-preexisting） ══════════════════════
# 代码评审报告新增「既有问题」区。带 id 列的表只放本 change 池项；
# 「已存在：T123」「待人工补录」写在表下列表；无既有问题只写「无」。
# 这些用例对 guard_defer_ledger 直接喂报告文本（不经 CLI），只验 B26 对新形态的放行/拦截。

PREEXISTING_HEAD = "### 既有问题\n"
PREEXISTING_TABLE = ("| id | 池 | 摘要 | 说明 |\n"
                     "|---|---|---|---|\n"
                     "| B90 | bug | 既有问题：parse_foo 空输入越界 | 不在改动行内 |\n")


def _guard(repo, body):
    report = repo / "code-review-report.md"
    report.write_text("# code-review 报告\n" + body, encoding="utf-8")
    return _sg.guard_defer_ledger(repo, "demo", report)


def test_preexisting_section_table_row_plus_already_exists_passes(repo):
    write_pool_file(repo, "bug", "B90", "demo")
    body = PREEXISTING_HEAD + PREEXISTING_TABLE + "\n- 已存在：T123\n"
    assert _guard(repo, body) is None


def test_preexisting_section_none_only_passes(repo):
    assert _guard(repo, PREEXISTING_HEAD + "无\n") is None


def test_preexisting_section_pending_manual_record_below_table_passes(repo):
    body = (PREEXISTING_HEAD + "\n- 待人工补录：既有问题：X；"
            "补录命令：`issues_v2.py add --pool bug --json '{}'`\n")
    assert _guard(repo, body) is None


def test_preexisting_section_none_written_as_id_row_is_blocked(repo):
    body = (PREEXISTING_HEAD + "| id | 池 | 摘要 | 说明 |\n"
            "|---|---|---|---|\n"
            "| 无 | — | — | — |\n")
    reason = _guard(repo, body)
    assert reason is not None and "id 列内容非法" in reason


def test_preexisting_section_table_id_from_other_change_is_blocked(repo):
    write_pool_file(repo, "bug", "B90", "some-other-change")
    body = PREEXISTING_HEAD + PREEXISTING_TABLE
    reason = _guard(repo, body)
    assert reason is not None and "some-other-change" in reason


@pytest.mark.parametrize("location", ["open", "closed"])
@pytest.mark.parametrize("origin", ["older-change", None])
def test_explicit_history_reuse_preserves_original_source(repo, location, origin):
    write_pool_file(repo, "bug", "B90", origin)
    issue = repo / "openspec/issues/open/bug/B90.md"
    if origin is None:
        issue.write_text(issue.read_text(encoding="utf-8").replace('"None"', 'null'), encoding="utf-8")
    if location == "closed":
        destination = repo / "openspec/issues/closed/bug/B90.md"
        destination.parent.mkdir(parents=True)
        issue.rename(destination)
        issue = destination
    original = issue.read_bytes()
    body = "| id | 摘要 | 去向 | 来源 |\n|---|---|---|---|\n| B90 | 既有问题 | defer | reuse |\n"
    assert _guard(repo, body) is None
    assert issue.read_bytes() == original


@pytest.mark.parametrize("source", ["", "maybe", "NEW"])
def test_invalid_ledger_source_cannot_bypass_provenance(repo, source):
    write_pool_file(repo, "bug", "B90", "older-change")
    body = f"| id | 来源 |\n|---|---|\n| B90 | {source} |\n"
    assert "来源须为" in _guard(repo, body)


def test_reuse_does_not_allow_missing_or_ambiguous_issue(repo):
    body = "| id | 来源 |\n|---|---|\n| B90 | reuse |\n"
    assert "文件系统不存在" in _guard(repo, body)
    write_pool_file(repo, "bug", "B90", "old")
    duplicate = repo / "openspec/issues/closed/bug/B90.md"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes((repo / "openspec/issues/open/bug/B90.md").read_bytes())
    assert "多个池文件" in _guard(repo, body)


@pytest.mark.parametrize("field,value", [("id", "B91"), ("pool", "todo")])
def test_reuse_rejects_mismatched_issue_identity(repo, field, value):
    write_pool_file(repo, "bug", "B90", "old")
    issue = repo / "openspec/issues/open/bug/B90.md"
    text = issue.read_text(encoding="utf-8")
    old = "B90" if field == "id" else "bug"
    text = text.replace(f'{field}: "{old}"', f'{field}: "{value}"')
    issue.write_text(text, encoding="utf-8")
    body = "| id | 来源 |\n|---|---|\n| B90 | reuse |\n"
    assert "id/pool 不匹配" in _guard(repo, body)
