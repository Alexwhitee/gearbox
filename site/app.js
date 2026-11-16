'use strict';
const stages = [
 {command:'/g-spec',description:'先核对真实代码，再澄清目标与关键前提。',files:['decision-memo.md','proposal.md · design.md','specs/ · tasks.md'],label:'保留决策',rule:'讨论站稳一条，纪要保存一条。'},
 {command:'/g-review spec',description:'逐视角审查，明确批准后才进入实施。',files:['spec-review-report.md','发现与决策登记区','设计批准 + 内容指纹'],label:'用户拍板',rule:'报告通过，不等于用户已经批准。'},
 {command:'/g-implement',description:'按票依赖串行实现、自审，并执行验收。',files:['tickets.md','impl-reports/task<N>-<slug>.md','checkpoint 完成标签'],label:'真实验收',rule:'勾选复选框，不能独立授权推进。'},
 {command:'/g-review code',description:'检查跨票行为、范围、错误路径和历史问题。',files:['code-review-report.md','P0/P1 修复，或明确阻塞','P2 延期 → 真实 issue'],label:'共同口径',rule:'不能用登记 issue 代替阻塞项修复。'},
 {command:'/g-done <change>',description:'逐需求验证，保留交接记录，完成归档。',files:['verify-report.md','hand-off.md','archive/ · 同步后的 specs/'],label:'默认不合并',rule:'明确指定目标后，才尝试 ff-only 合并。'}
];
const command=document.querySelector('#demo-command');
if(command){
 document.querySelectorAll('[data-stage]').forEach(button=>button.addEventListener('click',()=>{
  const stage=stages[Number(button.dataset.stage)];
  document.querySelectorAll('[data-stage]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  command.textContent=stage.command;
  document.querySelector('#demo-description').textContent=stage.description;
  document.querySelector('#demo-files').replaceChildren(...stage.files.map(name=>{const span=document.createElement('span');span.textContent='↳ '+name;return span;}));
  document.querySelector('#demo-rule-label').textContent=stage.label;
  document.querySelector('#demo-rule').textContent=stage.rule;
 }));
}
const menu=document.querySelector('.menu-button');
if(menu){
 const navigation=document.querySelector('#navigation');
 const close=()=>{menu.setAttribute('aria-expanded','false');navigation.classList.remove('is-open');};
 menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));navigation.classList.toggle('is-open',open);});
 navigation.querySelectorAll('a').forEach(a=>a.addEventListener('click',close));
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&menu.getAttribute('aria-expanded')==='true'){close();menu.focus();}});
}
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-filter]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
 let visible=0;
 document.querySelectorAll('.skill-card').forEach(card=>{const show=button.dataset.filter==='all'||card.dataset.category===button.dataset.filter;card.hidden=!show;if(show)visible++;});
 document.querySelector('#skill-count').textContent=`显示 ${visible} 个 skills`;
}));
const scenarios={new:{command:'/g-init → /g-architecture → /g-devenv → /g-spec',text:'先明确系统边界与测试路径。确实跨多个变更时，再用 /g-roadmap 拆阶段。'},existing:{command:'/g-init → /g-spec → /g-review spec → /g-done <change>',text:'先复用已有设计、代码与测试约定。设计明确批准后，再推进实现、验证与归档。'},resume:{command:'/g-done <同一个 change 名>',text:'重新读取 gate、已有代码和报告，补齐缺失的实现与证据；不凭复选框或聊天记忆跳步。'}};
document.querySelectorAll('[data-scenario]').forEach(button=>button.addEventListener('click',()=>{
 document.querySelectorAll('[data-scenario]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
 const item=scenarios[button.dataset.scenario],target=document.querySelector('#scenario-content');
 const code=document.createElement('code'),p=document.createElement('p');code.textContent=item.command;p.textContent=item.text;target.replaceChildren(code,p);
}));
let toastTimer;
function toast(message){const target=document.querySelector('#toast');if(!target)return;clearTimeout(toastTimer);target.textContent=message;target.classList.add('visible');toastTimer=setTimeout(()=>target.classList.remove('visible'),3000);}
document.querySelectorAll('[data-copy]').forEach(button=>button.addEventListener('click',async()=>{
 const text=document.getElementById(button.dataset.copy)?.textContent;
 if(!text)return;
 try{await navigator.clipboard.writeText(text);toast('安装命令已复制');}catch{toast('浏览器未允许复制，请选中命令手动复制');}
}));
const search=document.querySelector('#guide-search');
if(search){
 const article=document.querySelector('#guide-article'),status=document.querySelector('#guide-search-status');
 search.addEventListener('input',()=>{
  article.querySelectorAll('mark').forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent)));
  article.normalize();
  const query=search.value.trim();
  if(query.length<2){status.textContent='输入至少 2 个字符，查找手册中的内容';return;}
  const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT,{acceptNode:node=>node.parentElement.closest('script,style')?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT});
  const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
  let count=0;
  for(const node of nodes){const value=node.textContent,lower=value.toLocaleLowerCase(),needle=query.toLocaleLowerCase();let start=0,index=lower.indexOf(needle);if(index<0)continue;const fragment=document.createDocumentFragment();while(index>=0){fragment.append(document.createTextNode(value.slice(start,index)));const mark=document.createElement('mark');mark.textContent=value.slice(index,index+query.length);fragment.append(mark);count++;start=index+query.length;index=lower.indexOf(needle,start);}fragment.append(document.createTextNode(value.slice(start)));node.replaceWith(fragment);}
  status.textContent=count?`找到 ${count} 处匹配；按 Enter 跳到第一处`:'没有找到匹配内容';
 });
 search.addEventListener('keydown',event=>{if(event.key==='Enter')article.querySelector('mark')?.scrollIntoView({block:'center',behavior:'smooth'});});
}
