'use strict';
const poolDefaults=()=>({profile:'away-tactic-pool-v1',enabled:false,entries:[],uniform:{enabled:true,attribute_value:15}});
function poolData(){
 const pool=state.away_tactic_pool??=poolDefaults();
 pool.entries??=[];pool.uniform??={enabled:true,attribute_value:15};
 return pool;
}
const poolTotal=pool=>pool.entries.reduce((n,e)=>n+(e.weight||1),0);
async function poolSave(){
 try{state=(await api('/api/validate',clone(state))).scenario;save()}
 catch(e){toast('随机候选保存失败：'+e.message)}
 render();
}
function poolEmpty(){
 return `<div class="empty"><div class="symbol">⇄</div><h2>还没有随机候选战术</h2><p>导入本机 FMF，或在存档战术页加入联赛战术。</p></div>`;
}
function poolTable(pool,total){
 const rows=pool.entries.map((entry,index)=>{
  const weight=entry.weight||1;
  return `<tr><td><span title="${esc(entry.tactic?.tactic_name||entry.name)}">${esc(entry.name)}</span></td><td><input type="number" min="1" max="1000" step="1" value="${weight}" data-pool-weight="${index}" aria-label="权重"></td><td class="count">${total?pct(weight/total):'0%'}</td><td><button type="button" class="button small ghost" data-pool-remove="${index}">删除</button></td></tr>`;
 }).join('');
 return `<div class="table-scroll"><table class="pool-table"><thead><tr><th>战术</th><th>权重</th><th>单套概率</th><th>删除</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function randomOptionsView(){
 const pool=poolData(),total=poolTotal(pool),uniform=pool.uniform;
 return `<div class="card"><div class="card-head pool-head"><div class="save-team-controls"><h2>随机对手战术</h2><span class="tag">${pool.entries.length} 套</span><button id="random-options-close" class="button small ghost" type="button">收起设置</button></div><div class="save-team-controls"><button type="button" id="pool-import-fmf" class="button small primary">导入 FMF</button><button type="button" id="pool-import-save" class="button small">前往存档战术页面</button><input id="pool-import-file" type="file" accept=".fmf" multiple hidden></div></div><div class="card-body">${pool.entries.length?poolTable(pool,total):poolEmpty()}</div></div><div class="card"><div class="card-head"><h2>统一客队球员属性</h2></div><div class="card-body"><div class="save-team-controls"><label class="raw-toggle"><input id="pool-uniform" type="checkbox" ${uniform.enabled?'checked':''}>启用</label><label>属性值<input id="pool-uniform-value" type="number" min="1" max="20" step="1" value="${uniform.attribute_value}" ${uniform.enabled?'':'disabled'}></label></div><p class="tiny muted">开启后，每名首发在战术位置的熟练度固定为满值，其余属性统一为设定面板值。</p></div></div>`;
}
async function poolImportFiles(event){
 const files=[...event.target.files];if(!files.length)return;
 const button=$('#pool-import-fmf');if(button){button.disabled=true;button.textContent='正在导入…'}
 const failures=[];let imported=0;
 for(const file of files){
  if(!/\.fmf$/i.test(file.name)){failures.push(file.name+'：请选择战术 FMF 文件');continue}
  if(file.size>4*1024*1024){failures.push(file.name+'：文件超过 4 MB');continue}
  try{
   const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
   const result=await api('/api/pool/import-fmf',{scenario:clone(state),file_base64:btoa(binary),name:file.name.replace(/\.fmf$/i,'').trim().slice(0,80)});
   state=result.scenario;
   if(randomSelectionPending){poolData().enabled=true;randomSelectionPending=false}
   save();imported++;
  }catch(e){failures.push(file.name+'：'+e.message)}
 }
 event.target.value='';
 render();
 toast(imported?`已导入 ${imported} 套战术`+(failures.length?`，${failures.length} 个失败`:''):'没有导入成功');
 if(failures.length)setTimeout(()=>toast(failures[0]),1200);
}
function bindPool(){
 if(randomOptions.hidden)return;
 if($('#random-options-close'))$('#random-options-close').onclick=()=>{randomOptionsOpen=false;syncRandomMode()};
 if($('#pool-import-save'))$('#pool-import-save').onclick=()=>{randomOptionsOpen=false;view='library';render()};
 if($('#pool-import-fmf'))$('#pool-import-fmf').onclick=()=>$('#pool-import-file').click();
 if($('#pool-import-file'))$('#pool-import-file').onchange=poolImportFiles;
 $$('[data-pool-weight]').forEach(input=>input.onchange=()=>{
  const weight=Number(input.value),entry=poolData().entries[+input.dataset.poolWeight];
  if(!Number.isInteger(weight)||weight<1||weight>1000){toast('权重须为 1–1000 的整数');render();return}
  entry.weight=weight;poolSave();
 });
 $$('[data-pool-remove]').forEach(button=>button.onclick=()=>{
  const pool=poolData();pool.entries.splice(+button.dataset.poolRemove,1);
  if(!pool.entries.length)pool.enabled=false;
  poolSave();
 });
 if($('#pool-uniform'))$('#pool-uniform').onchange=()=>{const enabled=$('#pool-uniform').checked;poolData().uniform.enabled=enabled;if($('#pool-uniform-value'))$('#pool-uniform-value').disabled=!enabled;poolSave()};
 if($('#pool-uniform-value'))$('#pool-uniform-value').onchange=()=>{
  const value=Number($('#pool-uniform-value').value);
  if(!Number.isInteger(value)||value<1||value>20){toast('统一属性值须为 1–20 的整数');render();return}
  poolData().uniform.attribute_value=value;poolSave();
 };
}
let randomOptionsOpen=false,randomSelectionPending=false;
const randomOptions=document.createElement('section');
randomOptions.id='random-options';randomOptions.className='random-options';randomOptions.hidden=true;
randomOptions.setAttribute('aria-label','随机对手战术设置');
$('.runbar').before(randomOptions);
const randomModeLabel=document.createElement('label');randomModeLabel.className='compare-toggle';
randomModeLabel.title='开启后，每场从候选列表按权重抽取对手战术；关闭后使用当前选定的对手战术。';
randomModeLabel.innerHTML='<input id="random-mode" type="checkbox" aria-controls="random-options">随机对手战术';
$('#quick-score-mode').closest('label').after(randomModeLabel);
const randomManage=document.createElement('button');randomManage.id='random-manage';randomManage.type='button';randomManage.className='button small';randomManage.hidden=true;
randomManage.setAttribute('aria-controls','random-options');
randomModeLabel.after(randomManage);
randomManage.onclick=()=>{randomOptionsOpen=!randomOptionsOpen;syncRandomMode()};
function syncRandomMode(){
 const input=$('#random-mode');if(!input)return;
 const locked=saveMode==='save',pool=state?poolData():poolDefaults();
 if(locked)randomSelectionPending=false;
 const enabled=!locked&&(pool.enabled||randomSelectionPending);
 randomModeLabel.hidden=locked;input.disabled=locked;input.checked=enabled;
 randomManage.hidden=!enabled;randomManage.textContent=`候选战术（${pool.entries.length}）`;
 randomOptions.hidden=!enabled||!randomOptionsOpen;
 randomManage.setAttribute('aria-expanded',String(!randomOptions.hidden));
 input.setAttribute('aria-expanded',String(!randomOptions.hidden));
 if(!randomOptions.hidden){randomOptions.innerHTML=randomOptionsView();bindPool()}
}
$('#random-mode').onchange=()=>{
 const input=$('#random-mode');
 if(saveMode==='save'){input.checked=false;return}
 const pool=poolData();
 randomSelectionPending=input.checked&&!pool.entries.length;
 pool.enabled=input.checked&&pool.entries.length>0;
 randomOptionsOpen=input.checked;
 poolSave();
};
const poolBindPrevious=bind;
bind=function(){
 poolBindPrevious();syncRandomMode();
 const run=$('#run').onclick;
 $('#run').onclick=async function(event){
  if(saveMode!=='save'&&randomSelectionPending){
   randomOptionsOpen=true;syncRandomMode();toast('请先添加随机候选战术');return;
  }
  return run?.call(this,event);
 };
};
const updateRandomPosition=()=>document.documentElement.style.setProperty('--runbar-height',$('.runbar').getBoundingClientRect().height+'px');
new ResizeObserver(updateRandomPosition).observe($('.runbar'));
updateRandomPosition();
