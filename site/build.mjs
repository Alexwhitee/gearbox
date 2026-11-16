import {readFile,writeFile,mkdir,copyFile,readdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=fileURLToPath(new URL('../',import.meta.url)),source=path.join(root,'site'),dist=path.join(source,'dist');
const require=createRequire(import.meta.url),marked=require(path.join(root,'g-init/assets/hack/review-page/marked.umd.js'));
const escape=value=>value.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const skills=[
 ['g-spec','flow','需求与规格','把澄清、拷问和生成放在同一条路径上，先确认承重前提，再形成正式变更材料。','需求、项目现状与约束','四件套 + decision-memo.md','main-flow'],
 ['g-review','flow','设计审与代码审','串行检查范围、领域、对抗与接地事实。区分结构通过、内容判断和用户批准。','spec / code 模式、本次变更','spec-review-report / code-review-report','main-flow'],
 ['g-implement','flow','逐票实施与自审','出票与执行分开。以纵向切片交付行为，按 Blocked-by 串行选票，逐票保存验收证据。','已批准的设计、tasks 与 specs','tickets.md、实现报告、完成标签','main-flow'],
 ['g-done','flow','推进到完整交付','每步读取 gate，从当前盘面继续实现、评审、验证、交接和归档。默认不合并、不 push。','真实 change 名、可选明确合并目标','verify-report、hand-off、归档记录','main-flow'],
 ['g-architecture','planning','系统架构与边界','采集事实、划分子系统、定义 contract，检查场景覆盖，形成可进入骨架实施的 SAD。','系统定位、外部依赖、硬约束','sad.md、架构日志、骨架建议','planning'],
 ['g-roadmap','planning','跨变更的阶段规划','把超过一个 change 的工作拆成分阶段交付。近期细化，远期保留边界与依赖。','长期目标、约束、已有架构','design / roadmap / task-log','planning'],
 ['g-devenv','planning','环境与测试策略','查明单元、集成与 e2e 怎么跑，写出每层信心与盲区，记录真实泳道状态与证据。','现有代码、CI、测试服务、可选 SAD','testing-strategy、environments、泳道状态','planning'],
 ['g-init','support','给项目接入工作流','铺设项目骨架、schema 和人读手册，注入托管入口，保留项目自定义内容。','目标项目、已有 OpenSpec 配置','项目配置、目录与入口托管区块','installation'],
 ['g-upgrade','support','更新本机工具链','按实际运行 checkout 的远程执行 ff-only 更新，再刷新安装，避免指令与脚本版本错位。','实际安装来源与 Git 状态','更新后的 skills、全局工具与版本信息','upgrade'],
 ['g-issues','support','缺陷与待办台账','bug 与 todo 分池。一个问题一个文件，记录来源、状态与证据，复用历史 ID。','故障或改进、模块与来源','B/T issue、生成索引、状态历史','records'],
 ['g-adr','support','长期决策与取舍','新建决策、按变更同步、分批体检已有 ADR。格式交给脚本，内容事实依靠读码核对。','决策背景、备选、代码与变更','ADR 文件、格式检查与偏离记录','records'],
 ['g-retro','support','流程复盘','从已有 Git 与报告再生阶段耗时和历史统计。只呈现已有证据，不自动调整流程。','变更历史、评审报告与已有数据','openspec/retro/report.md','records']
];
const names=(await readdir(root)).filter(name=>name.startsWith('g-')).sort();
if(names.join()!==skills.map(s=>s[0]).sort().join())throw new Error('Skill catalogue must match repository skills');
for(const [name] of skills){const text=await readFile(path.join(root,name,'SKILL.md'),'utf8');if(!text.includes(`name: ${name}\n`))throw new Error(`Invalid skill: ${name}`);}
const labels={flow:'开发主线',planning:'项目规划',support:'记录与维护'};
const cards=skills.map(([name,category,title,description,input,output,anchor],index)=>`<article class="skill-card" data-category="${category}"><div class="skill-card-top"><span class="skill-index">SKILL ${String(index+1).padStart(2,'0')}</span><span class="skill-category">${labels[category]}</span></div><h3>/${name}</h3><div class="skill-title">${title}</div><p>${description}</p><details><summary>输入、产物与用法 <span>＋</span></summary><dl><dt>输入 / INPUT</dt><dd>${input}</dd><dt>产物 / OUTPUT</dt><dd>${output}</dd><dt>继续阅读</dt><dd><a class="text-link" href="/guide/#${anchor}">查看使用手册 ↗</a></dd></dl></details></article>`).join('\n');
await mkdir(path.join(dist,'guide'),{recursive:true});
const home=(await readFile(path.join(source,'index.html'),'utf8')).replace('<!-- SKILL_CARDS -->',cards);
let readme=await readFile(path.join(root,'README.md'),'utf8');
// 静态手册只映射仓库链接；全文仍来自当前 README。
readme=readme.replace(/\]\(\.\/([^)]*)\)/g,(_,relative)=>`](https://github.com/Alexwhitee/gearbox/blob/main/${relative})`);
const anchors=[...readme.matchAll(/<a id="([^"]+)"><\/a>\s*\n## (.+)/g)];
let article=marked.parse(readme,{gfm:true});
article=article.replace(/<table>([\s\S]*?)<\/table>/g,'<div class="table-scroll"><table>$1</table></div>');
const guide=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>完整使用手册 — G Skills</title><meta name="description" content="G Skills 的完整安装与使用手册：12 个 skill、开发流程、验证规则、分支管理、断点恢复与常见问题。"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css"><script src="/app.js" defer></script></head><body><a class="skip" href="#main">跳到正文</a><header class="header"><a class="brand" href="/"><span class="brand-mark">g<span>↗</span></span><span>G SKILLS<span class="brand-sub">DEVELOP WITH INTENT</span></span></a><a class="text-link" href="https://github.com/Alexwhitee/gearbox">GitHub ↗</a></header><main class="wrap guide-shell" id="main"><aside class="guide-sidebar" aria-label="手册目录"><a class="back-home" href="/">← 项目介绍</a><p class="eyebrow">THE FIELD GUIDE / 使用手册</p><label class="sr-only" for="guide-search">搜索手册</label><input class="guide-search" type="search" id="guide-search" placeholder="搜索手册，例如：分支、PASS" autocomplete="off" aria-describedby="guide-search-status"><span id="guide-search-status" class="guide-search-status" role="status">输入至少 2 个字符，查找手册中的内容</span>${anchors.map(([_,id,title])=>`<a href="#${escape(id)}">${escape(title)}</a>`).join('')}</aside><div><div class="guide-intro"><p class="eyebrow">G SKILLS / DOCUMENTATION</p><h1>完整使用手册</h1><p>从安装到交付，所有关键步骤与边界。内容与项目 README 同源。<br>仓库源文件链接需要对应的 GitHub 访问权限。</p></div><article id="guide-article" class="guide-content">${article}</article></div></main><footer class="footer wrap"><a class="brand" href="/">G SKILLS</a><span>规格先行 · 串行推进 · 证据交付</span><div><a href="/">项目介绍</a><a href="/LICENSE.txt">Apache-2.0</a></div></footer><div class="toast" role="status" id="toast"></div></body></html>`;
await writeFile(path.join(dist,'index.html'),home);
await writeFile(path.join(dist,'guide/index.html'),guide);
for(const file of ['styles.css','app.js','favicon.svg','_headers'])await copyFile(path.join(source,file),path.join(dist,file));
await copyFile(path.join(root,'LICENSE'),path.join(dist,'LICENSE.txt'));
await writeFile(path.join(dist,'404.html'),`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>页面未找到 — G Skills</title><link rel="stylesheet" href="/styles.css"></head><body><main class="wrap section"><p class="eyebrow">404 / PAGE NOT FOUND</p><h1>这条路径还没有落点。</h1><p>可以返回项目介绍，或从完整手册重新开始。</p><a class="button primary" href="/">返回首页 ↗</a></main></body></html>`);
console.log(`Built ${skills.length} skill cards and ${anchors.length} guide sections → site/dist`);
