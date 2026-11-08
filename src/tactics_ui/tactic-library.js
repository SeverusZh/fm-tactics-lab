'use strict';
let librarySave=null,libraryClub=null,libraryReport=null,libraryStage='',libraryExport=null,libraryTimer;
const libraryDirectory=()=>localStorage.getItem('fm27-export-directory')||'';
function libraryRefresh(){if(view==='library')render()}
function updateLibraryStage(){const el=$('#library-stage');if(el)el.textContent=libraryStage||''}
async function libraryRequest(url,data,onStage){
 for(let attempt=0;attempt<120;attempt++){
  const result=await api(url,data);
  if(result.status!=='reading')return result;
  if(onStage)onStage(result.stage||'正在读取…');
  await new Promise(resolve=>setTimeout(resolve,2000));
 }
 throw Error('读取超时，请稍后重试');
}
function libraryView(){
 const save=librarySave,status=save?.status,clubs=save?.clubs||[];
 return `<div class="card"><div class="card-head"><h2>识别存档</h2><span class="tiny" role="status" id="library-stage">${esc(libraryStage||save?.stage||'')}</span></div><div class="card-body"><div class="save-team-controls"><label>存档完整路径<input id="library-path" value="${esc(save?.source||'')}" placeholder="选择本机 .fm 存档"></label><button id="library-pick" class="button">选择存档…</button><button id="library-read" class="button" ${status==='reading'?'disabled':''}>读取存档</button></div>${status==='complete'?`<p class="tiny muted">存档日期 ${esc(save.date||'')} · 构建 ${esc(save.build||'')}</p><div class="save-team-controls"><label>我的球队<select id="library-club">${clubs.map(c=>`<option value="${c.uid}" ${c.uid===libraryClub?'selected':''}>${esc(c.name)}（${c.players}人）${(save.managed||[]).some(m=>m.club_uid===c.uid)?' · 人类经理执教':''}</option>`).join('')}</select></label></div>`:''}${save?.warnings?.length?`<details><summary>解析提示（${save.warnings.length}）</summary>${save.warnings.map(w=>`<p class="tiny">${esc(w)}</p>`).join('')}</details>`:''}</div></div>${libraryReport?libraryLeagueCard(libraryReport):''}`;
}
function libraryLeagueCard(report){
 const own=report.own||{},teams=report.teams||[],failures=report.failures||[];
 return `<div class="card"><div class="card-head"><h2>当前联赛</h2><span class="tag">${teams.length} 支对手</span></div><div class="card-body"><div class="save-team-controls"><label>国家<select><option>当前国家</option></select></label><label>联赛<select><option>当前联赛 · ${own.club_count??teams.length+1} 队</option></select></label></div><p class="tiny muted">存档不保存国家与联赛名称，这里按当前联赛分组。</p><div class="table-scroll"><table><thead><tr><th>球队</th><th>预设战术</th><th>状态</th></tr></thead><tbody>${teams.map(t=>`<tr><td>${esc(t.name)}</td><td>${esc(t.tactic_name||'')}</td><td class="tiny">${t.available===false?'暂不可用':'可用'}</td></tr>`).join('')}</tbody></table></div>${failures.length?`<details><summary>未接入 ${failures.length} 项</summary>${failures.map(f=>`<p class="tiny">${esc(f.club||f.name||'')}：${esc(f.error||'读取失败')}</p>`).join('')}</details>`:''}<div class="save-team-controls"><label>导出目录<input id="library-directory" value="${esc(libraryDirectory())}" placeholder="选择本机文件夹"></label><button id="library-folder" class="button">选择目录…</button><button id="library-export" class="button">导出全部战术</button><button id="library-pool" class="button primary">导入客队战术池</button></div>${libraryExport?`<div class="notice">已写入 ${libraryExport.files?.length||0} 个战术文件到 ${esc(libraryExport.directory||'')}</div>${(libraryExport.failures||[]).length?`<details open><summary>失败 ${libraryExport.failures.length} 项</summary>${libraryExport.failures.map(f=>`<p class="tiny">${esc(f.club||'')}${f.tactic_name?' · '+esc(f.tactic_name):''}：${esc(f.error||'写入失败')}</p>`).join('')}</details>`:''}`:''}</div></div>`;
}
function bindLibrary(){
 if(view!=='library')return;
 if($('#library-pick'))$('#library-pick').onclick=async()=>{try{const r=await api('/api/save/pick',{});if(r.path){$('#library-path').value=r.path;$('#library-read').click()}}catch(e){toast(e.message)}};
 if($('#library-read'))$('#library-read').onclick=readLibrary;
 if($('#library-club'))$('#library-club').onchange=()=>{libraryClub=+$('#library-club').value;libraryReport=null;libraryExport=null;loadLibraryLeague()};
 if($('#library-folder'))$('#library-folder').onclick=async()=>{try{const r=await api('/api/save/pick-folder',{});if(r.path){localStorage.setItem('fm27-export-directory',r.path);$('#library-directory').value=r.path}}catch(e){toast('选择目录失败：'+e.message)}};
 if($('#library-export'))$('#library-export').onclick=exportLibrary;
 if($('#library-pool'))$('#library-pool').onclick=importLibraryPool;
}
async function readLibrary(){
 const path=$('#library-path').value.trim();
 if(!path){toast('请填写存档完整路径');return}
 try{
  libraryStage='';libraryReport=null;libraryExport=null;
  const result=await api('/api/save/import',{path});
  librarySave={id:result.id,status:'reading',stage:result.reused?'存档未变化，复用已解析数据':'正在读取存档',source:path};
  if(result.reused)toast('存档未变化，已复用解析结果');
  render();pollLibrary();
 }catch(e){toast('读取存档失败：'+e.message)}
}
async function pollLibrary(){
 clearTimeout(libraryTimer);
 try{
  const value=await api('/api/save/status'+(librarySave?.id?'?id='+librarySave.id:''));
  librarySave={...librarySave,...value};
  if(value.status==='reading'){libraryRefresh();libraryTimer=setTimeout(pollLibrary,1500);return}
  libraryStage='';
  if(value.status==='error'){toast(value.stage||'存档读取失败');libraryRefresh();return}
  libraryClub=value.clubs?.some(c=>c.uid===libraryClub)?libraryClub:(value.clubs?.[0]?.uid??null);
  if(libraryClub==null){toast('未找到可读取的球队');libraryRefresh();return}
  await loadLibraryLeague();
 }catch(e){toast(e.message);libraryRefresh()}
}
async function loadLibraryLeague(){
 if(!librarySave?.id||libraryClub==null)return;
 libraryReport=null;libraryExport=null;libraryStage='正在读取联赛战术…';libraryRefresh();
 try{
  const report=await libraryRequest('/api/save/league-library',{id:librarySave.id,club_uid:libraryClub},stage=>{libraryStage=stage;updateLibraryStage()});
  if(report.status==='error')throw Error(report.stage||'联赛战术读取失败');
  libraryReport=report;libraryStage='';libraryRefresh();
 }catch(e){libraryStage='';toast('联赛战术读取失败：'+e.message);libraryRefresh()}
}
async function exportLibrary(){
 const directory=$('#library-directory').value.trim(),button=$('#library-export');
 if(!directory){toast('请填写或选择导出目录');return}
 button.disabled=true;button.textContent='正在导出中…';
 try{
  const result=await api('/api/save/league-export',{id:librarySave.id,club_uid:libraryClub,directory});
  localStorage.setItem('fm27-export-directory',result.directory||directory);
  libraryExport=result;toast(`已导出 ${result.files?.length||0} 个战术文件`);libraryRefresh();
 }catch(e){toast('导出失败：'+e.message);button.disabled=false;button.textContent='导出全部战术'}
}
async function importLibraryPool(){
 const button=$('#library-pool');button.disabled=true;button.textContent='正在导入…';
 try{
  const result=await libraryRequest('/api/save/league-pool',{id:librarySave.id,club_uid:libraryClub,scenario:clone(state)},stage=>{button.textContent=stage||'正在导入…'});
  if(result.status==='error')throw Error(result.stage||'导入失败');
  state=result.scenario;save();
  toast(`已导入 ${result.imported?.length||0} 套战术${result.duplicates?`，去重 ${result.duplicates} 套`:''}`);
  view='pool';render();
 }catch(e){toast('导入客队战术池失败：'+e.message);button.disabled=false;button.textContent='导入客队战术池'}
}
const libraryBindPrevious=bind;
bind=function(){libraryBindPrevious();bindLibrary()};
