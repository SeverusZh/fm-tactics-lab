'use strict';
const poolDefaults=()=>({profile:'away-tactic-pool-v1',enabled:false,entries:[],uniform:{enabled:true,attribute_value:15},rotation:{enabled:false,rounds:1},real:{enabled:false}});
const poolLimit=10000;
const poolRealOffNotice='真实名单模式已关闭：不是每套战术都有存档名单。';
function poolData(){
 const pool=state.away_tactic_pool??=poolDefaults();
 pool.entries??=[];pool.uniform??={enabled:true,attribute_value:15};pool.rotation??={enabled:false,rounds:1};pool.real??={enabled:false};
 if(!Number.isInteger(pool.rotation.rounds)||pool.rotation.rounds<1)pool.rotation.rounds=1;
 pool.rotation.enabled=pool.rotation.enabled===true;pool.real.enabled=pool.real.enabled===true;
 return pool;
}
const poolRead=()=>state?.away_tactic_pool??poolDefaults();
const poolTotal=pool=>pool.entries.reduce((n,e)=>n+(e.weight||1),0);
const poolMaxRounds=entries=>Math.max(1,Math.min(1000,entries?Math.floor(poolLimit/entries):1000));
function poolStatus(pool=poolRead()){
 const entries=pool.entries||[];
 if(!pool.enabled||!entries.length)return{cls:'pool-state-off',label:'已关闭'};
 if(pool.rotation?.enabled)return{cls:'pool-state-rotation',label:`轮战 ${entries.length}`};
 return{cls:'pool-state-random',label:`随机 ${entries.length}`};
}
const poolRealMissing=(pool=poolRead())=>(pool.entries||[]).filter(entry=>!entry.roster).map(entry=>entry.name);
function poolRealReason(pool=poolRead(),forHtml=false){
 const entries=pool.entries||[],missing=poolRealMissing(pool);
 if(!entries.length)return'还没有客队战术，导入后才能使用真实名单。';
 if(!missing.length)return'';
 const names=missing.slice(0,3).map(name=>forHtml?esc(name):name).join('、')+(missing.length>3?'等':'');
 return`真实名单不可用：${names} 没有存档名单，统一属性仍可使用。`;
}
const poolSnapshot=()=>state?.away_tactic_pool?clone(state.away_tactic_pool):null;
let poolCountRestore=null,poolPanelScroll=0,poolPreviousFocus=null;
function syncPoolCount(roundsOverride){
 const input=$('#count');if(!input)return;
 const pool=poolRead(),locked=saveMode!=='save'&&!!pool.enabled&&!!pool.rotation?.enabled;
 if(!locked){
  if(poolCountRestore){input.value=poolCountRestore.value;input.disabled=poolCountRestore.disabled;poolCountRestore=null}
  return;
 }
 poolCountRestore??={value:input.value,disabled:input.disabled};
 const rounds=roundsOverride??pool.rotation.rounds;
 input.value=String(Math.max(1,(pool.entries?.length||0)*rounds));
 input.disabled=true;
}
function syncPoolBar(){
 const button=$('#pool-open');if(!button)return;
 if(saveMode==='save'&&!poolPanel.hidden)closePoolPanel();
 const status=poolStatus();
 button.hidden=saveMode==='save';
 button.setAttribute('aria-expanded',String(!poolPanel.hidden));
 button.innerHTML=`战术池 <span class="tag ${status.cls}">${status.label}</span>`;
 syncPoolCount();
}
async function poolSave(previousPool){
 try{state=(await api('/api/validate',clone(state))).scenario;save()}
 catch(e){
  if(previousPool===null)delete state.away_tactic_pool;
  else if(previousPool!==undefined)state.away_tactic_pool=previousPool;
  toast('战术池保存失败：'+e.message);
  render();
  return false;
 }
 render();
 return true;
}
function poolEmpty(){
 return `<div class="pool-empty"><div class="symbol">⇄</div><h3>还没有客队战术</h3><p>导入本机 FMF，或在存档战术页加入联赛战术。</p><button type="button" class="button primary" data-pool-import>导入 FMF</button></div>`;
}
function poolTable(pool,total){
 const rotation=!!pool.rotation?.enabled,entries=pool.entries;
 const rows=entries.map((entry,index)=>{
  const weight=entry.weight||1,order=rotation?`顺序 ${index+1}`:(total?pct(weight/total):'0%');
  return `<tr data-pool-entry="${index}"><td class="pool-index">${String(index+1).padStart(2,'0')}</td><td class="pool-entry-name"><span title="${esc(entry.tactic?.tactic_name||entry.name)}">${esc(entry.name)}</span></td><td>${entry.roster?'<span class="tag pool-roster">存档名单</span>':'<span class="tag muted">统一属性</span>'}</td><td><input type="number" min="1" max="1000" step="1" value="${weight}" data-pool-weight="${index}" aria-label="权重"></td><td class="pool-prob">${order}</td><td class="pool-row-action"><button type="button" class="button small ghost" data-pool-remove="${index}">删除</button></td></tr>`;
 }).join('');
 const head=rotation?'<th>序号</th><th>战术</th><th>名单</th><th>权重</th><th>轮战顺序</th><th>删除</th>':'<th>序号</th><th>战术</th><th>名单</th><th>权重</th><th>单套概率</th><th>删除</th>';
 return `<div class="table-scroll"><table class="pool-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function poolPanelView(){
 const pool=poolData(),entries=pool.entries,total=poolTotal(pool),rotation=!!pool.rotation.enabled,real=!!pool.real.enabled,status=poolStatus(pool);
 const missing=poolRealMissing(pool),realReady=entries.length>0&&!missing.length,rounds=pool.rotation.rounds,rotationTotal=entries.length*rounds;
 const modeNote=rotation?'按条目顺序轮换客队战术，每套连续运行设定轮数。':'每场从候选列表按权重抽取对手战术；关闭后使用当前选定的对手战术。';
 const rotationInline=rotation?`<div class="pool-inline"><label class="pool-field">每套轮数<input id="pool-rounds" type="number" min="1" max="${poolMaxRounds(entries.length)}" step="1" value="${rounds}" aria-label="每套轮数"></label><span class="pool-total tag">每方案 ${entries.length}×${rounds} = ${rotationTotal} 场</span></div>`:'';
 const rotationWarning=rotation&&rotationTotal>poolLimit?`<p class="pool-warn">轮战每方案需要 ${entries.length}×${rounds} = ${rotationTotal} 场，超过 10000 场上限；请减少每套轮数。</p>`:'';
 const realNote=real?'<p class="pool-note">真实名单使用导入自存档的球员姓名与属性，导入后不随存档变化。</p>':`<div class="pool-inline"><label class="pool-field">属性值<input id="pool-uniform-value" type="number" min="1" max="20" step="1" value="${pool.uniform.attribute_value}" aria-label="属性值"></label></div><p class="pool-note">开启后，每名首发在战术位置的熟练度固定为满值，其余属性统一为设定面板值。</p>`;
 const uniformWarning=real||pool.uniform.enabled?'':'<p class="pool-warn">统一属性当前未启用，修改属性值后会启用。</p>';
 const modeWarning=entries.length?'':'<p class="pool-note">还没有客队战术，导入后才能选择抽取方式。</p>';
 const realReason=poolRealReason(pool,true);
 return `<header class="pool-panel-head"><div class="pool-panel-title"><h2 id="pool-panel-title">客队战术池</h2><span class="tag ${status.cls}">${status.label}</span></div><button type="button" class="button small ghost" data-pool-close>关闭</button></header><div class="pool-panel-body"><section class="pool-section"><label class="pool-switch"><input id="pool-enabled" type="checkbox" ${pool.enabled?'checked':''}>启用客队战术池</label><p class="pool-note">开启后，客队每场按抽取方式使用池内战术；关闭后使用当前选定的对手战术。</p></section><div class="pool-mode-grid"><section class="pool-section"><div class="pool-section-head"><h3>抽取方式</h3></div><div class="segmented pool-segmented"><button type="button" data-pool-mode="random" class="${rotation?'':'active'}" aria-pressed="${!rotation}" ${entries.length?'':'disabled'}>随机抽取</button><button type="button" data-pool-mode="rotation" class="${rotation?'active':''}" aria-pressed="${rotation}" ${entries.length?'':'disabled'}>轮战模式</button></div>${rotationInline}<p class="pool-note">${modeNote}</p>${modeWarning}${rotationWarning}</section><section class="pool-section"><div class="pool-section-head"><h3>客队名单</h3></div><div class="segmented pool-segmented"><button type="button" data-pool-roster="uniform" class="${real?'':'active'}" aria-pressed="${!real}">统一属性</button><button type="button" data-pool-roster="real" class="${real?'active':''}" aria-pressed="${real}" ${realReady?'':'aria-disabled="true"'}>真实名单</button></div>${realNote}${uniformWarning}${realReason?`<p class="pool-note">${realReason}</p>`:''}</section></div><section class="pool-section pool-entries"><div class="pool-section-head"><h3>战术条目</h3><span class="tag">${entries.length} 套</span></div>${entries.length?poolTable(pool,total):poolEmpty()}${entries.some(entry=>entry.roster)?'<p class="pool-note">带存档名单的候选合计上限约 1.5 MB；A/B 对照与本地保存会占用更多空间。</p>':''}</section></div><footer class="pool-panel-actions"><span class="pool-panel-foot-note">${entries.length} 套</span><button type="button" class="button" data-pool-import>导入 FMF</button><button type="button" class="button" data-pool-library>前往存档战术页面</button><button type="button" class="button primary" data-pool-close>完成</button></footer><input id="pool-import-file" type="file" accept=".fmf" multiple hidden>`;
}
async function poolImportFiles(event){
 const files=[...event.target.files];if(!files.length)return;
 const realWasOn=!!poolRead().real?.enabled,failures=[];let imported=0;
 [...poolPanel.querySelectorAll('[data-pool-import]')].forEach(button=>{button.disabled=true;button.textContent='正在导入…'});
 for(const file of files){
  if(!/\.fmf$/i.test(file.name)){failures.push(file.name+'：请选择战术 FMF 文件');continue}
  if(file.size>4*1024*1024){failures.push(file.name+'：文件超过 4 MB');continue}
  try{
   const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
   const scenario=clone(state);
   if(realWasOn&&scenario.away_tactic_pool)scenario.away_tactic_pool.real.enabled=false;
   const result=await api('/api/pool/import-fmf',{scenario,file_base64:btoa(binary),name:file.name.replace(/\.fmf$/i,'').trim().slice(0,80)});
   state=result.scenario;save();imported++;
  }catch(e){failures.push(file.name+'：'+e.message)}
 }
 event.target.value='';
 render();
 let message=imported?`已导入 ${imported} 套战术`+(failures.length?`，${failures.length} 个失败`:''):'没有导入成功';
 if(imported&&realWasOn)message+='；'+poolRealOffNotice;
 toast(message);
 if(failures.length)setTimeout(()=>toast(failures[0]),1200);
}
function fillPoolPanel(){
 const body=poolPanel.querySelector('.pool-panel-body');
 poolPanelScroll=body?body.scrollTop:0;
 poolPanel.innerHTML=poolPanelView();
 bindPool();
 const next=poolPanel.querySelector('.pool-panel-body');
 if(next)next.scrollTop=poolPanelScroll;
}
function openPoolPanel(){
 if(!state||saveMode==='save')return;
 poolPreviousFocus=document.activeElement instanceof HTMLElement?document.activeElement:null;
 fillPoolPanel();
 poolPanel.hidden=false;
 $('#pool-open')?.setAttribute('aria-expanded','true');
 poolPanel.querySelector('[data-pool-close]')?.focus?.();
}
function closePoolPanel(){
 if(poolPanel.hidden)return;
 poolPanel.hidden=true;
 $('#pool-open')?.setAttribute('aria-expanded','false');
 if(poolPreviousFocus?.isConnected)poolPreviousFocus.focus?.();
 poolPreviousFocus=null;
}
function togglePoolPanel(){if(poolPanel.hidden)openPoolPanel();else closePoolPanel()}
function bindPool(){
 const find=selector=>poolPanel.querySelector(selector),findAll=selector=>[...poolPanel.querySelectorAll(selector)];
 const enabled=find('#pool-enabled');
 if(enabled)enabled.onchange=async event=>{
  const pool=poolData();
  if(event.target.checked&&!pool.entries.length){event.target.checked=false;toast('请先导入客队战术');return}
  const previous=poolSnapshot();pool.enabled=event.target.checked;await poolSave(previous);
 };
 findAll('[data-pool-mode]').forEach(button=>button.onclick=async()=>{
  const pool=poolData(),rotation=button.dataset.poolMode==='rotation';
  if(rotation&&!pool.entries.length){toast('请先导入客队战术');return}
  if(rotation===!!pool.rotation.enabled)return;
  const previous=poolSnapshot();
  let adjusted=0;
  if(rotation&&pool.entries.length*pool.rotation.rounds>poolLimit){adjusted=poolMaxRounds(pool.entries.length);pool.rotation.rounds=adjusted}
  pool.rotation.enabled=rotation;
  const ok=await poolSave(previous);
  if(ok&&adjusted)toast(`轮战每方案最多 10000 场，每套轮数已调整为 ${adjusted}`);
 });
 findAll('[data-pool-roster]').forEach(button=>button.onclick=async()=>{
  const pool=poolData(),real=button.dataset.poolRoster==='real';
  if(real){
   const missing=poolRealMissing(pool);
   if(!pool.entries.length){toast('还没有客队战术，导入后才能使用真实名单。');return}
   if(missing.length){toast(poolRealReason(pool));return}
  }
  if(real===!!pool.real.enabled&&(real||pool.uniform.enabled))return;
  const previous=poolSnapshot();
  pool.real.enabled=real;
  if(!real)pool.uniform.enabled=true;
  await poolSave(previous);
 });
 const rounds=find('#pool-rounds');
 if(rounds){
  rounds.oninput=()=>{
   const pool=poolRead(),value=Number(rounds.value),entries=pool.entries.length;
   const label=find('.pool-total');
   if(label&&entries&&Number.isInteger(value)&&value>=1)label.textContent=`每方案 ${entries}×${value} = ${entries*value} 场`;
   if(Number.isInteger(value)&&value>=1)syncPoolCount(value);
  };
  rounds.onchange=async()=>{
   const pool=poolData(),value=Number(rounds.value),entries=pool.entries.length;
   if(!Number.isInteger(value)||value<1||value>1000){toast('每套轮数须为 1–1000 的整数');fillPoolPanel();return}
   if(entries&&entries*value>poolLimit){toast(`轮战每方案需要 ${entries}×${value} = ${entries*value} 场，超过 10000 场上限`);fillPoolPanel();return}
   const previous=poolSnapshot();pool.rotation.rounds=value;await poolSave(previous);
  };
 }
 const uniform=find('#pool-uniform-value');
 if(uniform)uniform.onchange=async()=>{
  const value=Number(uniform.value),pool=poolData();
  if(!Number.isInteger(value)||value<1||value>20){toast('统一属性值须为 1–20 的整数');fillPoolPanel();return}
  const previous=poolSnapshot();pool.uniform.attribute_value=value;pool.uniform.enabled=true;await poolSave(previous);
 };
 findAll('[data-pool-weight]').forEach(input=>input.onchange=async()=>{
  const pool=poolData(),weight=Number(input.value);
  if(!Number.isInteger(weight)||weight<1||weight>1000){toast('权重须为 1–1000 的整数');fillPoolPanel();return}
  const previous=poolSnapshot();pool.entries[+input.dataset.poolWeight].weight=weight;await poolSave(previous);
 });
 findAll('[data-pool-remove]').forEach(button=>button.onclick=async()=>{
  const pool=poolData(),previous=poolSnapshot();
  pool.entries.splice(+button.dataset.poolRemove,1);
  let closedReal=false;
  if(pool.real.enabled&&(!pool.entries.length||poolRealMissing(pool).length)){pool.real.enabled=false;closedReal=true}
  if(!pool.entries.length){pool.enabled=false;pool.rotation.enabled=false}
  const ok=await poolSave(previous);
  if(ok&&closedReal)toast(poolRealOffNotice);
 });
 findAll('[data-pool-import]').forEach(button=>button.onclick=()=>find('#pool-import-file').click());
 const file=find('#pool-import-file');
 if(file)file.onchange=poolImportFiles;
 findAll('[data-pool-close]').forEach(button=>button.onclick=()=>closePoolPanel());
 findAll('[data-pool-library]').forEach(button=>button.onclick=()=>{closePoolPanel();view='library';render();window.scrollTo(0,0)});
}
const poolPanel=document.createElement('section');
poolPanel.id='tactic-pool-panel';poolPanel.className='tactic-pool-panel';
poolPanel.setAttribute('role','dialog');poolPanel.setAttribute('aria-modal','false');poolPanel.setAttribute('aria-labelledby','pool-panel-title');poolPanel.hidden=true;
document.body.append(poolPanel);
const poolOpen=document.createElement('button');
poolOpen.id='pool-open';poolOpen.type='button';poolOpen.className='button pool-open';
poolOpen.setAttribute('aria-haspopup','dialog');poolOpen.setAttribute('aria-controls','tactic-pool-panel');poolOpen.setAttribute('aria-expanded','false');
poolOpen.addEventListener('click',togglePoolPanel);
const poolQuickMode=$('#quick-score-mode')?.closest('label'),poolCancel=$('#cancel');
if(poolQuickMode)poolQuickMode.after(poolOpen);else if(poolCancel)poolCancel.before(poolOpen);
if(poolCancel)poolOpen.after(poolCancel);
const updatePoolPosition=()=>{const runbar=$('.runbar');if(runbar)document.documentElement.style.setProperty('--runbar-height',runbar.getBoundingClientRect().height+'px')};
if(window.ResizeObserver&&$('.runbar'))new ResizeObserver(updatePoolPosition).observe($('.runbar'));
updatePoolPosition();
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!poolPanel.hidden&&!document.querySelector('dialog[open]'))closePoolPanel()});
syncPoolBar();
const poolRunPrevious=$('#run')?.onclick;
if($('#run'))$('#run').onclick=async function(event){
 try{
  if(saveMode!=='save'&&state){
   const pool=poolRead();
   if(pool.enabled&&pool.rotation?.enabled){
    syncPoolCount();
    const entries=pool.entries.length,rounds=pool.rotation.rounds||1,total=entries*rounds;
    if(total>poolLimit)throw Error(`轮战每方案需要 ${entries}×${rounds} = ${total} 场，超过 10000 场上限`);
    const first=Number($('#seed').value);
    if(!Number.isInteger(first)||first<0||first>0xffffffff||first+total-1>0xffffffff)throw Error('轮战种子范围超出 0–4294967295');
   }
  }
 }catch(e){toast(e.message);return}
 return poolRunPrevious?.call(this,event);
};
const poolBindPrevious=bind;
bind=function(){poolBindPrevious();syncPoolBar();if(!poolPanel.hidden)fillPoolPanel()};
