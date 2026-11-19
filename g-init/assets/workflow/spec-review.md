# Spec 评审规则（内联版）

本文件管评审方法，流程与报告契约以 g-review/SKILL.md 为准。生成、实现、评审均由主 session 串行完成，无子代理、跨模型通道或档位调度。

## 一、检查范围

设计审读取 proposal/design/specs、tasks（需求 ↔ 任务双向追溯）、decision-memo 和引用的实际代码，核对需求、承重约束、方案可行性与跨文档一致性；缺定稿纪要的 change 不做设计审（gate 判 REFUSE_START next=g-spec）。代码审按需求与票验收核对 diff，并读取被修改代码的调用方和边界。

config 的 context/rules 是生成软约束，不是已经完成的机械验证。CLI validate 未覆盖的结构、完整性与一致性，仍需读回核验，不能凭文件存在或配置声明跳过。

## 二、逐视角内联检查

1. 广审：分别核对目标、范围、假设、可行性与工程约束。
2. 领域：按 trigger-catalog 命中的 TG 选 base 与领域清单，不机械遍历不相关领域。
3. 对抗：给出具体输入、触发条件或失败路径，尝试证伪设计或实现。
4. 接地：打开真实代码，核验函数、字段、API 与依赖断言；引用需可定位。

每个视角开始前重读清单与材料，分别记录结果。分开检查只能降低遗漏，不能提供独立上下文。报告必须标注「内联评审——单一主 session，无 fresh-context 独立镜，无跨模型第二意见」。不得声称自审消除了作者偏置。

## 三、发现与处置

每条发现记录严重度、位置、触发条件和建议。拿不准的设计判断写入决策登记区，带推荐、依据、代价和备选，交设计人门拍板；不得无声丢弃。代码审共用 code-checklists/code-review-base.md「放行口径」：P0/P1 未解决阻塞，只有 P2 可自动延期；defer 记录 new/reuse 来源并由 gate 对账。引用先读实物核验，不依赖已退役的度量锚证明执行。

## 四、可验证的边界

- 设计批准后由 anchor_writeback.py 写 ship-gate frontmatter，禁止手写指纹；批准锚 MUST 带 `--expected-ref <送审提交>`，送审后设计又改则脚本拒写、须重新送审。
- 设计门批准后再改 design/specs：实现前 gate 判失鲜拒绝，实现后 gate JSON 带非阻塞 `design_drift`，均须交人重审或明确确认。
- 代码审与 verify 在检查前捕获完整提交 SHA，写代码 PASS 必传 --expected-ref，且代码仍与该版本一致；改代码后必须重审或重验。
- gate 验报告格式、内容新鲜度、票完成标签和 defer 对账；不能证明评审确实发生、测试输出真实或需求语义正确。
- 设计 HARD-GATE 保留；不能用内联自审代替人的明确批准。

执行时同时读取 trigger-catalog.md、spec-checklists/ 或 code-checklists/。旧多代理方法见 git 历史，不属于当前执行规则。
