'use strict';
let squadPlayer=0;
function syncSquadFromMatch(t){
 if(!t.squad)return;
 const byId=new Map(t.squad.map(p=>[p.source_uid,p]));
 for(const p of t.players.slice(0,t.roster_size)){
  const target=byId.get(p.source_uid);if(!target)continue;
  for(const key of ['name','attributes','native_profile'])target[key]=clone(p[key]);
 }
}
function syncMatchFromSquad(t){
 if(!t.squad)return;
 const byId=new Map(t.squad.map(p=>[p.source_uid,p]));
 for(const p of t.players.slice(0,t.roster_size)){
  const source=byId.get(p.source_uid);if(!source)continue;
  for(const key of ['name','attributes','native_profile'])p[key]=clone(source[key]);
 }
}
const squadSavePrevious=save;
save=function(){state?.teams?.forEach(syncSquadFromMatch);return squadSavePrevious();};
function squadStatus(p,t=team()){
 const index=t.players.findIndex(q=>q.source_uid===p.source_uid);
 if(index<0||index>=t.roster_size)return '未入选比赛名单';
 const slot=t.lineup.indexOf(index);
 return slot<0?'替补':`首发 · 有球 ${t.phases[0][slot].position} ／ 无球 ${t.phases[1][slot].position}`;
}
const squadToolbarPrevious=toolbar;
toolbar=function(){let html=squadToolbarPrevious();if(team().squad)html=html.replace(`${team().players.length} 人名单`,`一线队 ${team().squad.length} 人 · 本场 ${team().roster_size} / 23 人`);return html;};
const squadTacticsPrevious=tacticsView;
tacticsView=function(){
 const html=squadTacticsPrevious(),t=team();if(!t.squad)return html;
 const starters=new Set(t.lineup),bench=t.players.map((p,i)=>({p,i})).filter(({i})=>i<t.roster_size&&!starters.has(i));
 const panel=`<section class="bench-panel" aria-label="本场替补名单"><div class="bench-panel-heading"><div><h3>本场替补 <span class="tag">${bench.length} / 12</span></h3><p class="tiny muted">本场 ${t.roster_size} / 23 人 · 一线队另有 ${t.squad.length-t.roster_size} 人未入选</p></div><button class="button small" id="board-match-squad">调整比赛名单</button></div><div class="bench-player-list">${bench.map(({p,i},j)=>`<button class="bench-player" data-bench-player="${i}" title="查看${esc(p.name)}的属性"><span class="tag">替补 ${j+1}</span><b>${esc(p.name)}</b><small>查看属性 ↗</small></button>`).join('')||'<p class="tiny muted bench-empty">尚未选择替补，可通过“调整比赛名单”添加。</p>'}</div></section>`;
 return html.replace('</div></section><section class="instruction-panel">','</div>'+panel+'</section><section class="instruction-panel">');
};
const squadPlayersPrevious=playersView;
playersView=function(){
 const t=team();if(!t.squad)return squadPlayersPrevious();
 syncSquadFromMatch(t);squadPlayer=Math.min(squadPlayer,Math.max(0,t.squad.length-1));
 const p=t.squad[squadPlayer];
 const fragment=document.createElement('div');fragment.innerHTML=squadPlayersPrevious();
 const bulk=fragment.querySelector('.team-bulk-controls')?.outerHTML||'';
 return `${toolbar()}<div class="player-layout"><aside class="card player-list"><div style="padding:12px"><b>完整一线队 · ${t.squad.length}人</b><p class="tiny muted">未入选球员保留在这里，不参与模拟。</p><button class="button small" id="squad-selection">排首发／选替补</button></div>${t.squad.map((p,i)=>`<button data-squad-player="${i}" class="player-item ${i===squadPlayer?'active':''}"><span class="number">${i+1}</span><span>${esc(p.name)}<small>${esc(squadStatus(p,t))}</small></span></button>`).join('')}</aside><section class="card"><div class="card-body">${bulk}<h2>${esc(p.name)}</h2><p class="tiny muted">${esc(squadStatus(p,t))} · CA ${p.native_profile?.current_ability??'未知'} · 所有属性可编辑，未入选球员的修改不会进入本场模拟。</p><label>姓名 <input id="squad-name" maxlength="48" value="${esc(p.name)}"></label><label class="raw-toggle"><input id="raw" type="checkbox" ${raw?'checked':''}>内部原值</label><div class="squad-attributes">${catalog.attributes.map(a=>`<label>${esc(a.label)}<input type="number" data-squad-attribute="${a.id}" value="${a.id<15||raw?p.attributes[a.id]:p.attributes[a.id]/5}" min="0" max="${a.id<15||!raw?20:100}" step="${a.id<15||raw?1:0.2}"></label>`).join('')}</div><button class="button small" id="squad-attribute-reset">恢复该球员导入属性</button></div></section></div>`;
};
function showSquadSelection(){
 const t=state.teams[0];
 if(!t.squad){toast('当前方案没有完整一线队名单');return;}
 syncSquadFromMatch(t);
 const roster=t.squad.map(p=>({uid:p.source_uid,name:p.name}));
 const picks=t.lineup.map(i=>t.players[i].source_uid);
 const bench=t.players.slice(0,t.roster_size).filter((p,i)=>!t.lineup.includes(i)).map(p=>p.source_uid);
 const dialog=document.createElement('dialog');dialog.className='save-dialog squad-selection-dialog';
 dialog.innerHTML=`<h2>一线队 ${roster.length} 人 · 本场最多23人</h2><p>选择11名首发和最多12名替补。未选球员继续保留在一线队，不参与本场模拟。不自动补人。</p><div class="squad-pick-grid">${Array.from({length:11},(_,i)=>`<label>${esc(t.phases[0][i].position)}<select data-squad-pick="${i}"><option value="">请选择球员</option>${roster.map(p=>`<option value="${p.uid}" ${picks[i]===p.uid?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label>`).join('')}</div><h3>替补 <span id="squad-bench-count"></span></h3><div class="squad-bench-list">${roster.map(p=>`<label><input type="checkbox" data-squad-bench="${p.uid}" ${bench.includes(p.uid)?'checked':''}>${esc(p.name)}</label>`).join('')}</div><div class="dialog-actions"><button class="button" data-close>取消</button><button class="button primary" data-accept>应用比赛名单</button></div>`;
 const currentPicks=()=>[...dialog.querySelectorAll('[data-squad-pick]')].map(s=>s.value===''?null:Number(s.value));
 const refresh=()=>{const starts=new Set(currentPicks());dialog.querySelectorAll('[data-squad-bench]').forEach(c=>{c.disabled=starts.has(+c.dataset.squadBench);if(c.disabled)c.checked=false;});const count=dialog.querySelectorAll('[data-squad-bench]:checked').length;dialog.querySelector('#squad-bench-count').textContent=`${count} / 12`;};
 document.body.append(dialog);dialog.querySelectorAll('select,input').forEach(e=>e.onchange=refresh);refresh();
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();dialog.querySelector('[data-accept]').onclick=async()=>{
  const starters=currentPicks(),substitutes=[...dialog.querySelectorAll('[data-squad-bench]:checked')].map(c=>+c.dataset.squadBench);
  if(starters.includes(null)||new Set(starters).size!==11){toast('请选择11名不同的首发球员');return;}
  if(substitutes.length>12){toast('最多选择12名替补');return;}
  try{
   const result=await api('/api/save/selection',{scenario:state,lineup:starters,bench:substitutes});state=result.scenario;side=slot=player=0;save();render();
   dialog.close();toast(`比赛名单：11名首发、${substitutes.length}名替补；其余球员不参与模拟`);
  }catch(e){toast(e.message);}
 };dialog.onclose=()=>dialog.remove();dialog.showModal();
}
const squadBindPrevious=bind;
bind=function(){squadBindPrevious();
 if($('#board-match-squad'))$('#board-match-squad').onclick=showSquadSelection;
 $$('[data-bench-player]').forEach(b=>b.onclick=()=>{const index=+b.dataset.benchPlayer;player=index;squadPlayer=team().squad.findIndex(p=>p.source_uid===team().players[index].source_uid);view='players';render();});
 $$('[data-squad-player]').forEach(b=>b.onclick=()=>{squadPlayer=+b.dataset.squadPlayer;render();});
 $$('[data-squad-attribute]').forEach(input=>input.onchange=()=>{const a=+input.dataset.squadAttribute,v=Number(input.value),value=a<15||raw?v:Math.round(v*5);if(!Number.isFinite(value)||!Number.isInteger(value)||value<0||value>(a<15?20:100)){toast('属性超出范围');render();return;}team().squad[squadPlayer].attributes[a]=value;syncMatchFromSquad(team());save();});
 if($('#squad-selection'))$('#squad-selection').onclick=showSquadSelection;
 if($('#squad-name'))$('#squad-name').onchange=e=>{team().squad[squadPlayer].name=e.target.value.slice(0,48);syncMatchFromSquad(team());save();render();};
 if($('#squad-attribute-reset'))$('#squad-attribute-reset').onclick=()=>{const p=team().squad[squadPlayer];p.attributes=clone(p.initial_attributes);syncMatchFromSquad(team());save();render();};
};
