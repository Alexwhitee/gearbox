# G Skills 网站

静态项目介绍页，以及与根目录 README 同源生成的完整使用手册。无新增 npm 依赖、无运行时服务、无外部字体或统计脚本。

线上地址：[项目介绍](https://g-skills.pages.dev/) · [完整使用手册](https://g-skills.pages.dev/guide/)。部署到 Cloudflare Pages 的 `g-skills` 项目，后续更新使用下方直接上传命令。

## 本地构建与预览

在仓库根目录运行：

```bash
node site/build.mjs
node site/check.mjs
python3 -m http.server 4173 --directory site/dist --bind 127.0.0.1
```

打开 `http://127.0.0.1:4173/`；手册在 `/guide/`。修改根 README 后重新构建，避免维护两份手册。

构建脚本复用仓库已带的 Markdown 渲染器，仅在构建时使用。`dist/` 是生成物，不提交。首页的 12 个 skill 由构建脚本核对真实目录与名称。

## Cloudflare Pages 部署

先在本机完成 `wrangler login`，不要把令牌写进项目文件。以下命令使用已登录的 Cloudflare 账号；项目已存在时跳过 create。

```bash
node site/build.mjs
WRANGLER_SEND_METRICS=false wrangler pages project create g-skills --production-branch main
WRANGLER_SEND_METRICS=false wrangler pages deploy site/dist --project-name g-skills --branch main --commit-dirty=true
```

仓库有多个 Cloudflare 账号时，通过 `CLOUDFLARE_ACCOUNT_ID` 明确本次目标账号；不要在未确认的账号下部署。`site/wrangler.toml` 可用于从 `site/` 目录部署。

部署前检查桌面与手机布局、阶段切换、skill 筛选、安装命令复制、FAQ、手册搜索和站内链接。Cloudflare 部署后再核对首页与 `/guide/` 的 HTTPS 响应。
