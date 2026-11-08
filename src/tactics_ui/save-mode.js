'use strict';
let saveMode=localStorage.getItem('fm27-mode-value')||'free',saveInfo=null,saveClub=null,saveRoster=null,saveOpponents=[],saveChosen=new Set(),saveLoaded=null,saveTimer;
const freeTeamSides=editableTeamSides;
editableTeamSides=()=>saveMode==='save'?[0]:freeTeamSides();
const modePanel=document.createElement('section');modePanel.className='card save-mode-panel';
$('#engine-settings').after(modePanel);
const experimentLabel=document.createElement('label');experimentLabel.innerHTML='实验名称<input id="experiment-name" maxlength="100" placeholder="留空自动命名">';
$('#seed').closest('label').before(experimentLabel);
const executionOptions=document.createElement('details');
executionOptions.className='card save-mode-panel';
executionOptions.innerHTML=`
 <summary>战术执行力实验</summary>
 <p class="tiny muted">启用后，每场独立运行新版引擎分支。数值是人为设定的实验条件。</p>
 <div class="save-team-controls">
  <label><input id="execution-enabled" type="checkbox">启用</label>
  <label>己方<input id="execution-own" type="number" min="0" max="100" step="1" value="70" disabled></label>
  <label>对方<input id="execution-opponent" type="number" min="0" max="100" step="1" value="70" disabled></label>
 </div>`;
modePanel.after(executionOptions);
$('#execution-enabled').onchange=()=>{
 for(const id of ['execution-own','execution-opponent'])$('#'+id).disabled=!$('#execution-enabled').checked;
};
function saveModeDraft(){if(state)localStorage.setItem('fm27-mode-draft-'+saveMode,JSON.stringify(state));}
function setSaveMode(value){
 if(activeJob){toast('请先等待当前实验结束或取消');return;}
 clearTimeout(saveTimer);
 saveModeDraft();localStorage.setItem('fm27-mode-reference-'+saveMode,JSON.stringify(reference));saveMode=value;
 localStorage.setItem('fm27-mode-value',value);
 try{const draft=JSON.parse(localStorage.getItem('fm27-mode-draft-'+value));if(draft)state=draft;}catch(e){toast('模式草稿读取失败');}
 try{reference=JSON.parse(localStorage.getItem('fm27-mode-reference-'+value))||null;}catch(e){reference=null;}
 side=slot=player=0;save();render();drawSaveMode();
 if(value==='save'&&!saveInfo)pollSave();
}
function drawSaveMode(){
 const status=saveInfo?.status;
 modePanel.innerHTML=`<div class="save-mode-top"><div class="segmented"><button data-mode="free" class="${saveMode==='free'?'active':''}">自由推演</button><button data-mode="save" class="${saveMode==='save'?'active':''}">存档对战</button></div>${saveMode==='save'?'<span class="tiny muted">真实属性 · 两阶段战术 · 多对手主客场测试</span>':''}</div>${saveMode==='save'?`<div class="save-mode-body"><label>存档完整路径<input id="career-path" value="${esc(saveInfo?.source||'')}" placeholder="例如 D:\\存档\\生涯.fm"></label><button id="career-pick" class="button">选择存档…</button><button id="career-read" class="button" ${status==='reading'?'disabled':''}>读取存档</button><span class="tiny" role="status">${esc(saveInfo?.stage||'请选择 .fm 存档；战术 FMF 仍在战术板导入')}</span>${status==='complete'?`<p class="tiny muted">存档日期 ${esc(saveInfo.date)} · 构建 ${esc(saveInfo.build)} · 当前存档属性与教练偏好</p><div class="save-team-controls"><label>我的球队<select id="career-club">${saveInfo.clubs.map(c=>`<option value="${c.uid}" ${c.uid===saveClub?'selected':''}>${esc(c.name)}（${c.players}人）${saveInfo.managed.some(m=>m.club_uid===c.uid)?' · 人类经理执教':''}</option>`).join('')}</select></label>${saveRoster?`<label>存储战术<select id="career-tactic">${saveRoster.tactics.filter(t=>t.available).map(t=>`<option value="${t.index}">${esc(t.name)}</option>`).join('')}</select></label><button id="career-load" class="button primary" ${saveRoster.tactics.some(t=>t.available)?'':'disabled'}>载入战术板</button><button id="career-lineup-open" class="button">一线队／比赛名单</button>`:''}<button id="career-opponents" class="button">选择存档对手</button></div>${saveLoaded?`<p class="tiny">已载入：${esc(state?.teams[0]?.name||'')} · ${esc(saveLoaded.tactic_name)} <button id="career-restore" class="button small">恢复导入方案</button></p><p class="tiny muted">${esc(saveLoaded.notice)}</p>`:''}${saveInfo.warnings?.length?`<details><summary>解析提示（${saveInfo.warnings.length}）</summary>${saveInfo.warnings.map(w=>`<p class="tiny">${esc(w)}</p>`).join('')}</details>`:''}<p class="tiny">已选 ${saveChosen.size} 个对手方案。每队场数沿用底部场数，主客场各半；启用对照时总场数翻倍。此模式编辑主队，运行时载入所选对手的教练偏好预设。<strong id="career-total"></strong></p>`:''}</div>`:''}`;
 modePanel.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>setSaveMode(b.dataset.mode));
 if($('#career-pick'))$('#career-pick').onclick=async()=>{try{const r=await api('/api/save/pick',{});if(r.path){$('#career-path').value=r.path;$('#career-read').click();}}catch(e){toast(e.message)}};
 const readButton=$('#career-read');if(readButton)readButton.onclick=async()=>{try{const r=await api('/api/save/import',{path:$('#career-path').value});saveLoaded=null;saveRoster=null;saveChosen.clear();saveOpponents=[];saveInfo={id:r.id,status:'reading',stage:r.reused?'存档未变化，复用已解析数据':'正在读取存档',source:$('#career-path').value};if(r.reused)toast('存档未变化，已复用解析结果与对手预设');drawSaveMode();pollSave();}catch(e){toast(e.message)}};
 if($('#career-club'))$('#career-club').onchange=async e=>{saveClub=+e.target.value;saveChosen.clear();saveOpponents=[];saveLoaded=null;await readSaveClub();};
 if($('#career-load'))$('#career-load').onclick=loadSaveTeam;
 if($('#career-lineup-open'))$('#career-lineup-open').onclick=showSaveLineup;
 if($('#career-opponents'))$('#career-opponents').onclick=()=>discoverSaveOpponents();
 if($('#career-restore'))$('#career-restore').onclick=()=>{const saved=localStorage.getItem('fm27-career-original');if(saved&&confirm('恢复导入时的己方阵容与战术？当前修改会被替换。')){state.teams[0]=JSON.parse(saved);save();render();drawSaveMode();}};
 const countLabel=$('#count').closest('label');countLabel.firstChild.textContent=saveMode==='save'?'每队场数':'每方案场数';
 updateSaveTotal();
}
function updateSaveTotal(){const e=$('#career-total');if(e)e.textContent=`预计 ${saveChosen.size*Number($('#count').value)*($('#compare').checked?2:1)} 场`;}
$('#count').addEventListener('input',updateSaveTotal);$('#compare').addEventListener('change',updateSaveTotal);
async function pollSave(){clearTimeout(saveTimer);try{const value=await api('/api/save/status'+(saveInfo?.id?'?id='+saveInfo.id:''));saveInfo={...saveInfo,...value};drawSaveMode();if(value.status==='reading')saveTimer=setTimeout(pollSave,1500);else if(value.status==='complete'){saveClub=value.clubs.some(c=>c.uid===saveClub)?saveClub:(value.clubs[0]?.uid??null);if(saveClub!==null)await readSaveClub();else{saveRoster=null;drawSaveMode();toast('未找到可载入的人类经理执教球队');}}else if(value.status==='error')toast(value.stage);}catch(e){toast(e.message);}}
async function readSaveClub(){try{saveRoster=await api('/api/save/club',{id:saveInfo.id,club_uid:saveClub});saveRoster.picks=saveRoster.selections.filter(s=>!s.substitute).sort((a,b)=>a.slot-b.slot).map(s=>s.source_uid);drawSaveMode();}catch(e){toast(e.message);}}
async function loadSaveTeam(){
 try{
  if(!$('#career-tactic')?.value)throw Error('该队没有可完整解析的存储战术');
  if(!confirm('用此队的存档阵容和所选战术替换当前主队？'))return;
  const r=await api('/api/save/load',{id:saveInfo.id,club_uid:saveClub,tactic_index:Number($('#career-tactic').value),lineup:saveRoster.picks.length===11?saveRoster.picks:null,scenario:state});
  state=r.scenario;reference=clone(state);saveLoaded=r.source;
  localStorage.setItem('fm27-career-original',JSON.stringify(state.teams[0]));
  save();saveModeDraft();
  side=slot=player=0;
  view='tactics';
  render();drawSaveMode();
  $('#workspace').scrollIntoView({block:'start'});
  toast('已载入真实属性及所选两阶段战术');
 }catch(e){toast('载入失败：'+e.message);}
}
function showSaveLineup(){
 const dialog=document.createElement('dialog');dialog.className='save-dialog';
 dialog.innerHTML=`<h2>首发与完整名单</h2><p>按存储战术的11个位置顺序选择球员；最多带入宿主支持的比赛名单，其余球员保留在此供选择。</p>${Array.from({length:11},(_,i)=>`<label>位置 ${i+1}<select data-career-pick="${i}"><option value="">请选择球员</option>${saveRoster.players.map(p=>`<option value="${p.uid}" ${saveRoster.picks[i]===p.uid?'selected':''}>${esc(p.name)} · CA ${p.ca}</option>`).join('')}</select></label>`).join('')}<div class="dialog-actions"><button class="button" data-close>取消</button><button class="button primary" data-accept>保存首发选择</button></div>`;
 document.body.append(dialog);dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.querySelector('[data-accept]').onclick=()=>{const picks=[...dialog.querySelectorAll('[data-career-pick]')].map(s=>s.value===''?null:Number(s.value));if(picks.includes(null)||new Set(picks).size!==11){toast('请选择11名不同的球员');return;}saveRoster.picks=picks;dialog.close();toast('首发选择已保存，点击载入战术板应用');};dialog.onclose=()=>dialog.remove();dialog.showModal();
}
async function discoverSaveOpponents(){try{const r=await api('/api/save/opponents',{id:saveInfo.id,club_uid:saveClub});if(r.status==='error')throw Error(r.stage||'同联赛对手读取失败');if(r.status==='reading'){toast(r.stage);clearTimeout(saveTimer);saveTimer=setTimeout(discoverSaveOpponents,2500);return;}saveOpponents=r.opponents;showSaveOpponents(r);}catch(e){toast(e.message);}}
function showSaveOpponents(report){
 const dialog=document.createElement('dialog');dialog.className='save-dialog opponent-picker';
 dialog.innerHTML=`<h2>选择存档对手方案</h2><p class="tiny muted">按各队主教练的风格和主次偏好阵型匹配原装预设，完整保留预设中的球队指令、个人指令和双阶段映射。球员属性来自存档，名单按位置补齐；这是教练偏好配置，不代表当天实战战术。</p><input data-search placeholder="搜索球队"><div class="career-opponent-list">${saveOpponents.map(o=>`<label data-opponent-row="${esc(o.name)}"><input type="checkbox" data-opponent="${o.key}" ${saveChosen.has(o.key)?'checked':''}><span><b>${esc(o.name)}</b><small>${o.source_kind==='coach_preference_preset'?'教练偏好预设':o.source_kind==='saved_template'?'存档保存模板':'已保存方案'} · ${o.roster_pending?'名单按需读取':'比赛名单 '+o.match_roster_count+'人'}</small></span><button type="button" class="button small" data-preview="${o.key}">查看阵容与战术</button></label>`).join('')||'<p>未找到完整的存档对手方案。</p>'}</div><details><summary>未接入的记录（${report.failures.length}）</summary>${report.failures.map(f=>`<p class="tiny">${esc(f.member||'')}：${esc(f.error)}</p>`).join('')}</details><div class="dialog-actions"><button class="button" data-close>取消</button><button class="button primary" data-accept>使用选中方案</button></div>`;
 document.body.append(dialog);dialog.querySelectorAll('[data-preview]').forEach(b=>b.onclick=e=>{e.preventDefault();e.stopPropagation();previewSaveOpponent(b.dataset.preview);});dialog.querySelector('[data-search]').oninput=e=>dialog.querySelectorAll('[data-opponent-row]').forEach(r=>r.hidden=!r.dataset.opponentRow.toLowerCase().includes(e.target.value.toLowerCase()));dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.querySelector('[data-accept]').onclick=()=>{const chosen=[...dialog.querySelectorAll('[data-opponent]:checked')].map(e=>e.dataset.opponent),clubs=chosen.map(key=>saveOpponents.find(o=>o.key===key).club_uid);if(new Set(clubs).size!==clubs.length){toast('同一球队请选择一套方案');return;}saveChosen=new Set(chosen);dialog.close();drawSaveMode();};dialog.onclose=()=>dialog.remove();dialog.showModal();
 enhanceOpponentPicker(dialog,report);
}
function opponentSearchText(o){
 const aliases={679:'曼城 曼彻斯特城 manchester city mancity man city',680:'曼联 曼彻斯特联 manchester united manutd man utd',603:'维拉 阿斯顿维拉 aston villa',868:'巴黎 大巴黎 巴黎圣日耳曼 psg paris saint germain'};
 const clean=s=>String(s).normalize('NFKC').toLowerCase().replace(/[\s\u200b-\u200f\ufeff·._-]/g,'');
 const named=[['马德里竞技','马竞 atletico madrid atlético'],['皇家马德里','皇马 real madrid'],['托特纳姆','热刺 spurs tottenham'],['阿森纳','arsenal 枪手'],['切尔西','chelsea 蓝军'],['利物浦','liverpool 红军'],['拜仁','bayern munich'],['巴塞罗那','巴萨 barcelona'],['国际米兰','国米 inter milan'],['AC米兰','ac milan'],['尤文图斯','尤文 juventus'],['纽卡斯尔','纽卡 newcastle'],['诺丁汉森林','森林 nottingham forest']].filter(([name])=>o.name.includes(name)).map(([,text])=>text);
 return clean([o.name,o.member,aliases[o.club_uid]||'',o.search_terms||'',...named].join(' '));
}
function enhanceOpponentPicker(dialog,report){
 const rules=dialog.querySelector('p'),details=document.createElement('details');details.className='opponent-rules';details.innerHTML='<summary>数据来源与名单规则</summary>';rules.before(details);details.append(rules);
 const missing=report.unrecovered_clubs||[];if(missing.length){const pending=document.createElement('details');pending.innerHTML='<summary>同联赛尚未接入（'+missing.length+'队）</summary>'+missing.map(c=>'<p class="tiny">'+esc(c.name)+'：'+esc(c.reason)+'</p>').join('');dialog.querySelector('.dialog-actions').before(pending);}
 const list=dialog.querySelector('.career-opponent-list'),requested=report.requested_teams||[];
 list.querySelectorAll('[data-opponent-row]').forEach(row=>{const key=row.querySelector('[data-opponent]').dataset.opponent;row.dataset.clubUid=saveOpponents.find(o=>o.key===key).club_uid;});
 for(const team of requested.filter(t=>!t.available)){const row=document.createElement('label');row.dataset.opponentRow=team.name;row.dataset.clubUid=team.club_uid;row.innerHTML=`<input type="checkbox" disabled aria-label="${esc(team.name)}方案待恢复"><span><b>${esc(team.name)}</b><small>方案待恢复 · ${esc(team.reason)}</small></span>`;list.append(row);}
 const search=dialog.querySelector('[data-search]');search.type='search';search.placeholder='搜索同联赛球队';search.setAttribute('aria-label','搜索同联赛对手');
 const controls=document.createElement('div');controls.className='save-team-controls';controls.innerHTML=`<label>对手范围<select data-scope aria-label="对手范围"><option value="league" selected>同联赛（${report.same_league_available||0}/${report.same_league_clubs||0}可用）</option><option value="all">全部可用球队（${saveOpponents.length}）</option></select></label><button type="button" class="button small" data-select-visible>选中当前可用球队</button>`;search.before(controls);
 const scope=controls.querySelector('[data-scope]'),policy=document.createElement('p');policy.className='tiny muted';policy.textContent='仅列出当前存档的同联赛球队。战术按现任主教练偏好匹配原装预设；不读取历史比赛方案。球员属性来自当前存档，名单按位置近似选取。';controls.before(policy);
 const count=document.createElement('p');count.className='tiny opponent-match-count';search.after(count);
 const empty=document.createElement('p');empty.className='opponent-no-match';empty.hidden=true;empty.textContent='没有匹配的可用存档方案。搜索仅限通过完整战术与球员校验的球队。';dialog.querySelector('.career-opponent-list').after(empty);
 const normalize=s=>String(s).normalize('NFKC').toLowerCase().replace(/[\s\u200b-\u200f\ufeff·._-]/g,'');
 const update=()=>{let ready=0,pending=0;const q=normalize(search.value);dialog.querySelectorAll('[data-opponent-row]').forEach(row=>{const uid=+row.dataset.clubUid,o=saveOpponents.find(o=>o.club_uid===uid)||requested.find(o=>o.club_uid===uid);const inScope=scope.value==='all'?o.available!==false:o.same_league;row.hidden=!inScope||(!!q&&!opponentSearchText(o).includes(q));row.style.display=row.hidden?'none':'';if(!row.hidden){if(o.available===false)pending++;else ready++;}});count.textContent=`显示 ${ready} 队可用${pending?' · '+pending+' 队暂不可用':''} · 已选 ${dialog.querySelectorAll('[data-opponent]:checked').length} 队`;empty.hidden=ready+pending>0;};
 scope.onchange=update;controls.querySelector('[data-select-visible]').onclick=()=>{list.querySelectorAll('[data-opponent-row]').forEach(row=>{const checkbox=row.querySelector('[data-opponent]');if(!row.hidden&&checkbox)checkbox.checked=true;});update();};
 search.oninput=update;dialog.querySelectorAll('[data-opponent]').forEach(c=>c.addEventListener('change',update));update();
}
const saveApiPrevious=api;
function opponentPreviewBoard(t,p){
 const ps=positions(),rs=roles();
 return `<section class="preview-board"><div class="board-title"><h3>${p?'无球阶段':'有球阶段'}</h3><small>进攻方向 ↑</small></div><div class="pitch preview-pitch"><div class="pitch-lines"><div class="halfway"></div><div class="centre-circle"></div><div class="box top"></div><div class="box bottom"></div><div class="six-yard top"></div><div class="six-yard bottom"></div></div>${t.phases[p].map((c,i)=>{const player=t.players[t.lineup[i]],pos=ps[c.position];return `<button type="button" class="pitch-slot preview-player" data-preview-phase="${p}" data-preview-slot="${i}" style="left:${pos.x}%;top:${pos.y}%" title="${esc(player.name+' · '+(rs[c.role]?.label||c.role))}" aria-label="${p?'无球':'有球'} · ${esc(player.name)} · ${esc(rs[c.role]?.label||c.role)}"><span class="shirt">${i+1}</span><span class="slot-name">${esc(player.name)}</span><span class="slot-role">${esc(rs[c.role]?.label||c.role)}</span></button>`;}).join('')}</div></section>`;
}
function opponentPreviewPlayer(t,index,p=null,slot=null){
 const player=t.players[index],cell=p===null?null:t.phases[p][slot],rs=roles();
 const pis=cell?`<div class="preview-instructions">${catalog.player_instructions.filter(g=>g.phase===p).map(g=>`<div><span>${esc(g.label||g.name)}</span><b>${esc(g.options.find(o=>o.id===cell.instructions[g.id])?.label||'标准')}</b></div>`).join('')}</div>`:'';
 return `<h3>${esc(player.name)}${cell?' · '+(p?'无球':'有球')+' · '+esc(cell.position)+' · '+esc(rs[cell.role]?.label||cell.role):' · 推演替补'}</h3>${pis}<details ${cell?'':'open'}><summary>查看当前存档属性（${player.attributes.length} 项）</summary><div class="preview-attributes">${player.attributes.map((v,a)=>`<span>${esc(catalog.attributes[a].label||catalog.attributes[a].name)} <b>${a<15?v:Number((v/5).toFixed(1))}</b></span>`).join('')}</div></details>`;
}
async function previewSaveOpponent(key){
 try{
  const r=await api('/api/save/preview',{id:saveInfo.id,club_uid:saveClub,key,scenario:state});
  const t=r.team,rs=roles(),dialog=document.createElement('dialog');dialog.className='save-dialog opponent-preview';
  const generated=r.source.source_kind==='original_ai_generation'&&!r.source.native_preview;
  const phases=generated?'':`<div class="preview-dual-boards">${opponentPreviewBoard(t,0)}${opponentPreviewBoard(t,1)}</div><p class="tiny muted">两阶段共用同一套推演首发，按位置和能力近似选取；点击球员查看该阶段的个人指令与当前存档属性。</p><section class="preview-player-detail" data-preview-detail aria-live="polite"></section>`;
  const instructions=generated?'':catalog.team_instructions.map(g=>`<p class="tiny">${esc(g.label||g.name)}：${esc(g.options.find(o=>o.id===t.instructions[g.id])?.label||'标准')}</p>`).join('');
  const count=t.roster_size??t.players.length,bench=t.players.slice(0,count).map((p,i)=>({p,i})).filter(({i})=>!t.lineup.includes(i));
  dialog.innerHTML=`<h2>${esc(t.name)} · 双阶段战术预览</h2><p>推演名单 ${count} 人 · 属性来自当前存档</p><p class="tiny">${esc(r.source.source)}</p>${generated?'<p>战术将在比赛准备时由原版AI生成，完整球队指令、个人指令和双阶段映射记录在每场原生回执中。</p>':phases+'<details class="preview-team-instructions"><summary>全部球队指令</summary>'+instructions+'</details>'}<details><summary>推演替补（${bench.length} 人）</summary><div class="preview-bench">${bench.map(({p,i})=>`<button type="button" class="button small" data-preview-bench="${i}">${esc(p.name)}</button>`).join('')||'<p>未选择替补</p>'}</div></details><div class="dialog-actions"><button class="button" data-close>关闭预览</button></div>`;
  const showPlayer=(index,p=null,i=null)=>{const detail=dialog.querySelector('[data-preview-detail]');if(detail)detail.innerHTML=opponentPreviewPlayer(t,index,p,i);dialog.querySelectorAll('[data-preview-slot]').forEach(b=>b.classList.toggle('selected',p!==null&&+b.dataset.previewSlot===i));};
  dialog.querySelectorAll('[data-preview-slot]').forEach(b=>b.onclick=()=>showPlayer(t.lineup[+b.dataset.previewSlot],+b.dataset.previewPhase,+b.dataset.previewSlot));
  dialog.querySelectorAll('[data-preview-bench]').forEach(b=>b.onclick=()=>{showPlayer(+b.dataset.previewBench);dialog.querySelector('[data-preview-detail]')?.scrollIntoView({block:'nearest',behavior:'smooth'});});
  if(!generated)showPlayer(t.lineup[0],0,0);
  document.body.append(dialog);dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.showModal();
 }catch(e){toast(e.message);}
}
api=async function(url,data){
 if(url==='/api/run'&&data){
  data={...data,name:$('#experiment-name').value.trim()||undefined};
  delete data.scenario.experimental_execution;
  if(data.reference)delete data.reference.experimental_execution;
  if($('#execution-enabled').checked){
   const values=['execution-own','execution-opponent'].map(id=>{
    const input=$('#'+id);
    if(input.value===''||!input.checkValidity())throw Error('战术执行力须为 0–100 的整数');
    return Number(input.value);
   });
   data.scenario={...data.scenario,experimental_execution:values};
   if(data.reference)data.reference={...data.reference,experimental_execution:values};
  }
  if(saveMode==='save'){
   delete data.scenario.away_tactic_pool;if(data.reference)delete data.reference.away_tactic_pool;
   if(!saveLoaded||saveLoaded.club_uid!==saveClub)throw Error('请先将所选球队载入战术板');
   if(!saveChosen.size)throw Error('请至少选择一个存档对手');
   url='/api/save/run';data={...data,save_id:saveInfo.id,club_uid:saveClub,count:Number($('#count').value),first_seed:Number($('#seed').value),opponents:saveOpponents.filter(o=>saveChosen.has(o.key)).map(o=>({key:o.key}))};
  }
 }
 return saveApiPrevious(url,data);
};
const saveResultsPrevious=resultsView;
resultsView=function(){
 let html=saveResultsPrevious();if(!selectedJob)return html;
 const j=selectedJob;
 if(j.experimental_execution){
  const row=j.runs[j.detailIndex??Math.max(0,j.runs.length-1)];
  const variant=row?.variant??Object.keys(j.experimental_execution)[0];
  const values=j.experimental_execution[variant];
  if(values)html=`<p class="card save-mode-panel">战术执行力实验 · ${esc(j.team_names[variant][0])} ${values[0]} / ${esc(j.team_names[variant][1])} ${values[1]}${row?.experimental_execution?' · 原生采样已核对':''}</p>`+html;
 }
 if(j.experiment_type==='save_opponents'){
  html=html.replaceAll('主队视角','己方视角').replaceAll('主队胜率','己方胜率');
  const rows=Object.entries(j.opponent_metrics||{}).flatMap(([key,groups])=>Object.entries(groups).filter(([g,m])=>m).map(([g,m])=>{const name=Object.values(j.schedule).find(v=>v.opponent_key===key)?.opponent;return `<tr><td>${esc(name)} · ${g==='A'?'对照':'本次'}</td><td>${m.n}</td><td>${pct(m.win_rate)}</td><td>${pct(m.possession)}</td><td>${fmt(m.xg)} / ${fmt(m.xga)}</td><td>${fmt(m.shots)}</td><td>${pct(m.pass_completion)}</td></tr>`;}));
  html=`<section class="card"><div class="card-head"><h3>逐对手表现 · 己方视角</h3></div><div class="table-scroll"><table><thead><tr><th>对手／方案</th><th>场数</th><th>胜率</th><th>控球</th><th>xG / xGA</th><th>射门</th><th>传球成功</th></tr></thead><tbody>${rows.join('')}</tbody></table></div></section>`+html;
 }
 const busy=['queued','running'].includes(j.status);
 return `<div class="card experiment-heading"><h2>${esc(j.name||'实验 '+j.id)}</h2><button class="button small" id="rename-experiment">重命名</button><button class="button small" id="delete-experiment" ${busy?'disabled title="请等待实验结束或取消后再删除"':''}>删除实验</button><label>查找实验<input id="find-experiment" placeholder="按名称搜索"></label></div>${html}`;
};
async function deleteExperiment(button){
 const {id,name}=selectedJob;
 if(!confirm(`永久删除「${name||'实验 '+id}」及其本地结果和日志？`))return;
 button.disabled=true;
 try{
  await api('/api/jobs/delete',{id});
 }catch(e){
  button.disabled=false;
  toast(e.message);
  return;
 }
 history=history.filter(job=>job.id!==id);
 if(polledJob?.id===id)polledJob=null;
 if(selectedJob?.id===id){
  selectedJob=null;
  const next=history[0];
  if(next){
   try{
    const job=await api('/api/jobs/'+next.id);
    if(!selectedJob)selectedJob=job;
   }catch(e){toast(e.message)}
  }
 }
 render();
 toast('实验已删除');
}
const saveBindPrevious=bind;
bind=function(){saveBindPrevious();
 if($('#lineup-player'))[...$('#lineup-player').options].forEach(o=>o.disabled=Number(o.value)>=team().roster_size);
 if($('#sp-strategy')&&view==='setpieces'){const select=$('#sp-strategy'),value=spCurrent().strategy;if(![...select.options].some(o=>+o.value===value)){select.add(new Option('原版存储策略（代码 '+value+'）',value));select.value=value;}}
 $$('[data-job]').forEach(b=>{const h=history.find(h=>h.id===b.dataset.job);if(h){b.textContent=(h.name||'实验 '+h.id)+' · '+h.completed+'/'+h.total;b.title=new Date(h.created*1000).toLocaleString();}});
 if($('#rename-experiment'))$('#rename-experiment').onclick=async()=>{const name=prompt('实验名称（1–100字）',selectedJob.name||'');if(name===null)return;try{const r=await api('/api/jobs/rename',{id:selectedJob.id,name});selectedJob.name=r.name;const h=history.find(h=>h.id===r.id);if(h)h.name=r.name;if(polledJob?.id===r.id)polledJob.name=r.name;render();}catch(e){toast(e.message)}};
 if($('#delete-experiment'))$('#delete-experiment').onclick=e=>deleteExperiment(e.currentTarget);
 if($('#find-experiment'))$('#find-experiment').oninput=e=>$$('[data-job]').forEach(b=>b.hidden=!b.textContent.toLowerCase().includes(e.target.value.toLowerCase()));
};
drawSaveMode();
window.addEventListener('pagehide',()=>{saveModeDraft();localStorage.setItem('fm27-career-context',JSON.stringify({id:saveInfo?.id,club:saveClub,loaded:saveLoaded,opponents:saveOpponents,chosen:[...saveChosen]}));});
if(saveMode==='save'){
 try{const context=JSON.parse(localStorage.getItem('fm27-career-context'));if(context?.id){saveInfo={id:context.id};saveClub=context.club;saveLoaded=context.loaded;saveOpponents=context.opponents||[];saveChosen=new Set(context.chosen||[]);}}catch(e){}
 pollSave();
}
