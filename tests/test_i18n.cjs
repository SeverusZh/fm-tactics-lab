const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ui = path.join(__dirname, '../src/tactics_ui');
function text(data, ignored=false){return {nodeType:3,data,parentElement:{closest:()=>ignored}};}
async function environment(system,browser){
 const title=text('战术板'), status=text('已选 19 队'), log=text('保持队形',true);
 const name=text('张 三（保持队形）');
 const control={nodeType:1,childNodes:[],value:'保持队形',attrs:{placeholder:'选择存档'},
  matches:()=>false,hasAttribute(k){return k in this.attrs;},getAttribute(k){return this.attrs[k];},setAttribute(k,v){this.attrs[k]=v;}};
 const root={nodeType:1,childNodes:[title,status,log,name,control],matches:()=>false,hasAttribute:()=>false};
 const original={teams:[{name:'张 三（保持队形）',instructions:{1:123},players:[{name:'张 三（保持队形）',attributes:[15,18]}]}]};
 const state=structuredClone(original);
 let callback;
 const context={window:{},navigator:{language:browser},document:{documentElement:root},state,
  fetch:async()=>({ok:true,json:async()=>({language:system})}),
  MutationObserver:class{constructor(fn){callback=fn;}observe(){}disconnect(){}}};
 vm.createContext(context);
 for(const file of ['i18n-en.js','i18n.js'])vm.runInContext(fs.readFileSync(path.join(ui,file),'utf8'),context);
 // Browser globals expose window properties as identifiers.
 await context.window.FM27I18n.ready;
 return {context,title,status,log,name,control,original,state,mutate:node=>callback([{type:'characterData',target:node}])};
}
(async()=>{
 // The OS setting overrides a browser with the opposite language.
 const en=await environment('en','zh-CN');
 // Populate the isolated window object as the browser would before re-evaluation.
 // Catalogue is referenced on window, so no global alias is needed.
 assert.equal(en.title.data,'Tactics board');
 assert.match(en.status.data,/Selected 19 teams/);
 assert.equal(en.name.data,'张 三（保持队形）');
 assert.equal(en.log.data,'保持队形');
 assert.equal(en.control.value,'保持队形');
 assert.equal(en.control.attrs.placeholder,'Choose save');
 assert.deepEqual(en.state,en.original);
 const translate=en.context.window.FM27I18n.translate;
 assert.equal(translate('保持队形'),'Hold shape');
 assert.equal(translate('有球阶段配置'),'In-possession phase Configuration');
 assert.equal(translate('导入客队战术池'),'Import into away tactic pool');
 assert.equal(translate('主队球员 01'),'Home Player 01');
 assert.equal(translate('立刻反击'),'Counter');
 assert.equal(translate('重新组织防守'),'Regroup');
 assert.equal(translate('立即反抢'),'Counter-press');
 en.status.data='正在模拟 2 / 6';en.mutate(en.status);
 assert.equal(en.status.data,'Simulating 2 / 6');
 en.mutate(en.status);assert.equal(en.status.data,'Simulating 2 / 6');
 en.state.teams[0].players[0].name='保持队形（测试）';
 en.name.data='保持队形（测试）';en.mutate(en.name);
 assert.equal(en.name.data,'保持队形（测试）');
 const zh=await environment('zh-CN','en-US');
 assert.equal(zh.title.data,'战术板');assert.equal(zh.control.attrs.placeholder,'选择存档');
 const dictionary=en.context.window.FM27English;
 for(const filename of fs.readdirSync(ui).filter(f=>/\.(js|html)$/.test(f)&&!f.startsWith('i18n'))){
  for(const word of fs.readFileSync(path.join(ui,filename),'utf8').match(/[\u3400-\u9fff]+/g)||[]){
   assert.ok(dictionary[word],`Missing translation in ${filename}: ${word}`);
  }
 }
 console.log('OS language, dynamic rendering, native values, names and transition labels verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
