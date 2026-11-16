"""当前执行面不能重新引入已退役的调度依赖。"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_live_skills_and_review_rules_have_no_retired_dispatch_contracts():
    paths = list(ROOT.glob("*/SKILL.md")) + [
        ROOT / "g-init/assets/workflow/spec-review.md",
        ROOT / "g-init/assets/workflow/trigger-catalog.md",
        ROOT / "g-init/assets/workflow/reference/quality-layering.md",
        ROOT / "g-architecture/references/review-lenses.md",
        ROOT / "g-devenv/references/review-lenses.md",
        ROOT / "g-devenv/references/review-dispatch-template.md",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for retired in ("G_TIER_", "G_EFFORT_", "subagent_type", "spawn_agent",
                        "subagent-dispatch-contract.md", "（已移除）", "评审 cross-model",
                        "单开领域 cross-model", "评审独立性靠"):
            assert retired not in text, f"{path.relative_to(ROOT)}: {retired}"


def test_ci_and_checkpoint_do_not_invoke_deleted_scripts():
    paths = list((ROOT / ".github/workflows").glob("*.yml")) + [
        ROOT / "g-init/assets/hack/checkpoint-commit.sh",
    ]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for retired in ("check_async_branch_parity.py", "token_snapshot.py",
                        "outside-voice-job.py", "g-ship/scripts/"):
            assert retired not in text, f"{path.relative_to(ROOT)}: {retired}"


def test_readme_and_current_maps_do_not_advertise_removed_entries():
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").glob("workflow-*"))]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for retired in ("/g-ship", "/g-spec-review", "/g-code-review",
                        "anchor_lint.py", "g-guide.html", "（已移除）"):
            assert retired not in text, f"{path.relative_to(ROOT)}: {retired}"
