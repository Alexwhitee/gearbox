"""收尾闭环断点修复（G 轨）：每条对应一个此前会让 /g-done 卡死或静默放行的盘面。

- A2 archive 后、commit 前：工作树归档未提交 ⇒ ARCHIVE_UNCOMMITTED（此前判「change 不存在」）
- A3 VERIFY_FAIL reason 给出「只缺 openspec/ 内证据」的恢复路径
- A4 票 BLOCKED ⇒ IMPL_BLOCKED（此前继续 CONTINUE_IMPL 重派）；blocked 后修复已提交 ⇒ RERUN_STALE
- B1 实现后设计漂移 ⇒ 后段判定 JSON 带非阻塞 design_drift
- B2 归档态：交付代码 ≠ verify 锚定代码 ⇒ 不判 SHIPPED / 不放行合并
- B6 送设计审前缺合格决策纪要 ⇒ REFUSE_START next=g-spec
"""
import json
import subprocess
import sys
from pathlib import Path

from conftest import (_git, commit_all, fingerprint, head_sha, mkchange, write_anchored_report,
                      write_memo, write_report)
from test_gate_impl_progress import PLAN2_TICKETS, approved_change
from test_gate_preflight import run_gate
from test_gate_tail import impl_done

BC = Path(__file__).resolve().parents[1] / "scripts" / "branch_context.py"


# ── B6 决策纪要门 ─────────────────────────────────────────────────────────

def test_missing_memo_refuses_with_next_g_spec(repo):
    mkchange(repo, memo=False)
    commit_all(repo, "seed")
    code, js, _ = run_gate(repo)
    assert code == 3 and js["verdict"] == "REFUSE_START" and js["next"] == "g-spec"
    assert "decision-memo.md 不存在" in js["reason"]


def test_empty_required_section_refuses(repo):
    d = mkchange(repo, memo=False)
    write_memo(d, constraints="<!-- 待补 -->")
    commit_all(repo, "seed")
    code, js, _ = run_gate(repo)
    assert code == 3 and js["next"] == "g-spec"
    assert "「## 承重约束」为空" in js["reason"]


def test_unfinalized_memo_refuses(repo):
    d = mkchange(repo, memo=False)
    write_memo(d, decision_hash=None)
    commit_all(repo, "seed")
    code, js, _ = run_gate(repo)
    assert code == 3 and js["next"] == "g-spec" and "decision_hash" in js["reason"]


def test_valid_memo_falls_through_to_design_gate(repo):
    mkchange(repo)
    commit_all(repo, "seed")
    code, js, _ = run_gate(repo)
    assert code == 3 and js["next"] is None and "未过设计门" in js["reason"]


def test_memo_not_required_once_design_approved(repo):
    # 已过设计门的在途 change 不追溯拦截（门只守「送设计审之前」）
    d = approved_change(repo, plan=PLAN2_TICKETS)
    (d / "decision-memo.md").unlink()
    commit_all(repo, "drop memo after approval")
    code, js, _ = run_gate(repo)
    assert js["verdict"] == "CONTINUE_IMPL"


def test_memo_section_heading_inside_fence_does_not_count(repo):
    d = mkchange(repo, memo=False)
    (d / "decision-memo.md").write_text(
        "---\ndecision_hash: sha256:abc\n---\n\n## 拍板决策\n\n- D1\n\n"
        "```markdown\n## 承重约束\n- 示例\n```\n", encoding="utf-8")
    commit_all(repo, "seed")
    code, js, _ = run_gate(repo)
    assert code == 3 and "缺必填小节「## 承重约束」" in js["reason"]


# ── A4 票 BLOCKED / BLOCKED_UPSTREAM 恢复 ─────────────────────────────────

def test_blocked_ticket_stops_instead_of_redispatch(repo):
    d = approved_change(repo, plan=PLAN2_TICKETS)
    commit_all(repo, "checkpoint(task1-a): A")
    plan = d / "tickets.md"
    plan.write_text(plan.read_text(encoding="utf-8") + "BLOCKED: 测试环境缺数据库\n", encoding="utf-8")
    commit_all(repo, "ticket 2 blocked")
    code, js, _ = run_gate(repo)
    assert code == 4 and js["verdict"] == "IMPL_BLOCKED" and js["next"] is None
    assert js["blocked_tasks"] == ["2"] and "测试环境缺数据库" in js["reason"]
    assert "删除" in js["reason"]


def test_blocked_line_on_done_ticket_is_ignored(repo):
    d = approved_change(repo, plan=PLAN2_TICKETS.replace("- [ ] s\n", "- [ ] s\nBLOCKED: 旧阻塞已解\n", 1))
    commit_all(repo, "checkpoint(task1-a): A")
    code, js, _ = run_gate(repo)
    assert js["verdict"] == "CONTINUE_IMPL"


def test_removing_blocked_line_resumes(repo):
    d = approved_change(repo, plan=PLAN2_TICKETS + "BLOCKED: x\n")
    assert run_gate(repo)[1]["verdict"] == "IMPL_BLOCKED"
    (d / "tickets.md").write_text(PLAN2_TICKETS, encoding="utf-8")
    commit_all(repo, "unblock")
    assert run_gate(repo)[1]["verdict"] == "CONTINUE_IMPL"


def _blocked_review(repo):
    d = impl_done(repo)
    write_anchored_report(repo, d, "code-review-report.md", head_sha(repo), "code",
                          body="# 代码审报告\nP0 未解\n", code_review="blocked")
    commit_all(repo, "cr blocked")
    return d


def test_blocked_upstream_without_new_code_stays_blocked(repo):
    _blocked_review(repo)
    code, js, _ = run_gate(repo)
    assert code == 4 and js["verdict"] == "BLOCKED_UPSTREAM" and "重调" in js["reason"]


def test_blocked_upstream_recovers_after_fix_committed(repo):
    _blocked_review(repo)
    (repo / "fix.py").write_text("fixed = True\n", encoding="utf-8")
    commit_all(repo, "fix: 解 P0")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RERUN_STALE" and js["next"] == "g-code-review"


# ── A3 VERIFY_FAIL 恢复路径 ───────────────────────────────────────────────

def test_verify_fail_reason_offers_openspec_only_recovery(repo):
    d = impl_done(repo)
    write_anchored_report(repo, d, "code-review-report.md", head_sha(repo), "code", code_review="pass")
    write_anchored_report(repo, d, "verify-report.md", head_sha(repo), "code", verify="FAIL")
    commit_all(repo, "verify fail: 缺收尾票报告")
    code, js, _ = run_gate(repo)
    assert code == 5 and js["verdict"] == "VERIFY_FAIL"
    assert "缺口只在 openspec/ 内" in js["reason"] and "整份重写" in js["reason"]


# ── B1 实现后设计漂移 ─────────────────────────────────────────────────────

def test_design_change_after_impl_surfaces_design_drift(repo):
    d = impl_done(repo)
    spec = d / "specs" / "cap"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("### Requirement: 新加的\n", encoding="utf-8")
    commit_all(repo, "docs: 实现后新增 Requirement")
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "RUN_CODE_REVIEW"     # 窗口外不阻塞
    assert js["design_drift"] == ["openspec/changes/demo/specs/cap/spec.md"]
    assert "design_drift" in js["reason"]


def test_no_design_drift_field_when_design_untouched(repo):
    impl_done(repo)
    _, js, _ = run_gate(repo)
    assert js["verdict"] == "RUN_CODE_REVIEW" and "design_drift" not in js


# ── A2 archive 已发生、归档未提交 ─────────────────────────────────────────

def _verified_active_change(repo):
    """走到 verify PASS 的 active change（带分支约定），返回 change 目录。"""
    commit_all(repo, "base seed")                  # main 有提交，才能作为合并目标
    _git(repo, "checkout", "-q", "-b", "feat/demo")
    d = impl_done(repo)
    r = subprocess.run([sys.executable, str(BC), "init", "--root", str(repo), "--change", "demo",
                        "--source", "main", "--base", head_sha(repo)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    commit_all(repo, "branch context")
    write_anchored_report(repo, d, "code-review-report.md", head_sha(repo), "code", code_review="pass")
    write_anchored_report(repo, d, "verify-report.md", head_sha(repo), "code", verify="PASS")
    commit_all(repo, "verify pass")
    return d


def _openspec_archive(repo, d):
    dest = repo / "openspec/changes/archive/2026-11-18-demo"
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.rename(dest)                     # openspec archive 只搬目录、不提交
    return dest


def test_uncommitted_archive_continues_instead_of_not_found(repo):
    d = _verified_active_change(repo)
    dest = _openspec_archive(repo, d)
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "ARCHIVE_UNCOMMITTED" and js["next"] == "g-done"
    assert js["archive_dir"] == "openspec/changes/archive/2026-11-18-demo"
    r = subprocess.run([sys.executable, str(BC), "show", "--root", str(repo), "--change", "demo"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["context_path"].startswith("openspec/changes/archive/2026-11-18-demo/")


def test_uncommitted_archive_requires_verify_pass(repo):
    d = _verified_active_change(repo)
    dest = _openspec_archive(repo, d)
    (dest / "verify-report.md").write_text("# 没有锚\n", encoding="utf-8")
    code, js, _ = run_gate(repo)
    assert code == 6 and js["verdict"] == "UNKNOWN" and "verify=PASS" in js["reason"]


# ── B2 归档态交付核对 ─────────────────────────────────────────────────────

def test_staged_source_sneaking_into_archive_commit_is_not_shipped(repo):
    d = _verified_active_change(repo)
    _openspec_archive(repo, d)
    (repo / "sneaky.py").write_text("未验证 = True\n", encoding="utf-8")
    commit_all(repo, "chore: archive demo")       # 归档提交顺带夹带了源码
    code, js, _ = run_gate(repo)
    assert code == 6 and js["verdict"] == "UNKNOWN" and "已验证代码不一致" in js["reason"]


def test_clean_archive_commit_ships_in_place(repo):
    d = _verified_active_change(repo)
    _openspec_archive(repo, d)
    commit_all(repo, "chore: archive demo")
    (repo / "later.py").write_text("后续工作\n", encoding="utf-8")
    commit_all(repo, "feat: 归档之后的新工作")       # 原地完成后的后续提交不影响已完成判定
    code, js, _ = run_gate(repo)
    assert code == 0 and js["verdict"] == "SHIPPED" and js["merge_not_requested"] is True


def test_code_committed_after_archive_blocks_pending_merge(repo):
    d = _verified_active_change(repo)
    r = subprocess.run([sys.executable, str(BC), "set-target", "--root", str(repo), "--change", "demo",
                        "--target", "main"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    commit_all(repo, "merge request")
    _openspec_archive(repo, d)
    commit_all(repo, "chore: archive demo")
    assert run_gate(repo)[1]["verdict"] == "RUN_VERIFY"          # 待合并、代码一致 → 放行
    (repo / "late.py").write_text("归档后才写的代码\n", encoding="utf-8")
    commit_all(repo, "feat: 归档后追加")
    code, js, _ = run_gate(repo)
    assert code == 6 and js["verdict"] == "UNKNOWN" and "已验证代码不一致" in js["reason"]
