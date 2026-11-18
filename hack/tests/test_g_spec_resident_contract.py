"""`g-spec` 薄入口的公开契约门。

被测 seam 是安装后用户与宿主实际读取的 `g-spec/SKILL.md`，以及入口按条件路由到的
versioned references。测试只观察这组公开 Markdown 契约，不解析实现私有结构。
"""

import re
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "g-spec" / "SKILL.md"


RESIDENT_CONTRACT = {
    "frontmatter": ("name: g-spec",),
    "principles": (
        "<!-- g:principles:start",
        "### ① 能查的自己查，能调研的自己调研",
        "### ② 不确定的方案，先调研再给推荐",
        "### ③ 以最终目标为准",
        "### ④ 方案尽量简化",
        "<!-- g:principles:end -->",
    ),
    "phase-0": ("## 第零步", "openspec --version", "openspec list", "### 0.3 重入探测"),
    "phase-a": ("## 相位 A", "MUST NOT 借批量甩开放题", "收束进的是 B，不是 C"),
    "phase-b": ("## 相位 B", "## 承重约束", "g-spec-grill"),
    "phase-c": (
        "## 相位 C",
        "openspec instructions <artifact>",
        "resolvedOutputPath",
        "`context` / 当前 artifact 的 `rules`",
        "作为生成约束",
        "MUST NOT 复制进产物",
        "resolve-workflow.sh",
    ),
    "c1-four-verdicts": (
        "### C.1 起手核验纪要（四判，缺一即拒）",
        "`decision-memo.md` **存在**",
        "`## 拍板决策` 与 `## 承重约束` **非空**",
        "**身份字段匹配当前盘面**",
        "**`decision_hash` 重算后匹配**",
    ),
    "final-review": (
        "## 终审",
        "整个 change 目录",
        "decision-memo.md",
        "design ↔ specs",
        "非平凡 design 至少一张",
        "TG-18 tasks 含测试覆盖图",
    ),
    "strict-validate": ("openspec validate", "--strict", "validate --strict"),
    "checkpoints": ("g-spec-grill", "g-spec-generate"),
    "exit-sequence": (
        "## 出口序列",
        "1. /clear",
        "2. 可选：切换模型",
        "3. /g-review spec",
    ),
}


REFERENCE_ROUTES = {
    "diagnostics": {
        "path": "references/degradation-ladder.md",
        "condition": "仅在发生失败、降级或需要诊断时读取",
        "tokens": ("# 降级阶梯", "problem + cause + fix", "## 4. 失败模式表"),
    },
    "evolution": {
        "path": "references/evolution-notes.md",
        "condition": "仅在审计历史依据或设计未来 T132 gate 时读取",
        "tokens": (
            "# 演进依据与未来门契约",
            "分支 A",
            "checkpoint(g-spec-grill)",
            "分支 B",
            "checkpoint(grill)",
            "g:grill-done",
            "T132 保持 OPEN",
        ),
    },
    "scope-cohesion": {
        "path": "references/scope-cohesion-check.md",
        "condition": "B.7 item 3 做 scope 内聚检查时读取",
        "tokens": (
            "# scope 内聚检查",
            "change-decomposition-standard.md",
            "一个完整内聚的阶段结果",
            "拆分/合并建议",
            "MUST NOT 基于未拍板的新范围推进",
        ),
    },
}


def _text(path: Path = SKILL) -> str:
    return path.read_text(encoding="utf-8")


def test_entry_is_within_unicode_character_budget():
    text = _text()
    assert len(text) <= 18_000, f"g-spec/SKILL.md 有 {len(text)} 个 Unicode 字符，超过 18,000"


def test_frontmatter_is_the_real_document_frontmatter():
    match = re.match(r"\A---\n(?P<body>.*?)\n---\n", _text(), flags=re.DOTALL)
    assert match, "入口缺 YAML frontmatter"
    frontmatter = match.group("body")
    assert re.search(r"^name:\s*g-spec$", frontmatter, flags=re.MULTILINE)
    assert not re.search(r"^disable-model-invocation:\s*true$", frontmatter, flags=re.MULTILINE), (
        "g-spec 已解除手动触发限制（simplify-workflow）——frontmatter MUST NOT 再声明"
        " disable-model-invocation: true"
    )
    assert re.search(r"^description:\s*>$", frontmatter, flags=re.MULTILINE)


def test_resident_contract_tokens_have_substantive_semantics():
    text = _text()
    for capability, tokens in RESIDENT_CONTRACT.items():
        missing = [token for token in tokens if token not in text]
        assert not missing, f"常驻契约 {capability} 缺少实质语义锚：{missing}"


def _assert_reference_routes(entry: str) -> None:
    for category, contract in REFERENCE_ROUTES.items():
        path = contract["path"]
        condition = contract["condition"]
        route = re.compile(
            rf"(?m)^- {re.escape(condition)}\s+"
            rf"\[[^\]]+\]\({re.escape(path)}\)"
        )
        assert route.search(entry), (
            f"{category} reference 必须由同一列表项中的加载条件和非空标签相对链接共同路由"
        )

        target = SKILL.parent / path
        assert target.is_file(), f"{category} reference 不可达：{target}"
        content = _text(target)
        headings = re.findall(r"^#{1,6}\s+\S.*$", content, flags=re.MULTILINE)
        assert len(headings) >= 2, f"{category} reference 只有空标题或无实质结构"
        for token in contract["tokens"]:
            assert token in content, f"{category} reference 缺语义锚：{token}"


def test_on_demand_references_have_conditions_paths_and_content():
    _assert_reference_routes(_text())


@pytest.mark.parametrize(
    "degraded_route",
    (
        "- 仅在发生失败、降级或需要诊断时读取\n  [](references/degradation-ladder.md)",
        "- 仅在发生失败、降级或需要诊断时读取\n  其它文字\n"
        "  [`references/degradation-ladder.md`](references/degradation-ladder.md)",
    ),
)
def test_reference_route_rejects_bare_or_detached_links(degraded_route):
    entry = _text()
    valid_route = (
        "- 仅在发生失败、降级或需要诊断时读取\n"
        "  [`references/degradation-ladder.md`](references/degradation-ladder.md)"
    )
    with pytest.raises(AssertionError, match="diagnostics reference"):
        _assert_reference_routes(entry.replace(valid_route, degraded_route, 1))


def test_retired_delegation_protocol_has_no_execution_route():
    entry = _text()
    assert "外派执行协议已退役" in entry
    assert "外派时读取" not in entry
    protocol = _text(SKILL.parent / "references/delegation-protocol.md")
    assert "不提供外派执行协议" in protocol
    assert "secret-scan" not in protocol
    assert "G_TIER" not in protocol


def test_codex_claim_is_limited_to_observed_user_trigger():
    text = _text()
    assert "Codex 当前只观察到用户显式触发已被接受" in text
    assert "没有本 session 可调用的 Skill 执行面" in text
    assert "MUST NOT 把接口缺席写成模型调用已被拒绝" in text


def test_final_review_accepts_change_directory_traceability():
    text = _text()
    assert "追溯边界是整个 change 目录" in text
    assert "只在 `decision-memo.md` 中保留被砍候选与理由也合法" in text
    assert "design.md` 的一行纪要指针是合法路径" in text


def test_t132_contract_is_documented_but_not_implemented():
    entry = _text()
    notes = _text(SKILL.parent / "references/evolution-notes.md")
    assert "T132 未来 gate 尚未实现，保持 OPEN" in entry
    assert "A 需要身份、hash、必填节有效的 `decision-memo.md`" in notes
    assert "B 需要既有 `checkpoint(grill)` 或未来 gate 明确认可的 `g:grill-done` 锚" in notes
    assert "本 reference 不实现 gate" in notes


# ── 指令层修订的在场锚（删掉它自称守的那句 ⇒ 红；needle 整句连读，防被别处同词满足）──────────

def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _span(text: str, start: str, end: str) -> str:
    i = text.index(start)
    return text[i:text.index(end, i)]


def test_c4_validate_runs_only_after_specs_and_at_final_review():
    """每份产物写后只判存在态；`validate --strict` 只在 specs 写完后与终审时跑。
    每份写后都跑会在 proposal/design 处必红（change 尚无 delta），把合格产物送进重试死循环。"""
    c4 = _span(_squash(_text()), "###C.4", "##终审")
    assert "每写完一份产物只判**存在态**" in c4
    assert "①`specs`产物写完后" in c4 and "②终审复核" in c4
    assert "`skip_specs`的change只在终审判" in c4
    assert "判该产物**未完成**" not in c4, "「每份产物写后 validate 不过即未完成」的旧措辞复活了"
    ladder = _squash(_text(SKILL.parent / "references/degradation-ladder.md"))
    assert "**MUSTNOT**在此时跑validate并据其判红" in ladder


def test_reentry_complete_requires_generate_checkpoint():
    """`isComplete` 只看文件存在：没有 `checkpoint(g-spec-generate)` 或目录不干净 ⇒ 待终审，补跑终审。"""
    text = _squash(_text())
    assert "`isComplete=true`只证明文件齐全" in text
    assert "含`checkpoint(g-spec-generate)`**且**`gitstatus--porcelain--openspec/changes/<name>/`为空" in text
    assert "判**待终审**——补跑终审+checkpoint，MUSTNOT拒绝或跳过终审" in text
    details = _squash(_text(SKILL.parent / "references/execution-protocol-details.md"))
    assert "|`待终审`|" in details
    assert "grep-q'^checkpoint(g-spec-generate)'" in details
    assert "**MUSTNOT单凭`isComplete=true`判complete**" in details


def test_skip_specs_has_a_process_owner():
    """零 spec 级行为变更：B.7 拍板记进纪要，C.3 才写 marker（白名单只放行这一个键）。"""
    text = _squash(_text())
    b7 = _span(text, "###B.7", "###B.8")
    assert "**零spec级行为变更？**" in b7 and "作为一条**拍板决策**写进纪要" in b7
    assert "**MUSTNOT为过validate编造Requirement。**" in b7
    c3 = _span(text, "###C.3", "###C.4")
    assert "向`.openspec.yaml`**追加**`skip_specs:true`" in c3
    assert "纪要无该决策⇒MUSTNOT写此键" in c3
    assert "只追加`skip_specs`一个键，其余键MUSTNOT改" in c3


def test_draft_memo_leaves_finalize_fields_to_convergence():
    """草稿只写身份三字段；`generated_at`/`decision_hash` 缺失 = 未定稿（C.1 的 undrafted 分支）。"""
    b1 = _span(_squash(_text()), "**④立即落最小草稿纪要**", "###B.2")
    assert "`generated_at`与`decision_hash`**不写**，B.8⑤定稿才补" in b1
    schema = _squash(_text(SKILL.parent / "references/decision-memo-schema.md"))
    assert "草稿纪要（B.1④）**只写**`schema_version`/`change`/`branch`" in schema


def test_memo_gate_is_located_in_the_g_done_gate():
    """「机械门」MUST 指向消费仓真会执行的位置（`/g-done` gate），不能只是本仓自测。"""
    entry = _squash(re.sub(r"(?m)^>", "", _text()))           # 该句在引用块内，先去掉行首 `>`
    assert "由`/g-done`的gate（`ship_gate`）在送设计审前检查，不过即REFUSE_START退回`/g-spec`" in entry
    schema = _squash(_text(SKILL.parent / "references/decision-memo-schema.md"))
    assert "**机械门**（pytest）" not in schema
    assert "|已定稿|frontmatter`decision_hash`非空" in schema


def test_retired_agent_definitions_are_removed():
    assert not (SKILL.parent / "agents").exists(), "已退役的外派角色定义仍在仓内（会被全局安装）"
    assert "外派见" not in _text()
