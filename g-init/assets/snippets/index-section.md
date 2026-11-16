## OpenSpec 工作流规则（g-init 维护）

> 本区块由 `g-init` 维护——`openspec/workflow/` bundle 的规则索引。
> 新增/删 workflow 规则后重跑 `g-init update`，或手动同步本表。

> 无本地规则副本的仓：下表文件位于全局 canonical `~/.g/workflow/`，相对链接不可点，以文件名为准。

| 名称 | 文件 | 作用 |
|---|---|---|
| `workflow` | [workflow/workflow.md](./workflow/workflow.md) | 端到端流程总览（内联精简版）：/g-spec 生成 → /g-review spec 设计审 → 设计 GATE → /g-done（gate 驱动：实现+代码审+verify+归档+merge）；阶段内部不用 /clear，仅两处阶段交界用，连续跑到 merge |
| `trigger-catalog` | [workflow/trigger-catalog.md](./workflow/trigger-catalog.md) | 「按内容条件触发」单一权威源 TG-NN，驱动 约束/领域清单/画图/必填槽 四层 |
| `ff-generation-constraints` | [workflow/ff-generation-constraints.md](./workflow/ff-generation-constraints.md) | 生成起手强制：FF-0 开分支 + 生成硬约束 D-1~D-6 + 切片建议 |
| `generation-process` | [workflow/generation-process.md](./workflow/generation-process.md) | 生成过程：发散(explore) + `/g-spec`（澄清→拷问→生成三相位） |
| `design-diagrams` | [workflow/design-diagrams.md](./workflow/design-diagrams.md) | 设计/spec 阶段画哪些图、何时画、什么形态（C4 + 行为图，触发条件化） |
| `spec-review` | [workflow/spec-review.md](./workflow/spec-review.md) | 评审方法论（Detection 层）：只做 prevention 残差，trigger 驱动 + 独立 pass + 读码核验 |

评审清单（`/g-review` 用）：[workflow/spec-checklists/](./workflow/spec-checklists/)（设计审，base + domains）、
[workflow/code-checklists/](./workflow/code-checklists/)（代码审，base + domains）。
说明类参考（可删不影响执行）：[workflow/reference/](./workflow/reference/)（含 change 拆分标准单一源 `change-decomposition-standard.md`）。
