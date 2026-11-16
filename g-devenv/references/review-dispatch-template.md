# 内联自审材料清单

> SKILL ④ 主 session 逐镜自审时，按本清单收集材料。镜的问题与输出格式都在 [`review-lenses.md`](./review-lenses.md)，本模板只列要交的材料。

## 必交材料

每面镜都交以下全部，缺一项会让镜在没证据的情况下下结论：

1. `.devenv.json`
2. 渲染后的 `testing-strategy.md`
3. `environments.md`
4. 本轮落地物 diff：`git diff <round.base_commit>`
5. `.devenv-runs/` 下最近的失败日志路径
6. 未跟踪文件清单及其内容：`git status --porcelain --untracked-files=all` 列出的每个文件都要交内容。`git diff` 不含未跟踪文件，而新建的 smoke / harness 多半是未跟踪的，必须在内。例外：`.env`、密钥、凭证类文件只列路径，不交内容。

## 本镜的问题

指向 `review-lenses.md` 中该镜对应的节，不在 prompt 里复制问题清单。

## 输出格式

指向 `review-lenses.md`「输出格式」节。

## 执行方式

主 session 按视角逐次核对并保存发现与处置；无子代理派发、前缀文件或回执。
