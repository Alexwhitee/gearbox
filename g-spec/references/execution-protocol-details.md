# 执行协议细节

按需路由自 `SKILL.md` 对应步骤；仅在实际执行到该步骤、需要展开判据表或背景细节时读取本文件。

## 0.2 宿主标注

resolve-models.sh 只提供宿主标注；不返回模型档位，不需要 eval。缺失时标 unknown，不阻塞。

## 分支约定与恢复

分支选择和后续交付必须一致：从 a 新建工作分支默认留在该工作分支且不合并；在 a 原地做默认提交归档并留在 a；只有人明确指定合并目标才执行合并。切换前捕获 a 与完整起始 SHA，CLI 创建 change 后由 branch_context.py init 保存四字段 JSON。旧变更缺文件时核对历史并由人明确起点/目标，不能拿当前 HEAD 或默认分支代填；恢复已有文件不重新初始化。hook 只保护创建入口，不负责推断合并目标。

## FF-0 三分支判定：全局 hook 的匹配 grammar

全局 FF-0 hook 只在整条 Bash 命令完整匹配**单条直接 literal**创建调用时，才用 payload
`cwd` 执行三分支判定。正向有限 grammar 只包含 `openspec new change <合法字面量>` 与
`openspec change new <合法字面量>`，容忍水平空白、单/双引号与单个 `--json` 变体。未命中该
grammar 的 wrapper、目录切换、compound、换行、前后散文、无效 literal/option 或动态名
一律记录 `command-unverifiable`，不尝试细分原因或解释 shell。此未判定路径只输出
`additionalContext`，**MUST NOT 解析 shell**，也不设置 `permissionDecision`；多处创建调用的
stacking deny 先于 cwd 未判定。

## C.2 生成阶段强制阅读清单（schema 依赖图优先，缺口回退超集）

| 生成 | MUST 先全文读 |
|---|---|
| `proposal.md` | `decision-memo.md` |
| `design.md` | `decision-memo.md` + `proposal.md` |
| `specs/**` | `decision-memo.md` + `proposal.md` + **`design.md`** |
| `tasks.md` | `decision-memo.md` + `proposal.md` + `design.md` + `specs/**` |

每步读 `dependencies` 对象列表（含 `id`/`done`/`path`/`description`）并比较上表。
图已覆盖按图读；图不足则回退**写死超集**：`specs` 读 `proposal.md`+`design.md`，`tasks` 读
`proposal.md`+`design.md`+`specs/**`，不得跳过；纪要输入。

## 0.3 重入探测：isComplete 三态判定表

| `isComplete` | 纪要 | 态 | 动作 |
|---|---|---|---|
| `false` | **无** | `B-draft`（草稿都没落成） | 继续 ⇒ **回相位 B**：A 的共识随上下文丢了，先重述锚点纪要再拷问 |
| `false` | **有** | `B-draft`/`B-finalized`/`C-partial` | 问话附分支名 + 纪要已有 N 条承重约束；继续 ⇒ 跳过 A，核验纪要（C.1）后进入 C |
| `true` | 任意 | `complete` | **拒绝重生成**，呈现该 change 与出口序列；要改走评审或新 change |

🔴 **MUST NOT 拿「有没有 `decision-memo.md`」当探测前提**——B 起手建完目录到第一次落盘之间崩溃，
留下的正是第一行那种**没有纪要**的在途 change；**MUST NOT 只探 `isComplete=false`**，那让
`complete` 只剩一句声明、没有对应的操作判定。

## C.4 已知限制：CLI 1.5.0 `validate --strict` 覆盖边界

CLI 1.5.0 的 `validate --strict` 只校验 `specs/*/spec.md` delta；其余三份（proposal / design /
tasks）截断仍可能双绿，只能靠终审读回判定，MUST NOT 声称它能挡住半截 design.md。
