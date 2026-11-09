'use strict';
// Desktop-only presentation. The scenario schema and native position masks stay
// the same as the verified editor. Drops snap to engine-supported positions.
const desktopPositionNames={GK:'门将',DR:'右后卫',DL:'左后卫',DC:'中后卫',DCR:'右中卫',DCL:'左中卫',WBR:'右翼卫',WBL:'左翼卫',DMC:'后腰',DMR:'右后腰',DML:'左后腰',MR:'右中场',ML:'左中场',MC:'中场',MCR:'右中场',MCL:'左中场',AMR:'右边锋',AML:'左边锋',AMC:'前腰',AMCR:'右前腰',AMCL:'左前腰',ST:'中锋',STR:'右前锋',STL:'左前锋'};
function desktopIcon(kind='move'){
 const paths=kind==='shoot'?'<path d="M18 72L77 22M62 22h15v15"/><rect x="58" y="9" width="34" height="20"/>':kind==='width'?'<path d="M12 45h76M12 45l12-9m-12 9l12 9M88 45l-12-9m12 9l-12 9"/>':kind==='defend'?'<path d="M24 16h52v32c0 18-26 32-26 32S24 66 24 48Z"/><path d="M33 48h34M50 32v32"/>':'<path d="M21 72L50 20l29 52M50 20l-9 8m9-8l9 8M50 50v29"/><circle cx="21" cy="72" r="5"/><circle cx="79" cy="72" r="5"/>';
 return `<svg viewBox="0 0 100 90" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">${paths}</svg>`;
}
function desktopTile(g,value,attribute){
 const text=(g.name||'')+' '+(g.label||'');const kind=/Width|宽度/.test(text)?'width':/Shoot|Shots|射门/.test(text)?'shoot':/Press|Tack|Mark|Defen|逼抢|盯防|抢断/.test(text)?'defend':'move';
 return `<label class="instruction-tile"><span class="tile-title">${esc(g.label||g.name)}</span><span class="tile-drawing">${desktopIcon(kind)}</span>${select(g.options,value,`${attribute} aria-label="${esc(g.label||g.name)}"`)}</label>`;
}
teamInstructions=function(){
 const groups=catalog.team_instructions.filter(g=>g.possession_phase===phase);
 const categories=phase?[[4,'防守组织与转换'],[5,'传中防守'],[7,'限制门将出球'],[10,'逼抢方向']]:[[0,'整体进攻'],[1,'后场组织'],[2,'接应方式'],[3,'进攻三区'],[8,'支援跑动'],[9,'盘带'],[11,'推进方向'],[12,'门将分配']];
 return categories.map(([id,title])=>{const list=groups.filter(g=>g.phase===id);return list.length?`<div class="section-label">${title}</div><div class="instruction-grid fm-card-grid">${list.map(g=>desktopTile(g,team().instructions[g.id],`data-ti="${g.id}"`)).join('')}</div>`:''}).join('');
};
function desktopBoard(p){
 const ps=positions(),rs=roles();return `<section class="phase-board ${p===phase?'active-phase':''}" data-board="${p}"><button class="board-title" data-phase="${p}"><span class="phase-dot"></span>${p?'无球阶段':'有球阶段'}<small>${p===phase?'正在编辑':'点击切换'}</small></button><div class="pitch desktop-pitch" data-pitch="${p}" aria-label="${p?'无球':'有球'}战术板"><div class="pitch-lines"><div class="halfway"></div><div class="centre-circle"></div><div class="box top"></div><div class="box bottom"></div><div class="six-yard top"></div><div class="six-yard bottom"></div></div>${catalog.positions.map(pos=>`<span class="drop-position" data-position="${pos.id}" style="left:${pos.x}%;top:${pos.y}%">${pos.id}</span>`).join('')}${team().phases[p].map((c,i)=>{const pos=ps[c.position],name=team().players[team().lineup[i]].name;return `<button class="pitch-slot ${p===phase&&i===slot?'selected':''}" data-board-slot="${i}" data-board-phase="${p}" style="left:${pos.x}%;top:${pos.y}%" aria-label="${p?'无球':'有球'} ${name} ${c.position}，拖动或用方向键换位" title="${esc(name+' · '+(rs[c.role]?.label||c.role))}"><span class="shirt">${i+1}</span><span class="slot-name">${esc(name)}</span><span class="slot-role">${esc(c.position)}</span></button>`}).join('')}</div></section>`;
}
tacticsView=function(){
 const t=team(),c=current();return `${toolbar()}<div class="editor-grid desktop-editor"><section class="card formation-card"><div class="card-head"><div><h2>双阶段战术板</h2><div class="subtitle">拖动球衣调整位置 · 有球／无球分别设置</div></div><span class="tag">进攻方向 ↑</span></div><div class="preset-row">${select([{id:'',label:`${phase?'无球':'有球'}阶段：选择阵型…`},...Object.keys(PRESETS).map(id=>({id,label:id}))],'','id="formation"')}<button id="auto-lineup" class="button small">按位置选人</button></div><div class="dual-boards">${desktopBoard(0)}${desktopBoard(1)}</div><p class="drag-help">松开后吸附到原版支持的位置；落到已占用位置时交换球员，角色和指令留在原位置。两阶段共用同一套首发。</p><div class="compact-lineup">${t.lineup.map((p,i)=>`<button class="${i===slot?'active':''}" data-slot="${i}"><b>${i+1}</b><span>${esc(t.players[p].name)}</span><small>${esc(t.phases[phase][i].position)}</small></button>`).join('')}</div></section><section class="instruction-panel"><div class="phase-editor-heading">${phaseControls()}<span>${phase?'无球阶段':'有球阶段'}配置</span></div><div class="segmented editor-tabs"><button data-editor="team" class="${teamTab==='team'?'active':''}">球队指令</button><button data-editor="personal" class="${teamTab==='personal'?'active':''}">角色与球员指令</button></div><div class="card" ${teamTab==='team'?'':'hidden'}><div class="card-head"><div><input id="team-name" class="team-title" value="${esc(t.name)}" aria-label="球队名称"><div class="subtitle">${phase?'无球':'有球'}阶段球队指令</div></div></div><div class="card-body">${field('比赛心态（全队共用）',select(catalog.mentalities,t.mentality,'id="mentality"'))}${teamInstructions()}</div></div><div class="card inspector" ${teamTab==='personal'?'':'hidden'}><div class="card-head"><div><h2>${esc(t.players[t.lineup[slot]].name)}</h2><div class="subtitle">${phase?'无球':'有球'} · ${esc(desktopPositionNames[c.position])}</div></div><button id="edit-player" class="button small">球员属性 ↗</button></div><div class="card-body"><div class="inspector-top">${field('首发球员',select(t.players.map((p,i)=>({id:i,label:p.name})),t.lineup[slot],'id="lineup-player"'))}${field('位置',select(catalog.positions.map(p=>({id:p.id,label:`${desktopPositionNames[p.id]} · ${p.id}`})),c.position,'id="slot-position"'))}${field('角色',select(catalog.roles.filter(r=>r.phase===phase),c.role,'id="slot-role"'))}</div><div class="group-heading"><h3>球员指令</h3><span class="tiny muted"></span></div><div class="instruction-grid fm-card-grid">${catalog.player_instructions.map(g=>desktopTile(g,c.instructions[g.id],`data-pi="${g.id}"`)).join('')}</div><div id="mark-target">${markTarget()}</div><p class="instructions-note"></p></div></div></section></div>`;
};
function desktopMove(p,i,target){
 const cells=team().phases[p],cell=cells[i];if(!positions()[target])return false;
 if((i===0)!==(target==='GK')){toast('门将与外场球员的位置分开设置');render();return false;}
 if(cell.position!==target){
  const other=cells.findIndex(c=>c.position===target);
  if(other>=0){
   [cells[i],cells[other]]=[cells[other],cells[i]];
  }else{
   const moved=clone(cells);
   moved[i].position=target;
   moved.forEach((c,j)=>harmonizeCell(c,p,j,side,moved));
   const adjusted=moved.filter((c,j)=>c.role!==cells[j].role||c.duty!==cells[j].duty||
    Object.keys(c.instructions).some(key=>c.instructions[key]!==cells[j].instructions[key]));
   if(adjusted.length){
    const names=adjusted.map(c=>desktopPositionNames[c.position]).join('、');
    if(!confirm(`移动后，${names}有角色或个人指令不适用于新阵型。是否继续并调整这些设置？`)){
     render();return false;
    }
   }
   team().phases[p]=moved;
  }
  save();
 }
 phase=p;slot=i;render();return true;
}
function desktopBindDrag(){
 $$('[data-board-slot]').forEach(button=>{
  const p=+button.dataset.boardPhase,i=+button.dataset.boardSlot,pitch=button.closest('.pitch');let drag=null,suppress=false;
  button.onclick=()=>{if(suppress){suppress=false;return;}phase=p;slot=i;teamTab='personal';render();};
  button.onpointerdown=e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,target:team().phases[p][i].position,moved:false};button.setPointerCapture(e.pointerId);};
  button.onpointermove=e=>{
   if(!drag)return;if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5&&!drag.moved)return;
   drag.moved=true;pitch.classList.add('dragging');button.classList.add('being-dragged');const r=pitch.getBoundingClientRect(),x=Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100)),y=Math.max(0,Math.min(100,(e.clientY-r.top)/r.height*100));
   button.style.left=x+'%';button.style.top=y+'%';const possible=catalog.positions.filter(pos=>(i===0)===(pos.id==='GK'));
   const nearest=possible.reduce((a,b)=>Math.hypot(a.x-x,(a.y-y)*r.height/r.width)<=Math.hypot(b.x-x,(b.y-y)*r.height/r.width)?a:b);drag.target=nearest.id;
   pitch.querySelectorAll('.drop-position').forEach(dot=>dot.classList.toggle('drop-target',dot.dataset.position===nearest.id));
  };
  button.onpointerup=e=>{if(!drag)return;const ended=drag;drag=null;if(button.hasPointerCapture(e.pointerId))button.releasePointerCapture(e.pointerId);if(ended.moved){suppress=true;desktopMove(p,i,ended.target);}};
  button.onpointercancel=()=>{drag=null;render();};
  button.onkeydown=e=>{if(!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();if(i===0)return;const a=positions()[team().phases[p][i].position],dx=e.key==='ArrowLeft'?-1:e.key==='ArrowRight'?1:0,dy=e.key==='ArrowUp'?-1:e.key==='ArrowDown'?1:0;const candidates=catalog.positions.filter(b=>b.id!=='GK'&&(dx?(b.x-a.x)*dx>1:Math.abs(b.x-a.x)<3&&(b.y-a.y)*dy>1));if(candidates.length){candidates.sort((a1,b)=>Math.hypot(a1.x-a.x,a1.y-a.y)-Math.hypot(b.x-a.x,b.y-a.y));desktopMove(p,i,candidates[0].id);$(`[data-board-phase="${p}"][data-board-slot="${i}"]`)?.focus();}};
 });
}
const desktopBindPrevious=bind;bind=function(){desktopBindPrevious();if(view!=='tactics')return;desktopBindDrag();$('#slot-position').onchange=e=>desktopMove(phase,slot,e.target.value);$$('.instruction-tile').forEach(tile=>{const select=tile.querySelector('select');tile.classList.toggle('tile-locked',!!select?.disabled);if(select?.disabled)tile.setAttribute('aria-label',tile.querySelector('.tile-title').textContent+'，角色锁定');});};
document.title='FM27 战术推演 · v1109.3';
function desktopIsKeeper(index,s=side){const t=state.teams[s],slotIndex=t.lineup.indexOf(index);if(slotIndex>=0)return t.phases[0][slotIndex].position==='GK';const a=t.players[index].attributes;return a[0]>=10&&a[0]>=Math.max(...a.slice(2,15));}
function desktopAttributeVisible(id,keeper){if(id<15)return keeper?id===0:id!==0;if(GK.has(id))return keeper;if(keeper&&TECH.has(id)&&![22,37,38].includes(id))return false;if(keeper&&id===21)return false;return true;}
const desktopPlayersPrevious=playersView;playersView=function(){return desktopPlayersPrevious().replace('全部 69 项','全部相关属性');};
function desktopPlayerControls(){
 if(view!=='players')return;const keeper=desktopIsKeeper(player);
 $$('[data-attr]').forEach(input=>{if(!desktopAttributeVisible(+input.dataset.attr,keeper))input.closest('.attribute-row').remove();});
 $$('.attribute-group').forEach(group=>{if(!group.querySelector('.attribute-row'))group.remove();});
 const summary=$('.player-summary .tiny');if(summary)summary.textContent+=keeper?' · 门将属性视图':' · 外场属性视图';
 const bulk=$('#bulk-attribute');if(bulk){[...bulk.options].forEach(option=>{if(!desktopAttributeVisible(+option.value,keeper))option.remove();});if(!bulk.value)bulk.selectedIndex=0;}
 if($('#bulk-apply'))$('#bulk-apply').onclick=()=>{
  const id=+bulk.value,value=+$('#bulk-value').value;if(!Number.isFinite(value)||value<1||value>20){toast('属性显示值应在 1–20 之间');return;}
  const scope=$('#bulk-scope').value,targets=scope==='player'?[player]:scope==='starters'?team().lineup:team().players.map((_,i)=>i);let n=0;
  for(const i of targets)if(desktopAttributeVisible(id,desktopIsKeeper(i))){team().players[i].attributes[id]=Math.round(value*5);n++;}save();render();toast(`已修改 ${n} 名适用球员`);
 };
}
function desktopStatBlock(runs,title){
 const available=runs.filter(r=>r.statistics?.teams?.length===2);if(!available.length)return `<div class="notice">${esc(title)}：旧版记录未采集控球、xG 等统计；新版本运行的比赛会显示这些数据。</div>`;
 const definitions=[['possession','控球率',true],['xg','预期进球 xG'],['shots','射门'],['shots_on_target','射正'],['passes','传球次数'],['completed_passes','成功传球']];
 return `<section class="card match-statistics"><div class="card-head"><h3>${esc(title)} · 场均比赛数据</h3><span class="tag">${available.length} 场有原生统计</span></div><div class="card-body"><div class="stat-sides"><b>${esc(state.teams[0].name)}</b><b>${esc(state.teams[1].name)}</b></div>${definitions.map(([key,label,percent])=>{const values=[0,1].map(s=>available.reduce((n,r)=>n+(r.statistics.teams[s][key]??0),0)/available.length);return `<div class="stat-comparison"><strong>${percent?pct(values[0]):fmt(values[0])}</strong><span>${label}</span><strong>${percent?pct(values[1]):fmt(values[1])}</strong></div>`;}).join('')}<p class="tiny muted">来自原版球队统计对象；控球率由原版控球计数计算。仅对已采集统计的完整比赛取平均。</p></div></section>`;
}
const desktopResultsPrevious=resultsView;resultsView=function(){let html=desktopResultsPrevious();const j=selectedJob;if(!j)return html;const blocks=['A','B'].filter(v=>j.runs.some(r=>r.variant===v)).map(v=>desktopStatBlock(j.runs.filter(r=>r.variant===v),variantLabel(v,j))).join('');const failures=(j.failures||[]).length?`<section class="card failure-details"><div class="card-head"><h3>未计入结果的场次</h3></div><div class="card-body">${j.failures.map(f=>`<p>种子 ${f.seed} · ${esc(variantLabel(f.variant,j))}：${f.failure_phase==='host_exit_after_match'?'比赛已自然结束，但宿主退出异常，需要同种子复核':'宿主异常或校验未通过'}<br><small>${esc((f.errors||[]).join('；'))}</small></p>`).join('')}</div></section>`:'';html=html.replace('<div class="result-layout">',blocks+failures+'<div class="result-layout">');return html;};
const desktopEventsPrevious=eventsView;eventsView=function(run){return desktopEventsPrevious(run)+(run?.statistics?desktopStatBlock([run],'种子 '+run.seed).replace('场均比赛数据','本场比赛数据'):'');};
const desktopFeatureBindPrevious=bind;bind=function(){desktopFeatureBindPrevious();desktopPlayerControls();if(view==='results'&&$('#batch-csv'))$('#batch-csv').onclick=()=>{
 const header=['方案','种子','主队进球','客队进球','主队控球率','客队控球率','主队xG','客队xG','主队射门','客队射门','主队射正','客队射正','主队传球','客队传球','主队成功传球','客队成功传球','进球者（有球／无球位置）','助攻配对','红黄牌','耗时秒','日志'];const rows=selectedJob.runs.map(r=>{const teams=r.statistics?.teams;return[variantLabel(r.variant),r.seed,...r.result.score,...['possession','xg','shots','shots_on_target','passes','completed_passes'].flatMap(k=>teams?[teams[0][k],teams[1][k]]:['','']),(r.events?.goals||[]).map(g=>(g.own_goal?'乌龙：':'')+(g.scorer?g.scorer.name+'（'+g.scorer.ip_position+'／'+g.scorer.oop_position+'）':'身份未确认')).join('；'),(r.events?.goals||[]).map(g=>(g.scorer?.name||'未知')+' ← '+(g.assist?.name||'无助攻')).join('；'),(r.events?.cards||[]).map(c=>c.player.name+' '+({yellow:'黄牌',red:'红牌',second_yellow:'两黄变红'}[c.card])).join('；'),r.elapsed_seconds??'',r.log];});const csv='\ufeff'+[header,...rows].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`FM27-${selectedJob.id}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};};
