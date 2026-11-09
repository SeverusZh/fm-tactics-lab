'use strict';
const SP=()=>catalog.setpieces,spTeam=()=>team().setpieces;
let spTab='routines',spType=5,spVariant=0,spRole=4;
const spCurrent=()=>spTeam().routines[spType][spVariant];
const spDefinition=()=>SP().types.find(t=>t.id===spType);
function spStrategyOptions(def,value){
 const options=SP()[def.strategy_kind];
 return options.some(o=>o.id===value)?options:[...options,{id:value,label:`存档原始策略（${value}）`}];
}
const spLabel=g=>SP().categories.find(c=>c.id===g).label;
const spOptions=g=>SP()[g<4?'defend':'attack'].filter(o=>SP().allowed[g].includes(o.id));
function spNavigation(){return `<div class="sp-navigation segmented">${[['routines','套路与球员任务'],['priorities','角色球员优先级'],['throws','界外球策略'],['takers','主罚人和队长']].map(([id,label])=>`<button data-sp-tab="${id}" class="${spTab===id?'active':''}">${label}</button>`).join('')}</div>`}
function spRoutines(){
 const r=spCurrent(),def=spDefinition(),list=spTeam().routines[spType],count=r.groups.reduce((n,g)=>n+g.length,0),needed=spType<5?10:9;
 return `<div class="card"><div class="card-head"><div><h2>${side===0?'主队':'客队'} · ${esc(team().name)} · ${esc(def.label)}</h2><div class="subtitle">当前套路：${esc(r.name)} · 导入只替换此球队、此情形下的本套定位球</div></div><span class="tag">${count} / ${needed} 项任务</span></div><div class="card-body"><div class="sp-selector">${field('比赛情形',select(SP().types,spType,'id="sp-type"'))}${field('当前套路',select(list.map((x,i)=>({id:i,label:x.name})),spVariant,'id="sp-variant"'))}<div class="sp-actions"><button class="button small" id="sp-copy" ${list.length===3?'disabled':''}>复制为新套路</button><button class="button small ghost" id="sp-delete" ${list.length===1?'disabled':''}>删除本套</button><button class="button small ghost" id="sp-reset">恢复此情形样本</button></div></div><div class="sp-selector">${field('套路名称',`<input id="sp-name" maxlength="64" value="${esc(r.name)}">`)}${field('使用频率',select(SP().frequencies,r.frequency,'id="sp-frequency"'))}${def.strategy_kind?field(def.strategy_kind==='corner_target'?'发球目标':def.strategy_kind==='defensive_line'?'防守线策略':'进攻投入',select(spStrategyOptions(def,r.strategy),r.strategy,'id="sp-strategy"')):''}${def.swing?field('旋转方向',select(SP().swing,r.swing,'id="sp-swing"')):''}</div><p class="notice">每种情形最多三套，按原生权重2／5／8抽取；它们不是固定百分比。下方顺序决定角色分配的先后，球员再执行该组中的任务。${count!==needed?`<strong> 当前少分配${needed-count}项，补足后才能运行。</strong>`:''}</p></div></div>${r.priority.map((g,rank)=>`<div class="card"><div class="card-head"><div><h2>${rank+1}. ${esc(spLabel(g))}</h2><div class="subtitle">${r.groups[g].length} 名球员 · ${g<4?'防守':'进攻'}定位球角色</div></div><div><button class="button small" data-sp-priority="${rank}" data-delta="-1" ${rank?'':'disabled'}>↑</button><button class="button small" data-sp-priority="${rank}" data-delta="1" ${rank===r.priority.length-1?'disabled':''}>↓</button></div></div><div class="card-body">${r.groups[g].map((task,j)=>`<div class="sp-task"><span class="sp-task-number">${j+1}</span>${field('主要任务',select(spOptions(g),task,`data-sp-task="${j}" data-group="${g}"`))}${field('备用任务',select([{id:0,label:'无备用任务'},...SP()[g<4?'defend':'attack'].filter(o=>o.id)],r.backups[g][j],`data-sp-backup="${j}" data-group="${g}"`))}${field('改派至角色',select(r.priority.map(id=>({id,label:spLabel(id)})),g,`data-sp-transfer="${j}" data-group="${g}"`))}<div class="sp-actions"><button class="button small" data-sp-move="${j}" data-group="${g}" data-delta="-1" ${j?'':'disabled'}>↑</button><button class="button small" data-sp-move="${j}" data-group="${g}" data-delta="1" ${j===r.groups[g].length-1?'disabled':''}>↓</button><button class="button small ghost" data-sp-remove="${j}" data-group="${g}">移除</button></div></div>`).join('')||'<p class="muted">此组暂无任务</p>'}<div class="sp-add">${select([{id:'',label:'添加任务…'},...spOptions(g)],'',`data-sp-add="${g}" ${count>=needed?'disabled':''}`)}<span class="muted tiny">调整角色人数时先移除旧任务，再添加到目标组</span></div></div></div>`).join('')}`;
}
function spPriorityView(){
 const t=team(),list=spTeam().role_priorities[spRole];
 return `<div class="card"><div class="card-head"><div><h2>定位球角色球员优先级</h2><div class="subtitle">任务分给哪名球员，由该类候选顺序与原生可用性判断决定</div></div></div><div class="card-body">${field('角色类别',select(SP().categories,spRole,'id="sp-role"'))}<p class="notice">空名单使用原生能力评分。原生分配仍会排除不在场、已承担前序角色或正在主罚的球员。</p>${list.map((p,i)=>`<div class="captain-row"><span>${i+1}</span><strong>${esc(t.players[p].name)}</strong><span class="muted tiny">${t.lineup.includes(p)?'首发':'替补'}</span><button class="button small" data-sp-player-move="${i}" data-delta="-1" ${i?'':'disabled'}>↑</button><button class="button small" data-sp-player-move="${i}" data-delta="1" ${i===list.length-1?'disabled':''}>↓</button><button class="button small ghost" data-sp-player-remove="${i}">移除</button></div>`).join('')||'<p class="muted">按原生能力评分自动分配</p>'}<div class="captain-add">${select([{id:'',label:'加入候选球员…'},...t.players.map((p,i)=>({id:i,label:p.name})).filter(p=>!list.includes(p.id))],'','id="sp-player-add"')}<button class="button small ghost" id="sp-player-clear">恢复自动分配</button></div></div></div>`;
}
function spThrows(){return `<div class="card"><div class="card-head"><h2>界外球策略</h2></div><div class="card-body"><div class="sp-selector">${['后场','中场','前场'].map((label,i)=>field(label,select(i===2?[{id:0,label:'短距离界外球'},{id:1,label:'长距离界外球'}]:[{id:0,label:'保持球权'},{id:1,label:'沿边线推进'}],spTeam().throw_styles[i],`data-sp-throw="${i}"`))).join('')}</div><p class="notice">前场界外球的接应和进攻跑动在“进攻界外球”套路中编辑。这里改变原生策略，实际掷球仍受主罚人能力、场上空间和比赛状态影响。</p></div></div>`}
const spOldView=setPiecesView;setPiecesView=function(){
 spVariant=Math.min(spVariant,spTeam().routines[spType].length-1);
 if(spTab==='takers')return spOldView().replace('<div class="card">',spNavigation()+'<div class="card">').replace(/<p class="notice">本场使用样本原版定位球套路。[\s\S]*?<\/p>/,'');
 const content=spTab==='routines'?spRoutines().replace('<div class="sp-actions">','<div class="sp-actions"><button class="button small" id="sp-export-fmf">导出本套 FMF</button><button class="button small" id="sp-export">保存 JSON</button><button class="button small" id="sp-import">导入本定位球 FMF / JSON</button><button class="button primary small" id="sp-test">单独测试本套</button><label class="tiny">发球后窗口 <select id="sp-window"><option value="15">15 秒</option><option value="30" selected>30 秒</option><option value="60">60 秒</option></select></label><input id="sp-file" type="file" accept=".fmf,.json,application/json" hidden>'):spTab==='priorities'?spPriorityView():spThrows();
 return `${toolbar()}${spNavigation()}${content}`;
};
const spOldBind=bind;bind=function(){spOldBind();if(view!=='setpieces')return;
 const done=()=>{save();render()};
 $$('[data-sp-tab]').forEach(b=>b.onclick=()=>{spTab=b.dataset.spTab;render()});
 if($('#sp-type'))$('#sp-type').onchange=e=>{spType=+e.target.value;spVariant=0;render()};
 if($('#sp-variant'))$('#sp-variant').onchange=e=>{spVariant=+e.target.value;render()};
 if($('#sp-copy'))$('#sp-copy').onclick=()=>{const list=spTeam().routines[spType];if(list.length<3){const copy=clone(spCurrent());copy.name+=' 副本';list.push(copy);spVariant=list.length-1;done()}};
 if($('#sp-delete'))$('#sp-delete').onclick=()=>{const list=spTeam().routines[spType];if(list.length>1){list.splice(spVariant,1);spVariant=Math.min(spVariant,list.length-1);done()}};
 if($('#sp-reset'))$('#sp-reset').onclick=()=>{spTeam().routines[spType]=clone(defaults.teams[side].setpieces.routines[spType]);spVariant=0;done()};
 if($('#sp-export'))$('#sp-export').onclick=()=>download(`fm27-routine-${spType}.json`,{schema:'fm27-setpiece-routine-v1',type:spType,routine:spCurrent()});
 if($('#sp-test'))$('#sp-test').onclick=runSetpieceEpisode;
 if($('#sp-export-fmf'))$('#sp-export-fmf').onclick=async()=>{const button=$('#sp-export-fmf');try{button.disabled=true;button.textContent='写入并核验…';const result=await api('/api/export-setpiece',{side,scenario:state,type:spType,variant:spVariant});downloadBinary(result);toast(result.report.notice);}catch(e){toast('定位球导出失败：'+e.message)}finally{button.disabled=false;button.textContent='导出本套 FMF';}};
 if($('#sp-import'))$('#sp-import').onclick=()=>$('#sp-file').click();
 if($('#sp-file'))$('#sp-file').onchange=async e=>{try{
  const file=e.target.files[0];if(!file)return;if(file.size>4*1024*1024)throw Error('套路文件过大');if(/\.fmf$/i.test(file.name)){const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));const result=await api('/api/import-fmf',{side,scenario:state,setpiece_target:{type:spType,variant:spVariant},file_base64:btoa(binary)});state=result.scenario;done();toast(result.report.notice);return;}const data=JSON.parse(await file.text());
  if(data.schema!=='fm27-setpiece-routine-v1'||data.type!==spType)throw Error('请选择与当前比赛情形一致的本工具套路JSON');
  const candidate=clone(state);candidate.teams[side].setpieces.routines[spType][spVariant]=data.routine;
  state=(await api('/api/validate',candidate)).scenario;done();toast('套路已导入并通过校验');
 }catch(err){toast('导入失败：'+err.message)}finally{e.target.value=''}};
 for(const key of ['name','frequency','strategy','swing'])if($(`#sp-${key}`))$(`#sp-${key}`).onchange=e=>{spCurrent()[key]=key==='name'?e.target.value:+e.target.value;done()};
 $$('[data-sp-task]').forEach(e=>e.onchange=()=>{const g=+e.dataset.group,j=+e.dataset.spTask,r=spCurrent();r.groups[g][j]=+e.value;if(+e.value===15&&!r.backups[g][j])r.backups[g][j]=2;done()});
 $$('[data-sp-backup]').forEach(e=>e.onchange=()=>{spCurrent().backups[e.dataset.group][e.dataset.spBackup]=+e.value;done()});
 $$('[data-sp-transfer]').forEach(e=>e.onchange=()=>{
  const from=+e.dataset.group,to=+e.value,j=+e.dataset.spTransfer,r=spCurrent();if(from===to)return;
  const original=r.groups[from][j],fallback=[1,2,6,5,6,2,10,5][to],task=SP().allowed[to].includes(original)?original:fallback;
  const backup=task===original?r.backups[from][j]:task===15?2:0;
  r.groups[from].splice(j,1);r.backups[from].splice(j,1);r.groups[to].push(task);r.backups[to].push(backup);done();
 });
 $$('[data-sp-add]').forEach(e=>e.onchange=()=>{if(e.value==='')return;const g=+e.dataset.spAdd,r=spCurrent();r.groups[g].push(+e.value);r.backups[g].push(+e.value===15?2:0);done()});
 $$('[data-sp-remove]').forEach(e=>e.onclick=()=>{const g=+e.dataset.group,j=+e.dataset.spRemove,r=spCurrent();r.groups[g].splice(j,1);r.backups[g].splice(j,1);done()});
 $$('[data-sp-move]').forEach(e=>e.onclick=()=>{const g=+e.dataset.group,j=+e.dataset.spMove,k=j+(+e.dataset.delta),r=spCurrent();for(const list of [r.groups[g],r.backups[g]])[list[j],list[k]]=[list[k],list[j]];done()});
 $$('[data-sp-priority]').forEach(e=>e.onclick=()=>{const a=spCurrent().priority,i=+e.dataset.spPriority,j=i+(+e.dataset.delta);[a[i],a[j]]=[a[j],a[i]];done()});
 if($('#sp-role'))$('#sp-role').onchange=e=>{spRole=+e.target.value;render()};
 if($('#sp-player-add'))$('#sp-player-add').onchange=e=>{if(e.target.value!==''){spTeam().role_priorities[spRole].push(+e.target.value);done()}};
 if($('#sp-player-clear'))$('#sp-player-clear').onclick=()=>{spTeam().role_priorities[spRole]=[];done()};
 $$('[data-sp-player-remove]').forEach(e=>e.onclick=()=>{spTeam().role_priorities[spRole].splice(+e.dataset.spPlayerRemove,1);done()});
 $$('[data-sp-player-move]').forEach(e=>e.onclick=()=>{const a=spTeam().role_priorities[spRole],i=+e.dataset.spPlayerMove,j=i+(+e.dataset.delta);[a[i],a[j]]=[a[j],a[i]];done()});
 $$('[data-sp-throw]').forEach(e=>e.onchange=()=>{spTeam().throw_styles[e.dataset.spThrow]=+e.value;done()});
};
