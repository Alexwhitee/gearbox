import assert from 'node:assert/strict';
import {readFile,stat} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const dist=fileURLToPath(new URL('./dist/',import.meta.url));
const pages=['index.html','guide/index.html','404.html'];
let checked=0;
for(const page of pages){
 const html=await readFile(path.join(dist,page),'utf8');
 assert(!html.includes('sdflow-skills'),'Public site contains removed project mention');
 if(page!=='404.html')assert(/<header[\s\S]*?href="https:\/\/github\.com\/Alexwhitee\/gearbox"[\s\S]*?<\/header>/.test(html),'Missing header GitHub link');
 const base=new URL(page==='index.html'?'/':page.replace('index.html',''),'https://g-skills.example');
 for(const [,href] of html.matchAll(/(?:href|src)="([^"]+)"/g)){
  const url=new URL(href,base);
  if(url.origin!==base.origin)continue;
  const local=decodeURIComponent(url.pathname).replace(/^\//,'');
  const filename=path.join(dist,url.pathname.endsWith('/')?local+'index.html':local);
  assert(filename.startsWith(dist),'Site link escapes output directory');
  assert((await stat(filename)).isFile(),`Broken site link: ${href}`);
  if(url.hash){
   const target=await readFile(filename,'utf8');
   assert(target.includes(`id="${decodeURIComponent(url.hash.slice(1))}"`),`Missing anchor: ${href}`);
  }
  checked++;
 }
}
const guide=await readFile(path.join(dist,'guide/index.html'),'utf8');
for(const section of ['main-flow','skills','verification','git','resume','faq'])assert(guide.includes(`id="${section}"`));
assert((await stat(path.join(dist,'LICENSE.txt'))).size>0);
assert((await readFile(path.join(dist,'_headers'),'utf8')).includes("script-src 'self'"));
console.log(`Site check passed: ${pages.length} pages, ${checked} local links/assets, guide anchors and deployment headers`);
