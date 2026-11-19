"""守「四条通则」的一致性 —— 真相源唯一，注入机械化，漂移机械可查。

【为什么需要这个测试】
四条通则被【复制】进每一个顶层 SKILL.md + 1 份 bundle 副本。复制就会漂。
（数量由 sync_principles.py 自报——文档里硬编码计数，新增一个 skill 就过期。）
而这正是 CLAUDE.md 基准 1 说的：能用「可固化规则 + 脚本」保证的一致性，MUST 机械化。
—— 复制是必要的（skill 是独立分发单元，跑在别的项目里，读不到本仓 CLAUDE.md），
   但复制【不能靠手】。
"""
import subprocess
import sys
from pathlib import Path
import pytest

from test_support.windows import bash_executable, bash_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sync_principles as SP  # noqa: E402

# 【发布 clone 边界】本门守的是**本仓两份人读载体**（CLAUDE.md / AGENTS.md）的一致性，
# 而发布快照把它们剔除了（开发期资产，见 .agents/skills/g-publish 的 DROP_PATHS）
# ⇒ 使用者 clone 下来跑 pytest 时这批门无从守。完整仓里照跑照红；缺载体时显式 skip
# 并说明——MUST NOT 静默 pass。
_HAS_CARRIERS = (SP.REPO / "CLAUDE.md").exists() and (SP.REPO / "AGENTS.md").exists()
needs_human_carriers = pytest.mark.skipif(
    not _HAS_CARRIERS,
    reason="本门守本仓 CLAUDE.md / AGENTS.md 双载体一致性；发布 clone 不含它们",
)


@needs_human_carriers
def test_every_skill_carries_the_principles():
    """⭐ 每一个顶层 SKILL.md 都与真相源逐字节一致 —— 漂了就红。

    修：python3 hack/sync_principles.py --apply
    """
    assert SP.main(["--check"]) == 0


def test_source_is_the_only_place_it_is_authored():
    """真相源存在，且自带 marker（注入靠 marker 定位，不靠解析结构）。"""
    text = SP.SOURCE.read_text(encoding="utf-8")
    assert text.lstrip().startswith(SP.START)
    assert SP.END in text


def test_skill_source_is_the_installed_principles_file():
    """通则源即分发文件，不维护第二份手写拷贝。"""
    assert SP.SOURCE == SP.REPO / "g-init" / "assets" / "hack" / "skill-principles.md"
    assert SP.SOURCE.is_file()


HEADLINES = ("能查的自己查", "先调研再给推荐", "MUST NOT 拿现状反驳目标", "方案尽量简化")


def test_consumer_project_snippet_carries_all_three():
    """g-init 铺进【消费项目】CLAUDE.md/AGENTS.md 的托管块 MUST 带全三条。

    【为什么不逐字节比对】：受众不同 —— 那里的读者是「在这个项目里干活的 agent」，
    不是 gear skill 自己，所以传播纪律/fan-out 那些 skill 内部的话不该出现。
    ∴ 允许改写措辞，但【三条一条都不许少】——守的是这个。

    加第四条通则时，本测试会红 ⇒ 强制你也去更新消费项目的那份。
    """
    snip = (SP.REPO / "g-init" / "assets" / "snippets" / "claude-section.md") \
        .read_text(encoding="utf-8")
    for h in HEADLINES:
        assert h in snip, f"消费项目托管块缺了通则「{h}」"


def test_both_sources_carry_all_three():
    """两个源（skill 味 / 项目味）措辞可以不同，但【三条一条不许少】。

    加第四条通则时，两个源 + 消费项目 snippet 一起红 ⇒ 强制你三处都更新。
    """
    for src in (SP.SOURCE, SP.SOURCE_PROJECT):
        text = src.read_text(encoding="utf-8")
        for h in HEADLINES:
            assert h in text, f"{src.name} 缺了通则「{h}」"


def test_render_updates_every_block_not_just_the_first():
    """⭐ 一个文件里有多份托管块时，【每一份】都要被回填。

    CLAUDE.md / AGENTS.md 各有两份：顶部（本仓 dogfood）+ 文末（g-init 铺设的
    工作流托管区块自带）。只更新首个 ⇒ 第二份静默留旧版、同一文件自相矛盾，
    而 --check 照样报绿 —— 这是【假绿】。
    """
    stale = "## 四条通则（旧版占位）\n"
    text = (f"# T\n\n{SP.START} x -->\n{stale}{SP.END}\n\n"
            f"中间正文\n\n{SP.START} x -->\n{stale}{SP.END}\n\n尾部\n")

    out = SP.render(text, SP.SOURCE_PROJECT)

    assert "旧版占位" not in out, "有块没被回填"
    assert len(SP._blocks(out)) == 2, "块数不该变"
    assert out.count("真人用户明确指示优先") == 2
    assert "中间正文" in out and "尾部" in out
    assert SP.render(out, SP.SOURCE_PROJECT) == out, "render 必须幂等"


def test_apply_writes_lf_line_endings(tmp_path, monkeypatch):
    """--apply 回填后的文件 MUST 是 LF（仓内 .gitattributes 一律 LF）；Windows 上不指定 newline
    会把整份文件写成 CRLF，制造整文件 diff。"""
    probe = tmp_path / "probe.md"
    probe.write_bytes(f"# T\n\n{SP.START} x -->\n旧版\n{SP.END}\n".encode("utf-8"))
    monkeypatch.setattr(SP, "skills", lambda: [])
    monkeypatch.setattr(SP, "PROJECT_TARGETS", [probe])
    assert SP.main(["--apply"]) == 0
    data = probe.read_bytes()
    assert b"\r" not in data and "真人用户明确指示优先".encode("utf-8") in data


@needs_human_carriers
def test_every_block_in_project_targets_matches_source():
    """本仓 CLAUDE.md / AGENTS.md / claude-section.md 的【每一份】块 == 真相源全文。"""
    body = SP.block(SP.SOURCE_PROJECT).strip()
    for p in SP.PROJECT_TARGETS:
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        spans = SP._blocks("".join(lines))
        assert spans, f"{p.name} 没有托管块"
        for s, e in spans:
            got = "".join(lines[s:e + 1]).strip()
            assert got == body, f"{p.name} 第 {s + 1} 行起的托管块与真相源不一致"
