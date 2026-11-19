"""把「四条通则」托管区块（principles marker 家族）同步进目标文件。
（「广审镜定义」broad-mirror-def 家族的注入器已退役：g-roadmap 里那份即单一源，本脚本不再管。）

【为什么是内联复制，不是一行指针】
skill 是【独立分发单元】——symlink 装到 ~/.claude/skills/，跑在别的项目里，
那里读不到本仓的 CLAUDE.md。而「四条通则」是【每问一句话都要触发的立场】，
立场 MUST 在 prompt 里，不能藏在一个「模型可能不去 Read」的指针后面。

【那怎么防漂移】
真相源唯一（见下方 SOURCE / SOURCE_PROJECT），注入机械化（本脚本），漂移机械可查（--check）。
—— 这正是 CLAUDE.md 基准 1：能用「可固化规则 + 脚本」保证的一致性，优先机械化。

【语法面】
只认两个 marker token（start / end）+ 首个 H1（无既有块时的插入锚点）。都是
【单行字面量匹配】，语法面有界（基准 5）。MUST NOT 演化成「解析 Markdown 结构」。

用法：
    python3 hack/sync_principles.py --check     # 任一投放面漂了 → exit 1（CI / pytest 用）
    python3 hack/sync_principles.py --apply     # 回填全部投放面
"""
import argparse
import os
import sys

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "g-init" / "assets"

# 【两个源，因为受众不同 —— 不是同一段话的两份拷贝】
#   skill 味  → 读者是 skill 自己（SKILL 内部口径）
#   项目味    → 读者是「在这个项目里干活的 agent」（不该出现 skill 内部的话）
# 三条 headline 一条不许少 —— hack/tests/ 机械守（加第四条时两个源一起红）。
#
# 【为什么源在 assets/ 而不在 hack/】（CLAUDE.md：assets/ 是 bundle 的唯一权威源）：
#   - skill 味的源【就是】setup.sh 随 assets/hack/*.md 装进 ~/.g/hack/ 的那份通则文件。
#     源放别处 = 凭空多一份拷贝 = 凭空多一个漂移面。
#   - 项目味的源【就是】init 推给消费项目的那份 snippet 的一部分。
SOURCE = ASSETS / "hack" / "skill-principles.md"                    # skill 味（全局安装的通则源）
SOURCE_PROJECT = ASSETS / "snippets" / "principles-project.md"      # 项目味

# 项目味的投放面：
#   本仓 CLAUDE.md / AGENTS.md —— dogfood（我们自己就是一个「在这个项目里干活」的场景）
#   claude-section.md          —— g-init 铺进【消费项目】CLAUDE.md/AGENTS.md 的托管块模版
PROJECT_TARGETS = [
    REPO / "CLAUDE.md",
    REPO / "AGENTS.md",
    ASSETS / "snippets" / "claude-section.md",
]

START = "<!-- g:principles:start"
END = "<!-- g:principles:end -->"
LF = chr(10)

def block(src):
    """真相源的内容【就是】要注入的文本。零解析。"""
    return src.read_text(encoding="utf-8").strip() + "\n"


def skills():
    return sorted(p / "SKILL.md" for p in REPO.iterdir()
                  if p.is_dir() and (p / "SKILL.md").is_file())


def _blocks(text, start=START, end=END):
    """→ [(start_idx, end_idx)]：文本里【全部】托管块的行区间（含首尾 marker 行）。

    【为什么是「全部」而不是「首个」】：CLAUDE.md / AGENTS.md 各有【两份】——
    顶部一份（本仓 dogfood）+ 文末一份（g-init 铺设的工作流托管区块自带）。
    只更新首个 ⇒ 第二份静默留旧版 ⇒ 同一文件里两份通则自相矛盾，而 --check 照样报绿。
    这是【假绿】，不是省事。

    【为什么 start/end 是参数】：marker 家族曾不止一个，扫描逻辑参数化复用；
    默认值即 principles 家族——调用点 `_blocks(text)` 无需改动。
    """
    lines = text.splitlines(keepends=True)
    out, cursor = [], 0
    for i, l in enumerate(lines):
        if i < cursor or not l.startswith(start):
            continue
        ends = [j for j in range(i, len(lines)) if lines[j].startswith(end)]
        if not ends:
            raise SystemExit("[sync_principles] FAIL: 有 start 无 end —— 区块被手改坏了")
        out.append((i, ends[0]))
        cursor = ends[0] + 1
    return out


def _insert_anchor(lines):
    """无块时的插入点：首个 H1 之后；无 H1 则 frontmatter 之后。"""
    anchor = 0
    if lines and lines[0].strip() == "---":
        for j in range(1, len(lines)):
            if lines[j].strip() == "---":
                anchor = j + 1
                break

    for j in range(anchor, len(lines)):
        if lines[j].startswith("# "):
            anchor = j + 1
            break
    return anchor


def render(text, src, start=START, end=END):
    body = block(src)
    lines = text.splitlines(keepends=True)

    spans = _blocks(text, start, end)
    if not spans:
        anchor = _insert_anchor(lines)
        spans = [(anchor, anchor - 1)]   # 空区间 = 纯插入，不吞掉任何行

    out, cursor = "", 0
    for s, e in spans:
        head = out + "".join(lines[cursor:s])
        # 块前恰好一个空行（文件以块开头时不加）
        out = f"{head.rstrip(chr(10))}\n\n{body}" if head.strip() else body
        cursor = e + 1
    tail = "".join(lines[cursor:]).lstrip("\n")
    return f"{out}\n{tail}"


def targets():
    """→ [(文件, 该用哪个源)] —— 「四条通则」marker 家族的投放面。"""
    pairs = [(p, SOURCE) for p in skills()]
    pairs += [(p, SOURCE_PROJECT) for p in PROJECT_TARGETS]
    return pairs


def main(argv=None):
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    # 「四条通则」一个家族；render/--check/--apply 保留 marker 参数化以备未来新增家族。
    groups = [
        (targets(), START, END),
    ]

    drift = []
    absent = []
    total = 0
    for group_targets, start, end in groups:
        for p, src in group_targets:
            # 【投放面不在本 checkout 里】：发布快照剔除了 CLAUDE.md / AGENTS.md
            # （开发期资产，见 .agents/skills/g-publish 的 DROP_PATHS），而 setup.sh
            # 在使用者机器上照跑本门 ⇒ 裸 read_text 会 FileNotFoundError，让「报告漂移」
            # 变成「整个 --check 崩掉」，使用者装完第一眼看到一段 traceback。
            # 与上面 relpath 那条注释是同一类教训：**判定用的辅助操作，不该有能力中止判定。**
            # 不存在 ⇒ 不计入 total、不算漂移，末尾单列一行说明。
            if not p.exists():
                try:
                    absent.append(os.path.relpath(p, REPO))
                except ValueError:
                    absent.append(str(p))
                continue
            total += 1
            cur = p.read_text(encoding="utf-8")
            want = render(cur, src, start, end)
            if cur == want:
                continue
            # os.path.relpath 而非 Path.relative_to：后者对【仓外】的投放面直接抛 ValueError，
            # 于是「报告一个漂移」变成「整个 --check 崩掉」。投放面目录可被测试 monkeypatch 到
            # 仓外，此处只是【打印用的显示形式】，不该有能力中止判定。
            try:
                display = os.path.relpath(p, REPO)
            except ValueError:
                display = str(p)
            drift.append(display)
            if args.apply:
                # newline 显式写 LF：want 由通用换行读入（已是 LF）；不指定时 Windows 会写成 CRLF，
                # 每次 --apply 都把整份 SKILL.md 改成 CRLF（仓内 .gitattributes 约定一律 LF）。
                with open(p, "w", encoding="utf-8", newline=LF) as fh:
                    fh.write(want)

    absent_note = f"（{len(absent)} 个投放面不在本 checkout，已跳过：{', '.join(absent)}）" if absent else ""
    if not drift:
        print(f"[sync_principles] ✅ {total} 个投放面全部与真相源一致（四条通则）{absent_note}")
        return 0

    if args.apply:
        print(f"[sync_principles] ✅ 已回填 {len(drift)} 个：")
        for d in drift:
            print(f"   {d}")
        return 0

    print("[sync_principles] FAIL: 这些文件的托管块（四条通则）缺失或已漂移：", file=sys.stderr)
    for d in drift:
        print(f"   {d}", file=sys.stderr)
    print("   修：python3 hack/sync_principles.py --apply", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
