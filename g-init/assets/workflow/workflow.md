# Spec 工作流（端到端总览 · 内联精简版）

> **定位**：从需求到 merge 的端到端流程骨架。2026-11 简化：**单人单 session 内联执行**——
> 子代理 fan-out、跨模型 voice、模型档位/effort 调度、评审度量锚已移除；ship-gate 内容指纹与批准锚保留（恢复看 g-skills git 历史）。
> 遗漏由「逐视角内联检查 + 真实证据 + 设计门人工拍板」降低，不宣称具有独立上下文，报告如实标注内联模式。
> 🔴 产物文件名（`tickets.md`、`impl-reports/`、`spec-review-report.md`、`code-review-report.md`、`verify-report.md`）
> 是 `ship_gate.py` 的判定依据，MUST NOT 改名。

## 一、完整流程（唯一线性路径）

```
 阶段一·生成 ── 人类对话岛：拷问 ──────────────────────────────
   opsx:explore〔条件：问题模糊 / 方向未定〕；问题清晰直接进 /g-spec
   人示意收敛（"开搞"/"做吧"/"开 change"）→ 模型自动 invoke /g-spec
   /g-spec            澄清(A) → 拷问(B) → 生成(C)；起手 FF-0 开分支；产四件套 + decision-memo.md
     └─ 出口：/clear → /g-review spec
        │
 阶段二·设计审 ─────────────────────────────────────────────
   /g-review spec     内联多镜（广审双镜 + 领域 + 对抗 + 接地）→ spec-review-report.md
     │                     中途不打断，决策进报告「决策登记区」
   〔HARD-GATE：用户过报告拍板〕  ★全流程唯一人类门
        │
 阶段三·收尾 ── 过设计门后连续跑到 merge，无人类门 ────────────
   /g-done {change}   ship_gate 状态机驱动（盘面即状态）：
     ├─ RUN_PLAN / CONTINUE_IMPL → g-implement（出票 / 逐票实现+双轴自审+checkpoint）
     ├─ RUN_CODE_REVIEW          → 默认停：/clear 后 /g-done（代码审在不带实现上下文的会话里做）→ /g-review code → code-review-report.md
     ├─ RUN_VERIFY               → verify（Do Not Trust + 证据锚 + frontmatter 写锚）
     ├─ ADR 同步（非阻塞）→ hand-off → archive → commit → 按约定合并或不合并并留在工作分支完成（.skip-merge 三态）
     └─ SHIPPED → 摘要；VERIFY_FAIL / BLOCKED_UPSTREAM / IMPL_BLOCKED / 带 design_drift → 停并上抛
```

## 二、逐步 prompt

| 阶段 | 步 | command/skill | 产出物 | 规则·条件 |
|---|---|---|---|---|
| 一 | 1 | /opsx:explore | — | 问题/方向模糊才跑；人示意收敛 → 自动接 /g-spec |
| 一 | 2 | /g-spec | proposal/design/specs/tasks + decision-memo.md | generation-process §四；出口 = `/clear` → `/g-review spec` |
| 二 | 3 | /g-review spec | spec-review-report.md | 按 trigger-catalog 判 TG 深度；spec-checklists 选域；**非平凡必跑** |
| 二 | 4 | HARD-GATE | （人工批准） | ★全流程唯一人类门 |
| 三 | 5 | /g-done | tickets + 代码 + code-review-report.md + verify-report + 归档 + 提交 + merge | ship_gate 驱动到底；无人类门 |

`[checkpoint]` = 步末调 `~/.g/hack/checkpoint-commit.sh <step> "<描述>"`（用法见脚本头注释；缺失先在运行 checkout 跑 setup.sh）。

## 三、关键设计决策（内联版保留项）

1. **FF-0 三分支判定**（生成起手开分支，带守卫）：保护分支 → `git checkout -b feat/{change}`；已在 `feat/{本 change}` → 跳过；其它 feature 分支 → halt 问人。见 ff-generation-constraints.md §FF-0。
2. **`/clear` 只在两处阶段交界用**（一→二、二→三）：盘面纪律 + 产物自足性检验 + 去作者偏置；不要求切换模型；阶段内部要控上下文用 `/compact`。**唯一例外**：阶段三的 `RUN_CODE_REVIEW` 断点——实现与代码审同会话等于作者自审，本会话做过该 change 的实现时，g-done 在此默认停下请人 `/clear` 后重调 `/g-done {change}`，代码审在 fresh 会话里做（gate 从盘面续跑，零跨步记忆，不丢状态）；人明确要求本会话继续才不断。其余阶段内部仍禁 `/clear`。
3. **中途不 AskUserQuestion（G2）**：决策进报告「决策登记区」（≥2 方案：选项+推荐+三面后果(系统/用户/开发循环)+主次判定），攒到门一次拍。
4. **只停一次人类**：设计 HARD-GATE。阶段三内 ≥2 方案：有客观判据（测试/断言/基准）→ 自动选并记三镜+主次理由；无判据且影响大 → 登记区/hand-off 上抛；**MUST NOT 以自评置信硬选**。
5. **每步 checkpoint**：`checkpoint-commit.sh` 固定 message，不 squash。普通模式 git add -A；代码审与 verify 报告必须用 `-- openspec/<文件>...` 限定路径，拒绝源码脏改动并保留无关暂存文件。
6. **评审两层不重复**：实现期每票双轴自审（即时闭环）+ 事后 `/g-review code`（全 change 再检查）——职责不同，别优化掉任何一个。
7. **verify 防假✅**：唯一终门。每条 ✅ 附机验锚（测试名/commit/文件:行），无锚降级 gap；零用例的通过判核心缺口。代码审与 verify 在检查前捕获完整提交 SHA，写代码 PASS 必传 --expected-ref 并核对代码未变化。收尾票保留原始 suite-scope JSON.head 供 verify 比较，无测试层仍有此基准。
8. **测试配置缺席不免测**：suite-scope 的 unconfigured_layers 必须查 CI/README/既有测试约定，找到命令后执行；确无该层才附依据记未覆盖。已提交的 .skip-merge + 归档 verify=PASS 可正常结束。
9. **深度按 TG**：explore 模糊才跑；不分 S/M/L。
10. **放行口径单一源**：实现与最终代码审共用 code-review-base.md，P0/P1 未解决阻塞，只有 P2 可自动延期；defer 台账标 new/reuse，保留历史 issue 来源并对账。
11. **分支约定与续跑**：切分支前捕获起点，创建 change 后用 branch_context.py 保存四字段 JSON。从 a 新建默认留在功能分支且不合并，原地做则提交归档留在 a，只有明确指定才改目标。代码审/测试（--change）/ADR 用固定 base_sha，最终合并用 merge_target；缺约定须核对补录，不猜默认分支。skip merge 后明确目标再提交撤销标记，由 gate 续跑。

## 四、与规则集的关系

- 本文管编排；细则在各规则文件：`trigger-catalog.md`（TG 单一源）· `ff-generation-constraints.md`（FF-0 + 生成硬约束）· `generation-process.md`（生成三相位）· `design-diagrams.md`（画图）· `spec-review.md`（Detection 方法论）。
- 清单：`spec-checklists/`（设计审，base + domains）、`code-checklists/`（代码审，base + domains），按 TG 选域。
- 演进史 → workflow-history.md（不是当前约束，跑流程不用读）。

## 五、检查清单（跑一个变更时）

- [ ] 问题清晰否？不清晰先 explore；人示意收敛才自动接 /g-spec
- [ ] 生成起手过 FF-0？每步 checkpoint？
- [ ] `/clear` 只在两处交界 + RUN_CODE_REVIEW 断点？其余内部用 `/compact`？
- [ ] 设计审一份报告 + 决策登记区？读了真实代码、过了命中领域清单、对抗裁决？
- [ ] 过了 HARD-GATE（用户批准）才进阶段三？
- [ ] 实现逐票闭环（实现 → 双轴自审 → 验收命令 → checkpoint）？BLOCKED 如实标？
- [ ] 代码审每次全跑？P0/P1 修复或阻塞（自动修复上限 2 轮），P2 延期有真实 issue 并标 new/reuse？
- [ ] verify 每条 ✅ 附锚？FAIL 停并展示缺口？
