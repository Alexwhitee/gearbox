# 演进依据与历史取舍

> 仅在审计历史取舍时读取。本文不参与默认收尾执行。

## 1. v3 改进摘要（相对更早版本）

早期版本的归档步用手动 `mv` 搬迁 change 目录，漏掉了 delta 同步这一步，导致新能力永远进不了
`openspec/specs/`；也未做默认分支检测（容易误假设 `main`）、合并缺省行为不明确、未强制
verify 产出 `verify-report.md`。这些改进已固化进正文（以下为当前章节名）：

- 归档必须走 `openspec archive` CLI，CLI 失败才走 `--skip-specs` + 手动同步 → 「## archive」第 1 步；
  归档后用 `delta_sync_check.py` 机械核对 → 「## archive」第 3 步。
- 不再猜默认分支：合并目标来自本 change 的分支约定（`.g-branch.json` 的 `merge_target`）→ 「## 第零步」第 4–5 步。
- 合并**缺省不执行**：`merge_target` 默认 null，只提交归档、留在工作分支；只有用户明确指定目标才合并
  （早期版本曾「merge 缺省执行」，与现行为相反）→ 「## merge」。
- `verify-report.md` 是硬性可交付 → 「## verify」第 5–7 步。
- 模型档位已随 fan-out 架构移除，不再按步定档位。

## 2. 首次执行踩坑速记

以下踩坑记录来自本 skill 首次实际执行时的复盘，均已提炼进正文对应步骤，保留在此仅作历史参考：

- 手动归档漏 spec 同步 → 「## archive」第 1 步「归档必须用 openspec archive CLI」。
- 中文遗留主 spec、blockquote 写在 MUST 前、照搬旧 delta 原文 → 「## archive」第 1 步「手动同步的坑」。
- 复选框 stale（未做的项被勾、做了的没勾）→ 「## verify」第 1 步（真实完成才勾，不为过归档假勾）。
- 硬编码 main / `--no-ff` → 「## merge」第 3 步（按约定目标 `--ff-only`，不能快进即停）。
