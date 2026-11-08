'use strict';
let matchImportSide=0,matchImportBusy=false;
const workspaceToolbarPrevious=toolbar;
toolbar=function(){
 const base=workspaceToolbarPrevious()+'<p class="tiny muted controlled-state-note">双方全名单开赛体能／比赛状态 100% · 累积疲劳 0 · 士气 20/20 · 球队磨合 80 · 俱乐部磨合 100；比赛中状态正常变化。</p>';if(!['tactics','setpieces'].includes(view))return base;
 const setpiece=view==='setpieces',label=setpiece?spDefinition().label:'比赛战术';
 const sides=editableTeamSides(),singleTeam=sides.length===1;
 const cards=sides.map(s=>{
  const t=state.teams[s],teamLabel=singleTeam?'己方':s?'客队':'主队';
  const edit=singleTeam?'':`<button class="button small" data-edit-team="${s}">${s===side?'正在编辑':'编辑此队'}</button>`;
  const name=setpiece?t.setpieces.routines[spType].map(r=>r.name).join(' ／ '):t.tactic_name||'默认／手动设置';
  const actions=setpiece?'<p class="tiny muted">下方编辑该球队的定位球。</p>':`<div class="team-load-actions"><button class="button" data-match-import="${s}">导入${teamLabel}比赛战术 FMF</button><button class="button small" data-match-export="${s}">导出${teamLabel}比赛战术 FMF</button></div><p class="tiny muted">已加载的比赛战术可继续修改；定位球在定位球页单独导入。</p>`;
  return `<section class="team-load-card ${s===side?'editing':''}" data-loaded-team="${s}"><div class="team-load-heading"><span class="tag">${teamLabel}</span><b>${esc(t.name)}</b>${edit}</div><small>${esc(label)}</small><strong class="loaded-tactic-name">${esc(name)}</strong>${actions}</section>`;
 });
 return base+`<div class="team-load-grid${singleTeam?' single-team':''}">${cards.join('')}</div>`;
};
const workspaceBindPrevious=bind;
bind=function(){workspaceBindPrevious();
 $$('[data-edit-team]').forEach(b=>b.onclick=()=>{side=+b.dataset.editTeam;slot=player=0;render();});
 $$('[data-match-import]').forEach(b=>{b.disabled=matchImportBusy;b.onclick=()=>{matchImportSide=+b.dataset.matchImport;$('#match-file').click();};});
 $$('[data-match-export]').forEach(b=>b.onclick=async()=>{const target=+b.dataset.matchExport;try{b.disabled=true;b.textContent='写入并核验…';const result=await api('/api/export-fmf',{side:target,scenario:state});downloadBinary(result);toast(`${target?'客队':'主队'}比赛战术已导出`);}catch(e){toast(e.message);}finally{render();}});
};
$('#match-file').onchange=async e=>{
 const file=e.target.files[0],target=matchImportSide;if(!file)return;
 try{if(!/\.fmf$/i.test(file.name))throw Error('请选择比赛战术 FMF 文件');if(file.size>4*1024*1024)throw Error('FMF 文件超过 4 MB');matchImportBusy=true;render();
 const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
 const result=await api('/api/import-fmf',{side:target,scenario:state,file_base64:btoa(binary)});state=result.scenario;side=target;save();toast(`${target?'客队':'主队'}已加载比赛战术：${state.teams[target].tactic_name||file.name}`);
 }catch(e){toast('比赛战术导入失败：'+e.message);}finally{matchImportBusy=false;e.target.value='';render();}
};
// Document leases survive navigation/reload without leaving a separate service window.
const desktopPage=crypto.randomUUID();
function desktopPresence(action){const body=JSON.stringify({page:desktopPage,action});if(action==='close')navigator.sendBeacon('/api/desktop-presence',new Blob([body],{type:'application/json'}));else fetch('/api/desktop-presence',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true}).catch(()=>{});}
window.addEventListener('pageshow',()=>desktopPresence('open'));
window.addEventListener('pagehide',()=>desktopPresence('close'));
setInterval(()=>desktopPresence('open'),15000);desktopPresence('open');
