# 降级阶梯 · 诊断契约 · 失败模式表

> 被 `g-spec/SKILL.md` 引用。**撞到任何失败先查本表，别现场发明处置。**

## 1. 诊断契约（三要素，每一条降级/失败报告都要写满）

**problem + cause + fix**，缺一即不合格。

| 要素 | 内容 | 反例（MUST NOT） |
|---|---|---|
| **problem** | 发生了什么、哪一步 | 「出了点问题」 |
| **cause** | 判定依据：exit code / 缺失文件绝对路径 / **实际版本号** / stderr 原文 | 「可能是环境问题」 |
| **fix** | 可直接照做的下一步命令 | 「建议检查一下安装」 |

> 示例：相位 C 获取 design 指令失败（problem）；openspec instructions 非零退出，附实际版本与 stderr（cause）；先修复 CLI 或 schema 后重试（fix）。

## 2. 降级阶梯

| 层 | 触发 | 降级到 | 允许静默？ |
|---|---|---|---|
| 检索 | 本地或联网检索失败 | 主 session 报告缺口；瞬时错误有界重试，仍失败不猜测事实 | ❌ 报告必写 |
| 生成 | 主 session 写入失败 | 按错误类别修复；瞬时错误重试一次，契约错误立即停止 | ❌ 报告必写 |
| openspec CLI | 不存在 / 非零退出 / instructions schema 不兼容 | fail-closed 中止并给修复方法 | ❌ 必须中止并报 |

当前管线不派发子代理，无 agent 定义或跨模型 fallback 检查。

🔴 **降级前 MUST 确认替代路径不复用同一故障依赖。** 「联网检索超时 → 主 session 亲查」若亲查
同样要联网，那不是降级，是同一个故障再撞一次 —— 此时 SHALL 如实说明该限制，而非宣告已降级成功。

## 3. 外部检索的退避与错误分类

- **总时间预算**：单次外部检索 ≤ 3 分钟；相位内累计 ≤ 10 分钟，超出即停并如实报。
- **429 / 5xx**（瞬时）：**一次**带 jitter 的有界重试（退避 2–5s 随机）。
- **401/403 认证错误、schema 不兼容**：**立即 fail-closed**，MUST NOT 重试（重试只会再失败一次，且掩盖真因）。
- **判据是「错误类别」，不是「次数」**：瞬时错误重试一次；契约错误不重试〔A-1〕。

## 4. 失败模式表

| 失败模式 | 检测 | 处置 | 回滚 |
|---|---|---|---|
| **工作树不洁进入相位 B** | B 起手 `git status --porcelain` | **halt 报告给人**（stash / 先提交 / 确认带过来三选一）；MUST NOT 静默 `add -A` | 未提交，无需回滚 |
| **人在相位 B 中途放弃** | 无（人主动） | memo 草稿留在 feature 分支内；**删分支即净**——⚠️ 仅当 B 起手时工作树曾干净，否则用户的无关改动已被 `checkout -b` + `add -A` 裹挟进来 | 删分支 |
| **在其它 feature 分支上开新 change** | FF-0 三分支判定 | 「其它」→ **halt 问人**（从当前切出 / 回 base 切出 / 就地继续） | 未建目录 |
| **`git checkout -b` 失败（分支已存在）** | 命令 exit code | fallback `git checkout feat/{change}`（存在则复用）；再失败即如实报告让人决定 | — |
| **陈旧 `decision-memo.md`** | 相位 C 起手核身份字段（change/branch）对不上当前盘面 | **拒绝进 C**，呈现旧 memo 摘要给人确认；MUST NOT 静默复用 | — |
| **生成产物半截/无效** | `status --json`（存在态）+ `validate --strict`（合格态）**分开判** | validate 不过即判该产物**未完成**，按错误类别修复或重试（**非**「文件存在即跳过」）；写入用临时文件 + 原子替换 | 按 preimage 精确回滚该文件 |
| **CLI schema 漂移（版本对、行为变）** | `instructions --json` 后做最小 schema 断言 | **fail-closed 中止**，报实际版本 + 修复命令 | 未写产物 |
| **openspec CLI 不可用/报错** | 命令 exit code | **fail-closed 中止**（含版本与修复命令） | `new change` 前后各记一次 change 目录快照；非零退出后核 `.openspec.yaml`/`status`，**精确报告 partial state，MUST NOT 假定其原子性** |
| **生成中断（部分产物完成）** | `status` + `validate` 对账 | 如实报告完成/未完成清单；按相位状态机重入 | 分支内 git 状态即真相 |
| **纪要缺失/必填为空进入相位 C** | C 起手核验 | 拒绝生成，退回相位 B | — |

## 5. `validate --strict` 的真实覆盖面（诚实边界，实测锚定）

`openspec validate <change> --strict`（CLI 1.5.0）**只校验 `specs/*/spec.md` 的 delta 结构**
——至少一条 delta、`## ADDED/MODIFIED/REMOVED/RENAMED Requirements` 头、每条 Requirement
含 SHALL/MUST 与 ≥1 个 `#### Scenario:`。

实证：`dist/core/validation/validator.js` 全文无 `design` 字样；change 路径实际只跑
`validateChangeDeltaSpecs`——**把 `proposal.md` 整份删掉，它照样报 `Change 'demo' is valid`**。
`hack/tests/test_decision_memo_gate.py::test_validate_strict_only_covers_delta_specs` 机械钉住此事实。

⇒ **`design.md` / `proposal.md` / `tasks.md` 被截断时，`status` 报 done、`validate --strict` 也报绿。**
四件套里只有 `specs/` 有机械合格门。另外三份的「未截断」**没有机械门**，只能由主 session 在
**终审**读回时人判：文末是否收束（最后一节写完、无半句话）、`## ` 小节是否齐全、有无「TODO/待补」残留。

MUST NOT 在任何文档中声称「`validate --strict` 挡得住半截 design.md」。

---

## 附录 A · 依据与演进史

> 正文只放最终态；本附录承载「为什么是这样」（`openspec/rules/doc-authoring.md` DOC-1）。

**〔A-1〕重试次数为什么恰好是 1** —— 无强依据。按通则④判为可接受边角：
换成 2 次或 3 次都不改变失败面的形状，而**错误类别的二分**（瞬时 / 契约）才是承重的那条。
**MUST NOT 为「到底几次」单独返工。**
