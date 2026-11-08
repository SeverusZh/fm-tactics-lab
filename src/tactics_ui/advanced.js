'use strict';
const baseRender=render,baseBind=bind;
const PI_GROUPS=()=>Object.fromEntries(catalog.player_instructions.map(g=>[g.id,g]));
function policyFor(c,p=phase,i=slot,s=side){const duty=c.duty??defaults.teams[s].phases[p][i].duty;return catalog.pi_policies[`${p}:${c.position}:${c.role}:${duty}`]?.['1a080000']||'1'.repeat(43)}
function allowedRoles(c,p=phase,s=side,cells=state.teams[s].phases[p]){const count=cells.filter(x=>positions()[x.position].mask&16).length,dm=cells.filter(x=>positions()[x.position].mask&128).length;return catalog.role_eligibility_context[`${count>=3?3:0}:${dm===1?1:0}`][c.position][p]}
function retainedSourceCell(c,p,s){return state.teams[s].native_source_plan?.value?.phases?.[p]?.find(b=>['position','role','duty'].every(k=>b[k]===c[k]))}
function harmonizeCell(c,p,i,s,cells=state.teams[s].phases[p]){
 if(state.rules!=='game')return;
 const allowed=allowedRoles(c,p,s,cells);
 if(!retainedSourceCell(c,p,s)&&!allowed.includes(c.role)){const preferred=fallbackRole(c.position,p);c.role=allowed.includes(preferred)?preferred:allowed[0];c.duty='0'}
 const policy=policyFor(c,p,i,s);
 const retained=retainedSourceCell(c,p,s);
 for(const g of catalog.player_instructions){const value=c.instructions[g.id];if(value&&(g.phase!==p||policy[value]!=='0')&&retained?.instructions[g.id]!==value)c.instructions[g.id]=0}
}
function harmonizeAll(){state.teams.forEach((t,s)=>{t.phases.forEach((cells,p)=>cells.forEach((c,i)=>harmonizeCell(c,p,i,s)));if(teamConflict(t.instructions)&&JSON.stringify(t.native_source_plan?.value?.instructions)!==JSON.stringify(t.instructions))t.instructions[31]=catalog.team_instructions.find(g=>g.id===31).options.find(o=>o.native_bit===0).id})}
function teamConflict(instructions){const bits=new Set(catalog.team_instructions.map(g=>g.options.find(o=>o.id===instructions[g.id]).native_bit));return catalog.team_conflicting_bits.some(([a,b])=>bits.has(a)&&bits.has(b))}
function teamRuleControls(){if(view!=='tactics')return;$$('[data-ti]').forEach(e=>{const g=+e.dataset.ti;[...e.options].forEach(o=>{o.disabled=teamConflict({...team().instructions,[g]:+o.value});o.title=o.disabled?'与另一项同侧内套／外套指令互斥':''});const old=e.onchange;e.onchange=event=>{if(teamConflict({...team().instructions,[g]:+event.target.value})){toast('同侧内套和外套不能同时启用');render();return}old?.(event);render()}})}
function policyControls(){
 if(view!=='tactics')return;
 const strict=state.rules==='game',c=current(),policy=policyFor(c),allowed=allowedRoles(c),retained=retainedSourceCell(c,phase,side);
 const selector=$('#slot-role');if(selector)selector.innerHTML=catalog.roles.filter(r=>allowed.includes(r.id)||(retained&&r.id===c.role)).map(r=>`<option value="${esc(r.id)}" ${r.id===c.role?'selected':''}>${esc(r.label)}</option>`).join('');
 $$('[data-pi]').forEach(e=>{
  const g=PI_GROUPS()[e.dataset.pi],label=e.closest('label');label.hidden=strict&&g.phase!==phase;
  const forced=g.options.find(o=>o.id&&policy[o.id]==='3'),editable=g.options.some(o=>o.id&&policy[o.id]==='0');
  e.disabled=strict&&(!!forced||!editable);
  [...e.options].forEach(o=>{o.disabled=strict&&+o.value!==0&&policy[+o.value]!=='0'});
  if(strict&&forced&&retained?.instructions[g.id]!==c.instructions[g.id])e.value=String(forced.id);
  const note=document.createElement('small');note.className='constraint-note';
  if(strict&&forced)note.textContent='🔒 角色固定';else if(strict&&!editable)note.textContent='🔒 该角色不使用此指令';
  if(note.textContent)label.append(note);
 });
 const count=$('.group-heading .tiny');if(count)count.textContent=strict?`${phase?'无球':'有球'}阶段 · ${phase?4:13} 组`:'实验输入 · 17 组';
 const note=$('.instructions-note');if(note)note.textContent=strict?'位置可用角色和指令锁定由原生代码判定。显示“角色固定”的选项由角色自动执行，不作为额外覆盖项写入。':'实验输入允许提交被角色忽略的覆盖项；原生引擎仍按自身角色规则执行。';
 if(selector)selector.onchange=e=>{c.role=e.target.value;c.duty='0';harmonizeCell(c,phase,slot,side);save();render()};
 for(const id of ['#slot-position','#formation']){const element=$(id);if(element){const old=element.onchange;element.onchange=e=>{old?.(e);harmonizeAll();save();render()}}}
 const lineup=$('#lineup-player');if(lineup){const old=lineup.onchange;lineup.onchange=e=>{
  const ownSide=side,own=state.teams[ownSide],markers=state.teams[1-ownSide];
  const order=t=>t.lineup.concat(t.players.map((_,i)=>i).filter(i=>!t.lineup.includes(i)));
  const before=order(own),targets=markers.phases.flat().map(c=>[c,c.target_player===255?null:before[c.target_player]]);
  old?.(e);const after=order(own);for(const [c,target]of targets)if(target!==null)c.target_player=after.indexOf(target);save();render();
 }}
}
function rulesControl(){const host=$('.toolbar-right');if(!host)return;const label=document.createElement('span');label.className='rules-toggle';label.textContent='🔒 原版位置／角色／指令约束';host.prepend(label);teamRuleControls()}
const OI_OPTIONS={press:[{id:0,label:'默认'},{id:1,label:'从不'},{id:2,label:'总是'}],mark:[{id:0,label:'默认'},{id:1,label:'从不'},{id:2,label:'总是'}],tackle:[{id:0,label:'默认'},{id:1,label:'正常'},{id:2,label:'谨慎'},{id:3,label:'凶狠'}],foot:[{id:0,label:'不指定'},{id:1,label:'左脚'},{id:2,label:'右脚'},{id:3,label:'弱势脚'}]};
let oiTab='players';
function oiControls(row,kind,id){return ['press','mark','tackle','foot'].map(k=>`<td>${select(OI_OPTIONS[k],row[k],`data-oi="${k}" data-kind="${kind}" data-index="${id}"`)}</td>`).join('')}
function oppositionView(){const opponent=state.teams[1-side],oi=team().opposition;return `${toolbar()}<div class="card"><div class="card-head"><div><h2>${esc(team().name)}的针对性指令</h2><div class="subtitle">设置如何应对 ${esc(opponent.name)}，不是给对方下指令</div></div><div class="segmented"><button data-oi-tab="players" class="${oiTab==='players'?'active':''}">针对球员</button><button data-oi-tab="positions" class="${oiTab==='positions'?'active':''}">针对位置</button></div></div><div class="card-body"><div class="notice">“按球员”使用该球员的单独设置；“按位置”使用其有球位置的设置。名单重排时目标身份保持一致，开赛前由原生函数核对22名对手的有效指令。</div></div><div class="table-scroll"><table class="opposition-table"><thead><tr><th>${oiTab==='players'?'对方球员':'对方位置'}</th>${oiTab==='players'?'<th>采用设置</th>':''}<th>逼抢</th><th>紧逼盯人</th><th>铲抢</th><th>引导至</th></tr></thead><tbody>${oiTab==='players'?opponent.players.map((p,i)=>{const row=oi.players[i];return `<tr><td>${esc(p.name)}<small class="muted"> ${opponent.lineup.includes(i)?'首发':'替补'}</small></td><td>${select([{id:1,label:'按球员'},{id:0,label:'按位置'}],+row.personal,`data-oi="personal" data-kind="players" data-index="${i}"`)}</td>${oiControls(row,'players',i)}</tr>`}).join(''):catalog.positions.map(p=>`<tr><td>${esc(p.id)}</td>${oiControls(oi.positions[p.id],'positions',p.id)}</tr>`).join('')}</tbody></table></div><div class="card-body tiny muted">逼抢、盯人、铲抢与脚向均写入原生针对性指令。按位置的设置对选择了“按位置”的球员生效；不会覆盖选择“按球员”的球员。</div></div>`}
function setPiecesView(){const t=team();return `${toolbar()}<div class="card"><div class="card-head"><div><h2>队长优先顺序</h2><div class="subtitle">第一名在首发中的候选人作为本场队长；空列表由原生引擎选择</div></div><span class="tag">核对实际队长</span></div><div class="card-body"><div class="captain-list">${t.captains.length?t.captains.map((p,i)=>`<div class="captain-row"><span>${i+1}</span><strong>${esc(t.players[p].name)}</strong><span class="muted tiny">${t.lineup.includes(p)?'首发':'替补'}</span><button class="button small" data-cap-up="${i}" ${i===0?'disabled':''}>↑</button><button class="button small" data-cap-down="${i}" ${i===t.captains.length-1?'disabled':''}>↓</button><button class="button small ghost" data-cap-remove="${i}">移除</button></div>`).join(''):'<p class="muted">原生自动选择</p>'}</div><div class="captain-add">${select([{id:'',label:'选择候选队长…'},...t.players.map((p,i)=>({id:i,label:p.name})).filter(p=>!t.captains.includes(p.id))],'','id="captain-add"')}<button class="button small" id="captain-clear">恢复自动选择</button></div></div></div><div id="setpiece-routines"></div>`}
render=function(){if(!['opposition','setpieces'].includes(view))return baseRender();$('#page-title').textContent=view==='opposition'?'针对对手，细化比赛计划':'定位球与比赛职责';$$('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view));$('#workspace').innerHTML=view==='opposition'?oppositionView():setPiecesView();bind()};
bind=function(){baseBind();rulesControl();policyControls();$$('[data-oi-tab]').forEach(b=>b.onclick=()=>{oiTab=b.dataset.oiTab;render()});$$('[data-oi]').forEach(e=>e.onchange=()=>{const row=team().opposition[e.dataset.kind][e.dataset.index];row[e.dataset.oi]=e.dataset.oi==='personal'?!!+e.value:+e.value;save()});$$('[data-cap-remove]').forEach(b=>b.onclick=()=>{team().captains.splice(+b.dataset.capRemove,1);save();render()});for(const [tag,diff]of [['up',-1],['down',1]])$$(`[data-cap-${tag}]`).forEach(b=>b.onclick=()=>{const i=+b.dataset[tag==='up'?'capUp':'capDown'],a=team().captains;[a[i],a[i+diff]]=[a[i+diff],a[i]];save();render()});if($('#captain-add'))$('#captain-add').onchange=e=>{if(e.target.value!==''){team().captains.push(+e.target.value);save();render()}};if($('#captain-clear'))$('#captain-clear').onclick=()=>{team().captains=[];save();render()}};
const renderConstrained=render;render=function(){if(state){const before=JSON.stringify(state.teams.map(t=>[t.phases,t.instructions]));const legacy=state.rules!=='game';state.rules='game';harmonizeAll();if(legacy||before!==JSON.stringify(state.teams.map(t=>[t.phases,t.instructions]))){save();toast('已按位置与角色规则调整不适用的选项，保留球员属性与其他配置')}}return renderConstrained()};
for(const [name,label,symbol]of [['opposition','针对性指令','◎'],['setpieces','定位球与职责','⚑']]){const b=document.createElement('button');b.dataset.view=name;b.innerHTML=`${symbol} <span>${label}</span>`;b.onclick=()=>{view=name;render();window.scrollTo(0,0)};$('.rail nav').insertBefore(b,$('[data-view="results"]'))}
const TAKER_TYPES=[['penalties','点球'],['corners','角球'],['direct_free_kicks','直接任意球'],['wide_free_kicks','边路任意球'],['deep_free_kicks','对方半场任意球'],['throw_ins','进攻界外球']];
let takerType='penalties',takerFoot='left_foot';
const takerByFoot=()=>['corners','wide_free_kicks'].includes(takerType);
const takerKey=()=>takerType==='penalties'?takerType:`${takerType}_${takerByFoot()?takerFoot:takerFoot.replace('_foot','_side')}`;
function takersView(){
 const t=team();t.takers??=clone(defaults.teams[side].takers);const list=t.takers[takerKey()];
 return `<div class="card"><div class="card-head"><div><h2>定位球主罚优先顺序</h2><div class="subtitle">比赛中的原生主罚选择函数读取此名单；未设置时按原生属性与场景选择</div></div></div><div class="card-body"><div class="preset-row">${select(TAKER_TYPES.map(([id,label])=>({id,label})),takerType,'id="taker-type"')}${takerType==='penalties'?'':select([{id:'left_foot',label:takerByFoot()?'左脚主罚名单':'左侧主罚名单'},{id:'right_foot',label:takerByFoot()?'右脚主罚名单':'右侧主罚名单'}],takerFoot,'id="taker-foot"')}</div><p class="notice">角球和边路任意球按出球脚分组，直接任意球、对方半场任意球和进攻界外球按球所在侧分组。防守／中场界外球和本方半场任意球保留原生常规选择。引擎还会判断球员是否在场、是否可用；替补仍可列入候选。</p><div class="captain-list">${list.map((p,i)=>`<div class="captain-row"><span>${i+1}</span><strong>${esc(t.players[p].name)}</strong><span class="muted tiny">${t.lineup.includes(p)?'首发':'替补'}</span><button class="button small" data-taker-up="${i}" ${i?'':'disabled'}>↑</button><button class="button small" data-taker-down="${i}" ${i===list.length-1?'disabled':''}>↓</button><button class="button small ghost" data-taker-remove="${i}">移除</button></div>`).join('')||'<p class="muted">原生自动选择</p>'}</div><div class="captain-add">${select([{id:'',label:'选择主罚候选人…'},...t.players.map((p,i)=>({id:i,label:p.name})).filter(p=>!list.includes(p.id))],'','id="taker-add"')}<button class="button small" id="taker-clear">恢复自动选择</button></div></div></div>`;
}
const captainView=setPiecesView;setPiecesView=function(){return captainView().replace('<div id="setpiece-routines"></div>',takersView()+'<p class="notice">本场使用样本原版定位球套路。套路站位、跑动、发球策略和使用频率尚未开放编辑。</p>')};
const bindAdvanced=bind;bind=function(){bindAdvanced();
 for(const [id,key]of [['#taker-type','type'],['#taker-foot','foot']])if($(id))$(id).onchange=e=>{if(key==='type')takerType=e.target.value;else takerFoot=e.target.value;render()};
 if(view!=='setpieces')return;const list=team().takers[takerKey()];
 if($('#taker-add'))$('#taker-add').onchange=e=>{if(e.target.value!==''){list.push(+e.target.value);save();render()}};
 if($('#taker-clear'))$('#taker-clear').onclick=()=>{team().takers[takerKey()]=[];save();render()};
 $$('[data-taker-remove]').forEach(b=>b.onclick=()=>{list.splice(+b.dataset.takerRemove,1);save();render()});
 for(const [direction,delta]of [['up',-1],['down',1]])$$(`[data-taker-${direction}]`).forEach(b=>b.onclick=()=>{const i=+b.dataset[direction==='up'?'takerUp':'takerDown'];[list[i],list[i+delta]]=[list[i+delta],list[i]];save();render()});
};
