import sys
import os
import subprocess
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import retro_report as R


def _mk(root, rel):
    p = root / rel
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_discover_active_and_archive(tmp_path):
    _mk(tmp_path, "openspec/changes/foo")                      # 活动
    _mk(tmp_path, "openspec/changes/archive/2026-07-02-bar")   # 归档
    _mk(tmp_path, "openspec/changes/archive/2026-07-05-foo")   # foo 也有归档
    got = R.discover_changes(str(tmp_path))
    assert set(got) == {"foo", "bar"}
    assert got["foo"]["active"] is True
    assert got["foo"]["archive_dir"].endswith("2026-07-05-foo")
    assert got["bar"]["active"] is False
    assert got["bar"]["archive_dir"].endswith("2026-07-02-bar")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def _init_repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _commit(root, files: dict, msg):
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


def test_seed_mass_excluded_and_0_1_guard(tmp_path):
    root = _init_repo(tmp_path)
    # 创世 mass 提交碰 3 个 change dir → seed-mass
    _commit(root, {
        "openspec/changes/archive/2026-07-02-seedA/proposal.md": "x",
        "openspec/changes/archive/2026-07-02-seedB/proposal.md": "y",
        "openspec/changes/archive/2026-07-02-seedC/proposal.md": "z",
    }, "chore:初始化")
    changes = R.discover_changes(str(root))
    seed = R.seed_mass_shas(str(root), threshold=3)
    b = R.boundary_for_change(str(root), "seedA", changes["seedA"], seed)
    # seedA 的 pre-archive 路径 0 提交（创世只碰 archive 路径），兜底 archive 后剔 seed-mass → 仍 0/1
    assert b["unresolved"] is True
    assert len(b["commits"]) == 0  # seed-mass 提交被剔除后 archive 兜底也为空——若剔除失效会剩 1 条，此断言区分二者
    assert "边界不可解析" in b["note"]


def test_normal_change_boundary(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(grill)")
    changes = R.discover_changes(str(root))
    seed = R.seed_mass_shas(str(root), threshold=3)
    b = R.boundary_for_change(str(root), "foo", changes["foo"], seed)
    assert b["unresolved"] is False
    assert len(b["commits"]) == 2
    assert b["commits"][0]["subject"] == "checkpoint(ff)"


def test_archived_change_full_boundary_via_bare_path(tmp_path):
    """[impl-review-fix] F1 反证测试：归档 change 即使 active_dir=None（磁盘上已不在活动区），
    boundary_for_change 也必须通过裸 pre-archive 路径 openspec/changes/<name> 找回全部历史提交，
    不能只剩 1 条 archive rename 提交——这正是 17/18 归档 change 假性「边界不可解析」的根因。
    修前：只查 active_dir(None→[]) 再兜底 archive_dir（1 条 rename）→ unresolved True, commits=1。
    修后：裸路径∪archive路径按 sha 去重 → 应捞回 ff/grill/impl-review + rename 共 4 条。
    """
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(grill)")
    _commit(root, {"openspec/changes/foo/tasks.md": "c"}, "checkpoint(impl-review)")
    # 归档：git mv 全目录进 archive，active_dir 从此在磁盘上消失
    (root / "openspec/changes/archive").mkdir(parents=True, exist_ok=True)
    _git(root, "mv", "openspec/changes/foo", "openspec/changes/archive/2026-07-06-foo")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "chore(openspec): archive foo")

    changes = R.discover_changes(str(root))
    assert changes["foo"]["active_dir"] is None
    assert changes["foo"]["archive_dir"] is not None

    seed = R.seed_mass_shas(str(root))
    b = R.boundary_for_change(str(root), "foo", changes["foo"], seed)
    assert b["unresolved"] is False, f"边界应可解析，实际 note={b['note']!r} commits={b['commits']}"
    assert len(b["commits"]) == 4  # ff + grill + impl-review + archive-rename
    subjects = [c["subject"] for c in b["commits"]]
    assert subjects[0] == "checkpoint(ff)"
    assert subjects[-1] == "chore(openspec): archive foo"


def test_run_git_failure_traces_stderr(tmp_path, capsys):
    # T60 反证：git 失败（returncode≠0）须向 stderr 留痕，否则「git 报错」与「真无提交」
    # 都表现为空 stdout、静默不可区分。修前 _run_git 不看 returncode → stderr 无留痕 → FAIL。
    root = _init_repo(tmp_path)
    out = R._run_git(str(root), "nonexistent-subcommand-xyz")
    captured = capsys.readouterr()
    assert out == ""                              # 失败时 stdout 空（返回契约不变）
    assert "git 失败" in captured.err              # 但有可见留痕，不静默


def test_run_git_success_no_stderr_noise(tmp_path, capsys):
    # T60：正常 git 成功不应产生 stderr 噪声（留痕只在失败路径）。
    root = _init_repo(tmp_path)
    _commit(root, {"a.txt": "x"}, "init")
    R._run_git(str(root), "log", "--format=%H")
    assert capsys.readouterr().err == ""


def test_map_stage_longest_prefix(tmp_path):
    assert R.map_stage("checkpoint(impl-review)") == "code-review"
    assert R.map_stage("checkpoint(impl-review-fix)") == "code-review"
    assert R.map_stage("checkpoint(spec-review-autoplan)") == "spec-review"
    assert R.map_stage("checkpoint(spec-review-gate)") == "spec-review"
    assert R.map_stage("checkpoint(design-gate)") == "spec-review"
    assert R.map_stage("checkpoint(writing-plans)") == "impl"
    assert R.map_stage("checkpoint(model-baseline)") == "impl"
    assert R.map_stage("checkpoint(g-retro:task3-boundary)") == "impl"
    assert R.map_stage("checkpoint(final-review)") == "code-review"
    assert R.map_stage("checkpoint(ff)") == "ff"
    assert R.map_stage("checkpoint(grill)") == "grill"
    # g-spec 的两个相位锚：匹配是 startswith，故「grill」不是 `g-spec-grill` 的前缀，
    # 二者 MUST 各自单列；漏任一条即落 unknown 桶，相位锚等于白打。
    assert R.map_stage("checkpoint(g-spec-grill)") == "grill"
    assert R.map_stage("checkpoint(g-spec-generate)") == "ff"
    assert R.map_stage("checkpoint(g-spec-grill): 相位 B 收敛") == "grill"
    assert R.map_stage("feat(x): 随手") == "unknown"


def test_namespaced_step_slug_falls_back_to_tail():
    """`checkpoint(<change>:<step>)` 的 `<step>` 段 MUST 参与前缀匹配。

    [impl-review-fix] F1：旧实现只在 `task\\d+` / `-impl` 两条判定里剥命名空间，
    前缀匹配仍拿含 `<change>:` 前缀的整串去比 ⇒ 仓内 27 个 checkpoint 的 `<step>` 段
    **精确等于**既有规则却全落 unknown（plan×13 / grill×5 / ff×4 / spec-review×2 /
    propose×2 / design-gate×1）。`g-implement/SKILL.md:287` 明写
    `checkpoint-commit.sh "<change>:plan"`，即目标态 producer 就在产出这种形态。
    """
    assert R.map_stage("checkpoint(add-g-spec:plan)") == "other"
    assert R.map_stage("checkpoint(add-codex-host-support:grill)") == "grill"
    assert R.map_stage("checkpoint(add-codex-host-support:ff)") == "ff"
    assert R.map_stage("checkpoint(add-codex-host-support:spec-review)") == "spec-review"
    assert R.map_stage("checkpoint(add-codex-host-support:spec-review-amend)") == "spec-review"
    assert R.map_stage("checkpoint(harden-hr-tg-anchor-consistency:design-gate)") == "spec-review"
    assert R.map_stage("checkpoint(three-lens-decision-framework:propose)") == "other"
    assert R.map_stage(
        "checkpoint(harden-hr-tg-anchor-consistency:impl-review-fix-parsing)") == "code-review"
    # 回退**只在整串无命中时**发生 ⇒ 既有的整串匹配语义不变。
    assert R.map_stage("checkpoint(g-spec-grill)") == "grill"
    assert R.map_stage("checkpoint(g-retro:task3-boundary)") == "impl"
    # `<step>` 段无任何规则可依 ⇒ 照旧 unknown（不猜）。
    assert R.map_stage("checkpoint(g-retro-cleanup:t58-tilde-fence)") == "unknown"


def test_two_review_skill_slugs_map_to_their_stage():
    """[impl-review-fix] F1（面治）：`g-` 前缀的两个评审 slug 与 `g-spec-*` 同形。

    上一轮只补了 `g-spec-grill` / `g-spec-generate` 两条，同形的
    `g-code-review`（仓内 3 次）与 `g-spec-review`（1 次）漏掉 —— 同一失效模式。
    """
    assert R.map_stage("checkpoint(g-code-review)") == "code-review"
    assert R.map_stage("checkpoint(g-spec-review)") == "spec-review"


def test_short_prefix_tail_fallback_requires_a_token_boundary():
    """[impl-review-fix fix2] F-B：tail 回退把 ≤4 字符的短前缀误配到更长的词上。

    F1 的回退放宽了匹配面（整串无命中 ⇒ 拿 `tail` 再试一次），而 `gate` / `ff` / `plan`
    这三条短规则是**词**、不是**前缀**：`gateway-refactor` / `ffmpeg-upgrade` / `planner`
    会被静默吞进 spec-review / ff / other。归因错了不报错、不缺文件 —— 与本词表要治的病同型。
    ⇒ 短前缀（≤ `_TAIL_STRICT_MAXLEN`）在 tail 回退里 MUST 要求 token 边界（全等或后接 `-`）。
    """
    # 误配面：token 边界不成立 ⇒ 不猜，落 unknown
    assert R.map_stage("checkpoint(c:gateway-refactor)") == "unknown"
    assert R.map_stage("checkpoint(c:ffmpeg-upgrade)") == "unknown"
    assert R.map_stage("checkpoint(c:planner)") == "unknown"
    # 边界另一侧：全等 / 后接 `-` 照常命中 —— F1 的收益一分不丢
    assert R.map_stage("checkpoint(c:gate)") == "spec-review"
    assert R.map_stage("checkpoint(c:gate-frontmatter)") == "spec-review"
    assert R.map_stage("checkpoint(c:ff)") == "ff"
    assert R.map_stage("checkpoint(c:ff-amend)") == "ff"
    assert R.map_stage("checkpoint(c:plan)") == "other"
    assert R.map_stage("checkpoint(c:plan-b)") == "other"
    # 长前缀不受此限（`spec-review-amend` 这类既有形态照旧）
    assert R.map_stage("checkpoint(c:spec-reviewX)") == "spec-review"
    # 严格化**只加在回退这一跳**上 ⇒ 整串匹配（change 名本身带阶段词）语义一字未动
    assert R.map_stage("checkpoint(gateway-refactor)") == "spec-review"


def test_archive_rename_detects_done(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    # 用 git mv 模拟归档
    (root / "openspec/changes/archive/2026-07-06-foo").mkdir(parents=True)
    _git(root, "mv", "openspec/changes/foo/proposal.md",
         "openspec/changes/archive/2026-07-06-foo/proposal.md")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "chore(openspec): archive foo")
    sha = _git(root, "rev-parse", "HEAD").strip()
    assert R.is_archive_rename(str(root), sha, "foo") is True


def test_stage_walltimes_and_negative_clamp(tmp_path):
    # absorb-gstack-autoplan：attribute-to-next（checkpoint=工作完成点，区间归其完成点）——
    # a→b 的 600s 是「做 grill 用的时间」（b 才是 grill 完成的标记），故归 nxt=b 的阶段 grill，
    # 不再归 cur=a 的阶段 ff（首提交 a 自身的阶段 ff 因无前驱 Δ 而不入账）。
    commits = [
        {"sha": "a", "ts": 1000, "subject": "checkpoint(ff)"},
        {"sha": "b", "ts": 1600, "subject": "checkpoint(grill)"},       # ff→grill: 600s=10min 归 grill（nxt）
        {"sha": "c", "ts": 1500, "subject": "checkpoint(spec-review)"}, # 负 Δ → 钳 0 归 spec-review（nxt）
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits)
    assert got["stages"].get("ff", 0) == 0.0
    assert got["stages"]["grill"] == 10.0
    assert got["stages"].get("spec-review", 0) == 0.0
    assert got["reorder_suspected"] is True
    assert got["n_ckpt"] == 3


def test_stage_walltimes_historical_spec_review_autoplan_sequence_no_longer_misattributed(tmp_path):
    """回归测试（历史序列，含 checkpoint(spec-review-autoplan) 中间标签）：absorb-gstack-autoplan 修正
    既有错账——旧口径 attribute-to-previous 下，generate→autoplan 区间因 cur=g-spec-generate 映射
    stage="ff" 而误归 ff（design.md「墙钟归属」段实证的错账）。attribute-to-next 后，该区间与后续
    autoplan→spec-review 区间均归 nxt 的阶段（spec-review-autoplan/spec-review 皆映射 spec-review），
    Step1 广审墙钟不再泄漏进 ff。"""
    commits = [
        {"sha": "a", "ts": 1000, "subject": "checkpoint(g-spec-generate)"},
        {"sha": "b", "ts": 1000 + 600, "subject": "checkpoint(spec-review-autoplan)"},  # Step1 广审 600s
        {"sha": "c", "ts": 1000 + 600 + 300, "subject": "checkpoint(spec-review)"},      # Step2/3 300s
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits)
    assert got["stages"].get("ff", 0) == 0.0                 # 不再误归 ff
    assert got["stages"]["spec-review"] == 15.0               # 600s+300s = 900s = 15min，全归 spec-review


def test_stage_walltimes_new_single_checkpoint_sequence_attributes_to_spec_review(tmp_path):
    """回归测试（新序列，DD1 单批 dispatch 下中间 checkpoint(spec-review-autoplan) 已退役）：
    generate→spec-review 单一区间整体归 spec-review（本 skill 只剩一次 checkpoint(spec-review)）。"""
    commits = [
        {"sha": "a", "ts": 1000, "subject": "checkpoint(g-spec-generate)"},
        {"sha": "b", "ts": 1000 + 900, "subject": "checkpoint(spec-review)"},  # 单批 dispatch 900s
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits)
    assert got["stages"].get("ff", 0) == 0.0
    assert got["stages"]["spec-review"] == 15.0


def test_stage_walltimes_archive_rename_attributed_via_nxt_not_cur(tmp_path):
    """`is_archive_rename` 判定对象由 cur 换 nxt：归档 rename 提交与其前一个 checkpoint 之间的墙钟
    （真实是"做归档收尾用的时间"）现正确归 done，不再误归前一个 checkpoint 自身的阶段
    （旧口径下 impl-review→archive 区间会误归 code-review，因 cur=impl-review 映射 code-review）。"""
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(impl-review)")
    sha_impl = _git(root, "rev-parse", "HEAD").strip()
    (root / "openspec/changes/archive/2026-07-06-foo").mkdir(parents=True)
    _git(root, "mv", "openspec/changes/foo/proposal.md",
         "openspec/changes/archive/2026-07-06-foo/proposal.md")
    _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "chore(openspec): archive foo")
    sha_archive = _git(root, "rev-parse", "HEAD").strip()
    commits = [
        {"sha": sha_impl, "ts": 1000, "subject": "checkpoint(impl-review)"},
        {"sha": sha_archive, "ts": 1000 + 600, "subject": "chore(openspec): archive foo"},
    ]
    got = R.stage_walltimes(str(root), "foo", commits)
    assert got["stages"]["done"] == 10.0
    assert got["stages"].get("code-review", 0) == 0.0


def test_build_report_coverage_counts(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(grill)")
    md = R.build_report(str(root))
    assert "> 覆盖 1 change / 边界不可解析 0" in md
    assert "foo" in md
    assert "in-progress" in md  # foo 是活动 change


def test_build_report_per_change_stage_columns(tmp_path):
    """[impl-review-fix F12] per-change 表列含 4 个阶段 Δ 列 spec-rev Δ | impl Δ | code-rev Δ | done Δ
    ——「某 change 卡在哪个阶段」须可从表上直接读出。"""
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(spec-review)")
    _commit(root, {"openspec/changes/foo/tasks.md": "c"}, "checkpoint(foo:task1-impl)")
    md = R.build_report(str(root))
    assert "spec-rev Δ" in md
    assert "impl Δ" in md
    assert "code-rev Δ" in md
    assert "done Δ" in md


def test_build_report_has_no_retired_value_or_token_sections(tmp_path):
    """价值维（lens-metric）、tokens（token-log.jsonl）、hr-tg、per-镜实修率的产出方已随旧架构
    移除——报告 MUST NOT 再出现这些列/段（否则新 change 永远显示「无度量锚 / —」，噪声当数据）。"""
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(spec-review)")
    md = R.build_report(str(root))
    for retired in ("有真锚", "待复评", "Σfindings", "采纳率", "hr_tg", "tokens", "聚合③", "聚合④",
                    "Codex 用量覆盖"):
        assert retired not in md, f"退役维度残留：{retired}"
    assert "## 聚合① 阶段占比" in md and "## 聚合② 成本双峰" in md


def test_atomic_write_preserves_on_replace_and_no_tmp(tmp_path):
    target = tmp_path / "openspec/retro/report.md"
    R.atomic_write(str(target), "hello")
    assert target.read_text() == "hello"
    # 无残留 tmp
    assert not any(p.suffix == ".tmp" for p in (tmp_path / "openspec/retro").iterdir())


def test_report_idempotent(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(grill)")
    a = R.build_report(str(root))
    b = R.build_report(str(root))
    assert a == b


def test_atomic_write_preserves_mode_on_overwrite(tmp_path):
    if os.name == "nt":
        pytest.skip("Windows does not expose POSIX mode bits")
    target = tmp_path / "openspec/retro/report.md"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    os.chmod(str(target), 0o644)
    R.atomic_write(str(target), "new")           # 覆盖已存在文件
    assert target.read_text() == "new"
    mode = os.stat(str(target)).st_mode & 0o777
    assert mode == 0o644, f"权限被静默收紧到 {oct(mode)}（D13：覆盖须保原 0644，非 mkstemp 的 0600）"


def test_main_writes_report_and_returns_zero(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(grill)")
    rc = R.main(["--root", str(root)])
    assert rc == 0
    assert (root / "openspec/retro/report.md").is_file()


def test_main_rejects_retired_scan_codex_sessions_flag(tmp_path):
    with pytest.raises(SystemExit) as exc:
        R.main(["--root", str(tmp_path), "--scan-codex-sessions"])
    assert exc.value.code == 2


def test_main_cli_subprocess_under_gbk_stdout(tmp_path):
    """Windows smoke 泳道以 PYTHONIOENCODING=gbk 直跑本脚本——编码前导须让中文输出不崩。"""
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    script = Path(R.__file__)
    r = subprocess.run([sys.executable, str(script), "--root", str(root)],
                       capture_output=True, env=dict(os.environ, PYTHONIOENCODING="gbk"))
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert (root / "openspec/retro/report.md").is_file()


# ============================ 一览（语义化总结）============================
DECISION_WORDS = ["说明", "意味着", "因此", "所以", "建议", "应该",
                  "该砍", "值得", "可考虑", "淘汰", "降采样", "优化掉"]


def test_fmt_dur_precision():
    # 亚分钟保留小数（不 round 成 "0 min" 骗人）；≥1min 整数；≥60min 转 hr
    assert R._fmt_dur(0.2) == "0.2 min"
    assert R._fmt_dur(7) == "7 min"
    assert R._fmt_dur(30.4) == "30 min"
    assert R._fmt_dur(120) == "2.0 hr"
    assert R._fmt_dur(756) == "12.6 hr"


def test_semantic_summary_card_and_paragraph():
    stage = {"spec-review": 400.0, "impl": 300.0, "code-review": 100.0}
    cost = [("big", 756.0, False), ("small", 7.0, False), ("boundary", 0.0, True)]
    out = R.semantic_summary(4, 1, stage, cost, 90.0)
    # 指标卡：纯计数，无平均值列
    assert "| 复盘 change | 总墙钟 | 人类门 | 边界不可解析 |" in out
    assert "| 4 | ~13.3 hr | ~1.5 hr | 1 |" in out   # 总墙钟=stage_totals 之和 800min=13.3hr
    assert "平均" not in out
    # 段落：覆盖量 / 阶段大头 / 成本两端(含倍数)
    assert "覆盖 **4 个 change**" in out
    assert "其中人类门约 1.5 hr" in out
    assert "设计审 50%" in out and "写实现 38%" in out and "合计 88%" in out
    assert "最重的是 big（约 12.6 hr）" in out
    assert "最轻的是 small（7 min）" in out
    assert "相差约 108 倍" in out                      # 756/7≈108


def test_semantic_summary_no_decision_words():
    stage = {"spec-review": 400.0, "impl": 300.0}
    cost = [("big", 756.0, False), ("small", 7.0, False)]
    out = R.semantic_summary(4, 0, stage, cost, 30.0)
    for w in DECISION_WORDS:
        assert w not in out, f"决策/解读词泄漏: {w}"


def test_semantic_summary_no_walltime_degrades():
    # grand_total=0：总墙钟/人类门卡片显 "—"，无阶段句、无成本两端句，不崩
    out = R.semantic_summary(3, 3, {}, [("a", 0.0, True)], 0.0)
    assert "| 3 | — | — | 3 |" in out
    assert "时间集中在" not in out
    assert "耗时最重" not in out


def test_semantic_summary_subminute_no_absurd_ratio():
    # 最轻 change 亚分钟(0.2min)：如实显 0.2 min，但不给无意义倍数
    cost = [("big", 756.0, False), ("plan", 0.2, False)]
    out = R.semantic_summary(2, 0, {"impl": 756.2}, cost, 0.0)
    assert "最轻的是 plan（0.2 min）" in out
    assert "倍" not in out


def test_semantic_summary_single_change():
    # 仅 1 个有效墙钟 change：出"仅 X 有可解析墙钟"，不出两端/倍数
    out = R.semantic_summary(1, 0, {"impl": 50.0}, [("solo", 50.0, False)], 0.0)
    assert "仅 solo 有可解析墙钟" in out
    assert "最重的是" not in out


def test_build_report_includes_overview(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    md = R.build_report(str(root))
    assert "## 一览" in md
    assert "| 复盘 change | 总墙钟 | 人类门 | 边界不可解析 |" in md


# ── T29 / adr/0009(c)：人类门等待单列 ───────────────────────────────────────
def test_stage_walltimes_splits_grill_as_human_gate(tmp_path):
    commits = [
        {"sha": "a", "ts": 1000, "subject": "checkpoint(g-spec-generate)"},
        {"sha": "b", "ts": 1000 + 600, "subject": "checkpoint(g-spec-grill)"},   # grill 600s
        {"sha": "c", "ts": 1000 + 600 + 300, "subject": "checkpoint(spec-review)"},   # 300s
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits)
    assert got["human_gate"] == {"grill": 10.0}
    assert got["human_gate_min"] == 10.0
    assert got["total_min"] == 15.0
    assert got["total_excl_human_min"] == 5.0
    assert got["stages_excl_human"]["grill"] == 0.0
    assert got["stages_excl_human"]["spec-review"] == 5.0


def test_stage_walltimes_splits_design_approval_interval(tmp_path):
    commits = [
        {"sha": "a", "ts": 0, "subject": "checkpoint(spec-review)"},
        {"sha": "b", "ts": 600, "subject": "checkpoint(spec-review)"},      # 评审 10min
        {"sha": "c", "ts": 600 + 1800, "subject": "设计门拍板"},              # 拍板提交，subject 不可信
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits, approval_sha="c")
    assert got["human_gate"] == {"design-gate": 30.0}
    assert got["total_excl_human_min"] == got["total_min"] - 30.0
    assert got["stages_excl_human"].get("unknown", 0.0) == 0.0


def test_stage_walltimes_without_human_gate_signals_is_unchanged(tmp_path):
    commits = [
        {"sha": "a", "ts": 0, "subject": "checkpoint(spec-review)"},
        {"sha": "b", "ts": 600, "subject": "checkpoint(spec-review)"},
    ]
    got = R.stage_walltimes(str(tmp_path), "foo", commits)
    assert got["human_gate_min"] == 0.0
    assert got["total_excl_human_min"] == got["total_min"] == 10.0


def test_find_design_approval_sha_picks_first_true_commit(tmp_path):
    root = _init_repo(tmp_path)
    rpt = "openspec/changes/foo/spec-review-report.md"
    _commit(root, {rpt: "---\nship-gate:\n  design_approved: false\n---\n"}, "checkpoint(spec-review)")
    _commit(root, {rpt: "---\nship-gate:\n  design_approved: true\n---\n"}, "x")
    want = _git(root, "rev-parse", "HEAD").strip()
    _commit(root, {rpt: "---\nship-gate:\n  design_approved: true\n---\nmore\n"}, "y")
    assert R.find_design_approval_sha(str(root), "foo") == want


def test_find_design_approval_sha_none_when_never_approved(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/spec-review-report.md": "design_approved: false\n"}, "z")
    assert R.find_design_approval_sha(str(root), "foo") is None


def test_build_report_has_human_gate_columns(tmp_path):
    root = _init_repo(tmp_path)
    _commit(root, {"openspec/changes/foo/proposal.md": "a"}, "checkpoint(ff)")
    _commit(root, {"openspec/changes/foo/design.md": "b"}, "checkpoint(spec-review)")
    md = R.build_report(str(root))
    assert "人类门(min)" in md and "扣除后总墙钟(min)" in md and "spec-rev Δ(扣除后)" in md


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX mode bits")
def test_atomic_write_new_file_follows_umask(tmp_path):
    target = tmp_path / "openspec/retro/report.md"
    target.parent.mkdir(parents=True)
    old = os.umask(0o002)
    try:
        R.atomic_write(str(target), "new")
    finally:
        os.umask(old)
    assert (os.stat(str(target)).st_mode & 0o777) == 0o664


def test_g_recognizes_legacy_stage_names():
    assert R.map_stage("checkpoint(sdflow-spec-generate)") == "ff"
    assert R.map_stage("checkpoint(sdflow-code-review)") == "code-review"
