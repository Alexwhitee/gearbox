# gear 当前工作流

单人、单会话、串行执行。没有多代理、跨模型调度或模型档位解析。

## 从需求到完成

```text
g-init（一次铺设）
    ↓
g-spec：澄清 → 拷问 → proposal/design/specs/tasks + decision-memo
    ↓ 阶段交界读盘面材料
g-review spec：广审、领域、对抗、接地 → spec-review-report
    ↓ 人明确批准；anchor_writeback 写设计门内容指纹
g-done：每步前后调用 ship_gate
    ├─ g-implement mode=plan → tickets.md → 提交
    ├─ g-implement mode=exec → 逐票实现、自审、验收 → checkpoint
    ├─ g-review code → code-review-report + 内容指纹
    ├─ verify → verify-report + 内容指纹
    └─ hand-off → archive → delta 核验 → commit → ff-only merge
         明确 skip merge 时：已提交 .skip-merge + 归档 verify=PASS → 完成
```

## gate 与产物

| 状态 | 动作 | 判据 |
|---|---|---|
| REFUSE_START | 返回设计门 | 缺 change 或设计批准 |
| RUN_PLAN | 出票 | tickets.md 缺失 |
| CONTINUE_IMPL | 逐票执行 | 仍有票缺已提交的完成标签 |
| RUN_CODE_REVIEW | 代码审 | 实现完成，无评审报告 |
| BLOCKED_UPSTREAM | 停止 | 代码审 blocked |
| RUN_VERIFY | 验证或继续收尾 | 缺 verify，或归档/merge 尚未完成 |
| VERIFY_FAIL | 停止并展示缺口 | 新鲜 verify=FAIL |
| RERUN_STALE | 重跑对应步骤 | 被审查内容已变化 |
| STEP_IN_PROGRESS | 继续对应步骤 | 报告缺结论或 defer 未对账 |
| SHIPPED | 结束 | 归档已并指定目标，或不合并并留在工作分支完成，或明确跳过合并 |
| UNKNOWN | 报告原因 | 坏计划、坏锚或判定不能 |

JSON 中旧 next 名只为兼容：g-spec-review → g-review spec；g-code-review → g-review code。

## 核心契约

- tickets 标题与依赖有界解析；唯一 R-ID: all 收尾票覆盖全部功能票，并验收聚合测试套件。
- 进度只认计划首次提交起的 checkpoint(change:taskN-slug) 标签；勾框不能独立放行。
- suite-scope 返回配置中的测试层；unconfigured_layers 是待发现命令的层，必须查 CI/README/既有约定，实际执行或附查证依据记未覆盖。显式 domains 的空层集合才是配置确定的无测试域。
- 收尾票保留原始 suite-scope JSON 的完整 head，verify 以它为差异基准；无测试层也有该基准，不能从通过行反推或猜 HEAD。
- 三份报告头部 ship-gate 保存批准或结论，reviewed_sha 为 manifest 的 SHA-256，reviewed_manifest 为清单编码。统一由 anchor_writeback.py 计算，不手写。
- 代码 PASS 写锚必传检查前捕获的完整 --expected-ref，写入时核对代码指纹一致且源码干净；报告 checkpoint 只提交指定路径，拒绝夹带未验证代码。
- 实现与最终代码审共用 code-review-base.md 放行口径：P0/P1 未解决阻塞，只有 P2 可自动延期。defer 台账标 new/reuse：new 需当前 change 的 open 票，reuse 核验历史 open/closed 中唯一票的 id/pool，不改写来源。
- `.g-branch.json` 保存 source_branch/work_branch/base_sha/merge_target：从 a 新建默认留在功能分支且不合并，原地开发默认提交归档留在 a；只有明确指定才改目标。评审、suite-scope（传 --change）与 ADR 用固定 base_sha，合并用 merge_target；缺约定先核对补录，不猜默认分支。skip merge 后再次明确请求合并，先明确/沿用目标，再删除并单独提交归档标记，由 gate 续跑。
- gate 校验格式、完成标签、内容新鲜度与 defer ID 对账；不证明语义审查或测试确实发生。
- 单会话内联检查不具备独立上下文。设计批准仍须由真人明确给出。
- 历史 metrics/token 数据只供 g-retro 兼容读取；当前不生成、不强制要求度量锚。

## 工具与维护

规则根由 resolve-workflow.sh 解析到全局 canonical。ship_gate.py、anchor_writeback.py 和 delta_sync_check.py 随 g-done 分发；impl_route.py 随 g-implement 分发。安装由 setup.sh 完成，安装测试使用临时 HOME。

完整流程见 [WORKFLOW-GUIDE.md](../g-init/assets/workflow/WORKFLOW-GUIDE.md)，执行细节以各 SKILL.md 和对应脚本为准。辅助入口 architecture、roadmap、devenv、adr、issues、retro 各自保留其产物与职责。
