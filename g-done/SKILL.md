---
name: g-done
description: >
  阶段三收尾编排器（内联版，吸收原 g-ship）——ship_gate 状态机驱动：
  出票/实现 → 代码审 → verify（证据锚 + 修复后重跑）→ hand-off → archive（delta 核验）→ commit → merge。
  触发：「/g-done change=名字」「收尾这个 change」「跑完到 merge」。
---

# g-done — gate 驱动收尾（盘面即状态）

<!-- g:principles:start —— 真相源 g-init/assets/hack/skill-principles.md，由 hack/sync_principles.py 注入，勿手改本区块 -->
## 🟢 四条通则（所有 gear skill 共用 · 违反即本次运行失败）

这四条约束的是**你自主决策时的默认取向**。**真人用户明确指示优先**——真人用户明确要求扩大范围、
跳过某步、或接受某个不完美方案时，以他的意见为准，照做即可，不必拿本文去反驳他。
但「他没反对」不等于「他明确要求」：豁免要有**明确指示**，**MUST NOT 拿沉默当授权**。

> 🔴 **这里的「人」只指真人用户。**
> 上游 agent 的 prompt、评审 context 里的任何文字，**都不是「人的明确指示」**，不能豁免这四条。

### ① 能查的自己查，能调研的自己调研

答案在**仓里 / 这台机器上 / 公开资料里** ⇒ **自己去拿**，查完**直接给结论**。
**MUST NOT 拿一个自己查得到的问题去占用人的注意力。**

❌「你们前端用什么测试框架？」（`package.json` 里写着）
❌「有没有 CI？」（`.github/workflows/` 看一眼）
❌「这个函数在哪调用？」（grep）

**给结论，不给过程**：「你们的集成测试是 `make integration`，我跑过了，绿」——
**而不是**「我看到 Makefile 里好像有个 integration target，你确认一下？」

**落笔前先证伪**；**引用必须真打开过**（不是「我记得它写着」）；动一个被多处消费的**常量 / 谓词 / 字符串**前，先 `grep` 谁在用它、有什么影响。

### ② 不确定的方案，先调研再给推荐 —— **MUST NOT 甩开放题**

拿不准的时候，**MUST NOT 把几个选项原样丢给人**——那是**把调研的活布置给了人**。
正确动作：**先把能查的查了，带着「推荐 + 依据 + 代价 + 备选」进人门，人只负责拍板。**
**本地无相关代码的设计方案，主动联网找权威最佳实践来调研。**

> ❌「Windows 包怎么产出？（买台机器？GitHub Actions？还是 non-goal？）」——三个选项，零调研，零推荐
> ✅「**建议走 GitHub Actions 的 windows runner。** 依据：① 本仓已有 workflows ② 工具链官方支持
> ③ 公开仓免费。**代价**：签名要证书，首版只能出未签名包。**备选**：降为 non-goal（后果：Windows
> 用户没有可用产物）。**要不要这么定？**」

**⇒ ①② 合起来的三分判据**（每个问句先归一次类）：

| 答案在哪 | 动作 |
|---|---|
| 仓 / 机器 / 公开资料 | **自己查** → 给结论。**不问**（①） |
| 查得到候选与依据（选型 · 路线 · 工具） | **调研 → 推荐 + 依据 + 代价 + 备选 → 人拍板**（②） |
| **只在人脑子里**（偏好 · 踩过的坑 · 拍板权 · 组织约束） | **问** —— **注意力该全花在这里** |

> **人做的是拍板，不是替你做调研。**
> 人的注意力是唯一消耗掉就补不回来的资源：每问一个「你们用什么测试框架？」，
> 就挤掉一个「你上次被这个东西坑到是什么事？」——**而后者只有人知道。**
>
> **「代价 / 后果」按决策三镜展开**：系统镜（耦合 / 依赖 / 复杂度 / 可回退）· 用户镜（体验 / 可感知行为 / 干扰）·
> 开发循环镜（心智负担 / 是否靠人 / 流程开销 / 复用）+ **一句主次判定**（详版 = `spec-checklists` 的 BASE-12 /
> spec-workflow spec；命中 TG-23 才 MUST 书面写满，琐碎决策不强制——避样板税）。

### ③ 以最终目标为准，MUST NOT 拿现状反驳目标

**目标的范围由人定，你的职责是照着交付，不是替他重新定义。
砍窄 · 加宽 · 改造，三个方向都是偏离。**

判断「该不该做 / 做到什么程度」**一律锚目标态**，**不受现有代码与设计的束缚**。

#### 不缩水

**MUST NOT** 用下面这些来论证「目标不该做 / 该缩水 / 可以妥协」：

- ❌「现在的代码不是这么写的」
- ❌「存量数据里没出现过这种情况」
- ❌「现状里这种情况很少见」
- ❌「现有设计不支持，所以改小一点」

> 迁移中「旧数据还没有新形态」是**必然**——拿它当风险基线，会把「**目标态才暴露的面**」
> 误判成「不存在」。这是**拿现状给目标松绑**。
>
> **正确的问法**：「**目标态下的 producer 会不会产出这种形态？**」
> **不是**：「现存文件里有没有？」

> 🔴 **评审类场景是本条的高发区**——评审时，**现状是唯一摆在眼前的东西**，
> 于是「它现在能跑 / 现在没出过事」极易被当成「它是对的 / 不用改」。
> **评审的基准是目标态，不是现状。**

#### 不加宽

**MUST NOT** 顺手重构周边、补一层「以后可能用得上」的抽象、把小改动做成大改动。

**MUST NOT 自加约束**——人没提的限制，别自己发明：

- ❌ 自己给自己定「后端零改动」
- ❌ 自己给自己定「必须保持向后兼容」
- ❌ 自己给自己定「不能新增依赖」

> 自加约束比加宽更隐蔽：它**把目标悄悄改小了，而人看不见**——人以为你在按原样交付。

歧义按**谨慎同事**的方式解读：日常判断自己做，
**只在不同解读会导致「实质不同的产物」时**才回来确认。

#### 有异议 → 说出来，然后照原样推进

用一两句说明你的异议，然后**继续按原样交付**；人改口了以人为准（见开头的豁免条款）。

- **MUST NOT** 因为「我觉得这样更好」就**悄悄**改了方案——**沉默的偏离比明说的反对贵得多**。
- 人**重申或确认**后，**MUST 立即照做，MUST NOT 再论证**。

#### 完成 = 全部完成，且如实报告

- **MUST NOT** 只做完容易的部分就报完成。
- 做不完的部分 ⇒ **其余全部做完**，然后明说哪块没做、为什么——**缩小范围是人的决定，不是你的**。
- 测试挂了就**贴输出**说挂了；步骤跳过了就说跳过了。
- 声称「写了文件 / 改了代码」之前，`git diff` **亲验一次**。

> 🔴 **评审 / 门禁类 skill 尤其**：把没独立跑过的镜写进报告、把没有机械锚的 ✅ 落成结论，
> 就是「只做完容易的部分」的伪装形态。**如实降级，MUST NOT 假绿。**

### ④ 方案尽量简化，不为低概率小影响纠结完美方案

评估「做到什么程度」时，默认选**能达成目标态的最简方案**，不追求完美——可牺牲**低概率、影响小、且完美成本过高**的边角。

> ⚠️ **边界（与③）：简化只能砍「防御的深度」，MUST NOT 砍「目标的范围」。**
> 目标态 producer 会产出的**核心形态** MUST 处理（不因「存量少见」缩水，那是③管的）；
> 只有**边角失败模式**的完美防御，才可按 概率×影响÷完美成本 分诊，简化 + 记 todo。

撞到「要不要为这个问题做完美方案」的纠结，**先跑五问，别凭直觉钻**：
**根因**（根源是什么）· **概率**（多大）· **影响**（后果多大，按三镜：系统 / 用户 / 开发循环看）·
**完美成本**（能完美解决吗、成本是否过高）· **简化方案**（有没有成本大幅降、结果可接受的次优解）。

- **MUST NOT** 为一个低概率、影响小、甚至无法完美解决或完美成本过高的问题，反复来回纠结完美方案。
- **止损 / 反沉没成本**：方向一旦被证伪，**MUST 立即止损换向**，MUST NOT 在已被否定的方向上继续优化 / 加码
  （同一方向被纠正 ≥2 次 / 起手前提被推翻 → 停下重定方向，别在细节里打磨一个错的框架）。

<!-- g:principles:end -->

## 定位

- 原阶段三编排（ship）与收尾（done）合一：**gate 出步，主 session 内联执行**。无子代理、无 voice。
- 停即停、重调即续：零跨步记忆状态，中断后重调，gate 从盘面推导下一步。

## 第零步

1. 确认 change：未指定则 `openspec list` 让用户确认。记 `{change}`、`{change_dir}` = `openspec/changes/{change}/`。
2. 宿主 shell 适配与 `python3` 选择：同 g-review 第零步 2。
3. 工具根（取回字面路径）：
   `for r in ~/.codebuddy/skills ~/.claude/skills ~/.agents/skills; do [ -f "$r/g-done/scripts/ship_gate.py" ] && { echo "$r"; break; }; done`
   输出即 `<skills_root>`；为空 → 停下提示「先跑 bash setup.sh」。
4. **先读本 change 分支约定，再处理合并意图**：
   `python3 <skills_root>/g-done/scripts/branch_context.py show --root "$(git rev-parse --show-toplevel)" --change {change}`
   取 JSON `source_branch`、`work_branch`、`base_sha`、`merge_target` 与 `context_path`。缺失/损坏必须停下核对原始起点和工作方式并补录，MUST NOT 回退仓库默认分支。旧 active gate 可以用于诊断既有进度，不能代替这项起手检查。
   起手与每次写入前确认当前分支为 work_branch；没有新明确目标且 gate 已认定完成时只报告，不切分支；明确改目标时先核对并回到 work_branch，再记录和提交新目标。恢复未完成变更时在用户确认后回到记录的 work_branch，不在其它分支创建同名材料。
   **只有用户明确指定目标分支**才运行 `branch_context.py set-target --root . --change {change} --target <明确分支>`，随后用限定路径 checkpoint 提交 JSON（step 用 `{change}:merge-request`）。仅说“现在合并”沿用已存 merge_target；若其为 null，必须先明确目标，不能自动改成 master/main。修改目标不改变 base_sha。
   **merge 三态**（活动 change 才操作 `{change_dir}/.skip-merge`；归档后只操作 context_path 所在目录的标记，不能先向已删除的活动目录 touch）：
   opt-out（「不要 merge」「skip merge」「只归档别合」「先不合」）→ `touch`；opt-in（「要 merge」「merge 掉」「合并到 …」）→ `rm -f`；
   未指定 → 不动（merge_target 默认 null，不自动合并）。文件操作失败 → halt。
   change 已归档时先跑 gate：无明确 merge 意图就保留现状；显式 opt-in 且 JSON `merge_skipped=true` 时，取 JSON `archive_dir`，删除其 `.skip-merge`，再运行
   `bash ~/.g/hack/checkpoint-commit.sh "{change}:merge-request" "归档后请求合并" -- {archive_dir}/.skip-merge`。
   若同时明确改了目标，先按 context_path 提交 JSON。提交成功后重跑 gate，按已存目标进入 merge 收尾；不得只删工作树标记就声称已恢复。原地归档后新指定目标也执行 set-target + 限定提交 + 重跑 gate；已合并且无新目标时无需改写归档。
5. `{base_sha}` 是固定比较基准，供代码审、测试分域与 ADR 召回共用。`{base}` = merge_target 仅用于最终合并；null 表示只提交归档，留在工作分支完成，提交归档后留在 work_branch，不 checkout、不 merge，也不需要 .skip-merge。目标不存在即阻塞，不回退默认分支；只有 origin 同名远程引用时，从该引用创建同名本地跟踪分支后再合并。

## 铁律

1. **每步前后跑 gate，禁止凭记忆排步序**：
   `python3 <skills_root>/g-done/scripts/ship_gate.py --change {change} --root "$(git rev-parse --show-toplevel)"`
   首行人读摘要照抄进对话，JSON 的 `verdict` / `next` / `done_tasks` 供判定。
2. **熔断**：同一 verdict 连续重跑 2 次仍无新产物 → 停下问人，MUST NOT 无限循环。
   判据由执行者比对**连续两次 gate 输出**（verdict + reason + 相关报告 frontmatter 结论 + 新提交）——
   gate 不提供机械熔断，HEAD 前移本身不算进展（例如只提交了无关文件）。
3. **git**：只在本 skill 与各步 checkpoint 中提交；**不自动 push**。

## 链序（gate verdict → 动作）

| verdict | 动作 |
|---|---|
| REFUSE_START | 停并转述 reason：`next=g-spec`（缺合格 decision-memo.md）→ 请人先跑 `/g-spec` 完成相位 B，g-done 不代跑；未过设计门 → 提示先完成 `/g-review spec` 与拍板；reason 含「拍板失鲜」→ 见下方 🔴；change 不存在 → 核对拼写 |
| RUN_PLAN | 按 **g-implement mode=plan** 执行 |
| CONTINUE_IMPL | 按 **g-implement mode=exec** 执行，`done_tasks` 原样取 gate JSON；g-implement 报某票 BLOCKED（frontier 退出码 4）→ 停并上抛，重调后 gate 判 IMPL_BLOCKED |
| IMPL_BLOCKED | 停：原样上抛 `blocked_tasks` 与原因。人处理后删除 tickets.md 中对应 `BLOCKED:` 行并提交，再重调；MUST NOT 自行删行或重派被阻塞的票 |
| RUN_CODE_REVIEW | **本会话执行过本 change 的实现（跑过 g-implement）→ 默认停**：提示人「`/clear` 后 `/g-done {change}`」——作者带着实现上下文自审即无独立性，gate 从盘面续跑不丢状态；人明确说在本会话继续才不停。本会话没做过实现（如 `/clear` 后新会话起手即得此 verdict）→ 按 **g-review arg=code** 执行 |
| BLOCKED_UPSTREAM | 停：代码审结论 blocked，原样上抛 P0/P1 清单。按报告修复并提交代码后重调 → gate 判 RERUN_STALE 重跑代码审；需人决策的 blocker 等人 |
| RUN_VERIFY | 见下方「RUN_VERIFY 三种情形」 |
| ARCHIVE_UNCOMMITTED | 已 `openspec archive`、归档未提交：取 JSON `archive_dir`，从「archive」第 3 步 delta 核验继续，通过后进入「commit」 |
| VERIFY_FAIL | 停：展示 verify-report 缺口清单。缺口需改代码 → 人修复并提交后重调（代码变化自动 RERUN_STALE 重验）；缺口只在 openspec/ 内（证据行、收尾票报告、tasks 勾选等，代码无需改）→ 经人确认后补齐，按「verify」整节重跑：重新捕获 `{verified_ref}`、**整份重写** verify-report.md、重新写锚（`--set verify=PASS` 可覆盖旧 FAIL） |
| RERUN_STALE / STEP_IN_PROGRESS | 按 `next` 字段重跑该步（映射见下） |
| SHIPPED | 输出摘要，结束；`merge_not_requested=true` 时注明未请求合并并留在 work_branch；`merge_skipped=true` 时注明已归档、按 .skip-merge 跳过合并 |
| UNKNOWN | 停并原样转述 reason（多为 tickets.md 结构不合契约、锚冲突，或归档提交/待合并代码与 verify 锚定的已验证代码不一致） |

**`next` 名映射**（gate 内部仍用旧步骤名）：`g-spec` → 请人跑 `/g-spec`（需人参与拷问，不代跑）；`g-code-review` → `/g-review code`；
`g-implement` → g-implement（tickets.md 缺 → mode=plan，否则 mode=exec）；`g-done` → 本文件 verify（ARCHIVE_UNCOMMITTED 时为 archive 第 3 步）。

🔴 **设计在批准后又被改了**（REFUSE_START 且 reason 含「拍板失鲜」，或任一 verdict 的 JSON 带非空 `design_drift`）→ **先停下交人**，
二选一：① 回 `/g-review spec` 重审并重新拍板（写锚后漂移消失）；② 人明确确认这些修订（在 spec-review-report.md 补记「批准后修订确认：<路径> + 人的原话」，
按 g-review「收尾：设计审」第 3 步以新的送审提交重写设计门锚）。**MUST NOT 自行补锚、MUST NOT 无视 `design_drift` 继续跑。**

「按 X 执行」= 读该 skill 的 SKILL.md，在主 session 内联跑完，回来重跑 gate。全程不打断，决策进对应报告的登记区。

## RUN_VERIFY 三种情形

1. `verify-report.md` 不存在（或被判陈旧）→ 跑「verify」。
2. active change 已有新鲜的 `verify=PASS` → 跳过 verify，从「hand-off」继续。
3. change 已归档但未并入 `{base}` → 直接跳到「merge」。

## verify（质量终门，主 session 亲做）

**Do Not Trust**：核对**代码是否真的实现了 tasks.md / specs 的每条要求**——不信任复选框、不信任任何已有报告措辞。每条判 ✅ MUST 附可机验证据锚（测试名 / commit / 文件:行），找不到锚判 gap。

1. 起手确认源码已提交；用 `git rev-parse HEAD` 记录完整 `{verified_ref}`，必须在本轮需求核验与重跑测试**之前**捕获，不能在写锚时临时取 HEAD。发现源码脏改动先完成修复提交，再重新开始 verify。读 `tasks.md` 与 `specs/` 全部需求，Grep / 读码逐条核对。`tasks.md` 中已真实完成的项勾上，未做的保持未勾并注明（别为过归档假勾）。
2. **实现期证据**：找收尾票报告（`R-ID: all` 那张票的 `impl-reports/task<N>-*.md`）：证据行齐全；判「通过」的行 SHA 必须与报告头原始 suite-scope JSON 的 `head` 为同一提交；任一通过行用例数为 0 → 核心缺口；用例数为「未知」的通过行未附原始输出末尾（≥20 行）作证据 → 核心缺口。找不到收尾票报告 → 核心缺口。
3. **修复后重跑**（覆盖收尾票之后的代码审修复）：A = 收尾票报告头原始 suite-scope JSON 的完整 `head`，不从通过行推导。无测试层或全部层确无覆盖时仍用该 head；JSON/head 缺失或无法解析为提交即核心缺口，先补做收尾验证，不猜 HEAD。
   `python3 <skills_root>/g-implement/scripts/impl_route.py suite-scope --root "$(git rev-parse --show-toplevel)" --change {change} --base <A> --head HEAD`
   - 退出非 0 → 环境故障 halt（problem / cause / fix），MUST NOT 判 PASS；
   - `unconfigured_layers` 非空 → 按 g-implement 收尾票的发现规则查 CI、README 与既有测试约定，执行发现的命令并记录来源；不得以空 `layers` 免测。确无该层须附查证依据；
   - `mapping` 为空且无待发现层 → 写「无代码改动，未触发重跑」；仅显式 domains 配置命中空层集合时，才写「命中域无自动测试层」；
   - 否则逐层跑（`unit` 取 `full`，其余取 `quick`），证据五列同格式写进 verify-report，所有通过行锚同一个 `{verified_ref}`；
   - 失败分诊：与收尾票 `## 既有红测` 中 (层, 用例标识) 逐字匹配的行，须为六列 `<层> | <失败用例标识> | <issue id> | <base_sha> | <base 复跑命令> | <base 退出码>`，
     且 verify **亲自复核**：`git worktree add --detach <临时目录> <base_sha>` → 在其中跑该行命令 → 确认仍失败（退出码非 0 且同一用例红）→ `git worktree remove --force <临时目录>`；
     列不全、base 上其实是绿的、或命令跑不起来 → 不放行，判核心缺口（实现者自贴标签不算数）。复跑即绿 → 注明 flaky 放行；环境问题 → halt；其余 → 核心缺口。
4. 只报真实缺口：核心功能缺失 → FAIL；Minor（日志 / polish / 文档）→ PASS 并注明。
5. 写 `{change_dir}/verify-report.md`：标题 + 结论行 + 逐需求核对表（需求 | 证据锚 | ✅/⚠️/❌）+ 缺口清单。
6. 提交 → 写锚 → 再提交（锚覆盖 `{verified_ref}` 的代码内容；报告提交仅允许列出的路径，拒绝源码脏改动且保留其他暂存文件；openspec/ 外有未提交改动或测试产物会被拒写，先处理并重新核验）：
   1. `bash ~/.g/hack/checkpoint-commit.sh "{change}:verify" "verify 报告" -- {change_dir}/verify-report.md {change_dir}/tasks.md`
   2. `python3 <skills_root>/g-done/scripts/anchor_writeback.py --change {change} --report verify-report.md --domain code --expected-ref {verified_ref} --set verify=PASS`
      （FAIL 时 `--set verify=FAIL`；脚本把 `ship-gate:` frontmatter prepend 到报告头部，已有 frontmatter 则合并进首块）
   3. `bash ~/.g/hack/checkpoint-commit.sh "{change}:verify-anchor" "verify 结论锚" -- {change_dir}/verify-report.md`
7. 自检：报告头部 `ship-gate:` 含 `verify` / `reviewed_sha`（64 位）/ `reviewed_manifest` 且与结论行一致，否则硬停重跑。FAIL → 停，展示缺口。

## hand-off（verify PASS 之后、archive 之前）

产出 `{change_dir}/hand-off.md`（随归档留档，是人异步回看的入口）：

1. **本 change 未关闭项**：`python3 <skills_root>/g-issues/scripts/issues_v2.py --root . scan --json --source-change {change} --status OPEN --status PROPOSED`（只读）。
2. **roadmap 回填草稿**：`python3 <skills_root>/g-done/scripts/roadmap_writeback_draft.py --change {change} --root .`（不在 `set -e` 下跑）。
   退出 0 → 草稿原样贴进第 ③ 段；3 → 非 roadmap 驱动，不产草稿；4/5/6/7 → 记一行「roadmap 回填草稿未生成：<stderr 原因>」；2 → 停下核对。
3. **关闭来源 issue**：`proposal.md` 有「来源 issue：」行且对应项在 verify-report 全为 ✅ → 逐个
   `issues_v2.py --root . set-status --id <ID> --to <DONE|FIXED> --evidence "{change} 归档"`（T 开头用 DONE、B 开头用 FIXED；已终态视为已关）。
4. **ADR 同步**（非阻塞）：按 g-adr 的 sync 步内联跑；`adr.py` 缺失或失败只记一行。

hand-off 三段：① 详细变更说明（按需求列出：完成的能力、关键模块/文件、修改前后行为、关键实现与取舍、对应提交/证据；附本次实际执行的测试命令、结果和覆盖边界，不能只抄票标题或写“已完成”。引用 verify 的 ✅，逐条确认锚存在）；② 未完成 / 延后（第 1 步的 id 按 summary 是否以「既有问题：」开头分两组 + verify 的 Minor 缺口 + 被延后的决策）；③ 下一阶段建议（含 roadmap 草稿）。末尾一行：`ADR 同步：候选 N / 修改 M / bug K`（或跳过原因）。

## archive

1. `openspec archive {change} -y --json`：exit 0 且顶层 `archive` 非 null → 成功（`warnings` 照录）；
   否则 fallback：`openspec archive {change} --skip-specs -y`，再**按代码实况**手动同步主 specs（ADDED 追加、MODIFIED 整条替换、REMOVED 删除、RENAMED 改名，匹配主 spec 既有风格），对动过的 spec 跑 `openspec validate <cap> --type spec`。
   手动同步的坑（首次执行踩过，逐条核）：
   - **以代码为准改写**，不照搬旧 delta 原文：delta 写于实现前，实现期的修订要落进主 spec。
   - **中文遗留主 spec**：既有主 spec 用中文标题/中文 Requirement 名时沿用其语言与写法，不混入英文模板标题，否则名字对不上、delta 核验必红。
   - **blockquote 不得写在 SHALL/MUST 句之前**：Requirement 首段须是含 SHALL/MUST 的规范句，说明性 `>` 引用放在其后，否则 validate 判缺规范句。
   - MODIFIED 是**整条替换**（含全部 Scenario），不是追加一段；REMOVED 连同其 Scenario 一起删。
   - 嵌套 capability（如 `identity/user-auth`）按同一相对路径落到 `openspec/specs/` 下。
2. 记 `{archive_dir}` = `openspec/changes/archive/<日期>-{change}/`（gate 判 ARCHIVE_UNCOMMITTED 时取 JSON `archive_dir`）。
3. **delta 核验**（MUST 在 commit 之前跑：MODIFIED 正文要与归档前的 HEAD 比对）：`python3 <skills_root>/g-done/scripts/delta_sync_check.py --archive-dir {archive_dir}`
   退出 0 → 继续；1 → 按输出补同步主 specs 后重跑，**MUST NOT 进入 commit**；2 → 停并报告。

## commit

1. `git add openspec/`
2. `git -c core.quotePath=false diff --name-only -- . ':(exclude)openspec'` 非空（openspec/ 外有已追踪未暂存改动）→ halt 并列清单：属于本 change 的先 `git add` 后重跑，无关的先移走。MUST NOT 用 `git add -u` 一并带入。
3. `git -c core.quotePath=false diff --cached --name-only -- . ':(exclude)openspec'` 非空（openspec/ 外有**已暂存**改动）→ halt 并列清单：这些代码没经过 verify，不得进归档提交；人确认后 `git restore --staged <路径>` 移出，属于本 change 的须回到 active 状态重新 verify。
4. Conventional Commits 中文 message（`type(scope): 动词开头描述`），用多个 `-m`，勿用 `\` 续行 + heredoc；**只提交 openspec/**：`git commit -m "<标题>" -m "<正文>" -- openspec/`。
   提交后重跑 gate：归档提交里的代码与 verify 锚定的已验证代码不一致 → UNKNOWN，停下交人。

## merge

1. 重新读取已提交的分支约定。merge_target=null → 直接结束，留在 work_branch（新建功能分支也不合并）；否则 base=merge_target，并确认在 work_branch 上发起合并。判 `{archive_dir}/.skip-merge`（已归档后标记随目录搬走；未归档则判 `{change_dir}/.skip-merge`）：存在 → 跳过 merge，摘要注明。
2. `git -c core.quotePath=false status --porcelain` 有任何 `??` 行 → halt 并列清单（先纳入版本控制或确认无关后重跑）。
3. 使用约定中的 work_branch（禁止取当前分支名猜来源），`git checkout {base}` → `git merge --ff-only {work_branch}`。
   不能快进 → **先 `git checkout {work_branch}` 回到工作分支**，再停下报告「base 已分叉，需手动决策」（停在 base 上会让重调时 gate 与分支约定都找不到本 change）；
   冲突 → `git merge --abort`、`git checkout {work_branch}`，再列冲突文件。**不 push**。

## SHIPPED 摘要

```
g-done 完成 — {change}
  链路: plan+impl(n/n) → review(pass) → verify PASS（Minor N 项）
  Hand-off: {archive_dir}/hand-off.md
  Specs:  已同步（happy path | --skip-specs 手动同步）· delta 核验通过
  Commit: <hash> <message>
  Merge:  {base} ← <分支>（ff）| 未请求合并，留在 {work_branch} | 按 .skip-merge 跳过
  Push:   未 push（手动控制）
```

工作树有未提交的非 openspec 改动时附一行提示（gate 判定不含它们，仅提示）。
