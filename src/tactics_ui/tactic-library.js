'use strict';
let librarySave=null,libraryLeagues=null,libraryLeague=null,libraryReport=null,libraryStage='',libraryExport=null,libraryTimer,libraryLeaguesLoading=false,libraryLeaguesError='',libraryLeagueError=false,librarySearch='',libraryLeagueToken=0,libraryRealProgress=null,libraryRealToken=0;
const libraryDirectory=()=>localStorage.getItem('fm27-export-directory')||'';
function libraryRefresh(){if(view==='library')render()}
function librarySetStage(value){libraryStage=value;const element=$('#library-stage');if(element)element.textContent=value}
async function libraryRequest(url,data,onStage,active){
 for(let attempt=0;attempt<120;attempt++){
  if(active&&!active())return null;
  const result=await api(url,data);
  if(active&&!active())return null;
  if(result.status!=='reading')return result;
  if(onStage)onStage(result.stage||'正在读取…');
  await new Promise(resolve=>setTimeout(resolve,2000));
 }
 throw Error('读取超时，请稍后重试');
}
function libraryLeagueData(){return libraryReport?.league||libraryLeagues?.leagues?.find(league=>league.key===libraryLeague)||null}
const libraryLeagueName=league=>league.name||('联赛 #'+league.competition_id);
function libraryLeagueSearch(league){return [libraryLeagueName(league),league.nation||''].join(' ').toLowerCase()}
function librarySaveCard(){
 const save=librarySave,reading=save?.status==='reading',complete=save?.status==='complete';
 return `<div class="card"><div class="card-head"><h2>识别存档</h2><span class="tiny" role="status" id="library-save-stage">${esc(save?.stage||'')}</span></div><div class="card-body"><div class="save-team-controls"><label>存档完整路径<input id="library-path" value="${esc(save?.source||'')}" placeholder="选择存档"></label><button id="library-pick" class="button">选择存档…</button><button id="library-read" class="button" ${reading?'disabled':''}>${reading?'正在读取存档':'读取存档'}</button></div>${complete?`<p class="tiny muted">存档日期 ${esc(save.date||'')} · 构建 ${esc(save.build||'')}</p>`:''}${save?.warnings?.length?`<details><summary>解析提示（${save.warnings.length}）</summary>${save.warnings.map(w=>`<p class="tiny">${esc(w)}</p>`).join('')}</details>`:''}</div></div>`;
}
function libraryLeagueRow(league){
 const active=league.key===libraryLeague;
 const name=libraryLeagueName(league);
 const hidden=librarySearch&&!libraryLeagueSearch(league).includes(librarySearch.trim().toLowerCase());
 return `<button type="button" class="league-row ${active?'active':''}" data-league="${esc(league.key)}" data-league-search="${esc(libraryLeagueSearch(league))}" aria-pressed="${active}" ${hidden?'hidden':''}><span>${esc(name)}</span>${league.club_count?`<span class="tag">${league.club_count} 队</span>`:''}</button>`;
}
function libraryLeaguesBody(list){
 const groups=new Map();
 for(const league of list){
  const nation=league.nation||'未知国家';
  if(!groups.has(nation))groups.set(nation,[]);
  groups.get(nation).push(league);
 }
 const query=librarySearch.trim().toLowerCase();
 let visible=false;
 const html=[...groups].map(([nation,leagues])=>{
  let shown=false;
  const rows=leagues.map(league=>{const match=!query||libraryLeagueSearch(league).includes(query);if(match)shown=true;return libraryLeagueRow(league)}).join('');
  if(shown)visible=true;
  return `<div class="league-group" data-league-group ${shown?'':'hidden'}><div class="section-label">${esc(nation)}</div><div class="league-list">${rows}</div></div>`;
 }).join('');
 return `${html}<p class="tiny muted" id="library-league-empty" ${visible?'hidden':''}>没有匹配的联赛</p>`;
}
function libraryLeaguesCard(){
 if(librarySave?.status!=='complete')return '';
 const list=libraryLeagues?.leagues||[];
 const head=`<div class="card-head"><h2>联赛</h2>${list.length?`<span class="tag">${list.length} 个联赛</span>`:''}</div>`;
 if(libraryLeaguesLoading)return `<div class="card">${head}<div class="card-body"><p class="tiny" role="status">正在读取联赛列表</p></div></div>`;
 if(libraryLeaguesError)return `<div class="card">${head}<div class="card-body"><p class="tiny muted">联赛列表读取失败</p><button id="library-leagues-retry" class="button small">重试</button></div></div>`;
 if(!libraryLeagues)return '';
 if(!list.length)return `<div class="card">${head}<div class="card-body"><p class="tiny muted">没有可用的联赛</p></div></div>`;
 const search=list.length>8?`<div class="save-team-controls"><label>搜索联赛<input id="library-league-search" type="search" value="${esc(librarySearch)}" placeholder="搜索联赛"></label></div>`:'';
 return `<div class="card">${head}<div class="card-body">${search}${libraryLeaguesBody(list)}</div></div>`;
}
function libraryVariant(team,index){
 const variant=(team.variants||[]).find(item=>item.index===index);
 if(!variant)return '—';
 if(variant.source==='real_ai')return `<span title="${esc(variant.tactic_name||variant.name||'')}"><span class="tag">真实</span> ${esc(variant.label||'')}</span>`;
 return `<span title="${esc(variant.name||variant.preset_name||'')}">${esc(variant.preset_name||'—')}${variant.formation?` <span class="tiny muted">${esc(variant.formation)}</span>`:''}</span>`;
}
function libraryExportResult(){
 const result=libraryExport,failures=result?.failures||[],skipped=result?.skipped||[];
 if(!result&&!failures.length&&!skipped.length)return '';
 const counts=result&&(result.real_count||result.preset_count)?`（真实 ${result.real_count||0} 套 · 预设 ${result.preset_count||0} 套）`:'';
 const omitted=skipped.length?`<details><summary>未导出 ${skipped.length} 套</summary>${skipped.map(s=>`<p class="tiny">${esc(s.club||('#'+s.club_uid))} · ${esc(s.index??'')} · ${esc(s.reason||'未导出')}</p>`).join('')}</details>`:'';
 return `${result?`<div class="notice">已导出 ${result.files?.length||0} 个战术文件到 ${esc(result.directory||'')}${counts}</div>`:''}${omitted}${failures.length?`<details><summary>失败 ${failures.length} 项</summary>${failures.map(f=>`<p class="tiny">${esc(f.club||f.name||'')}${f.tactic_name?' · '+esc(f.tactic_name):''}：${esc(f.error||'写入失败')}</p>`).join('')}</details>`:''}`;
}
function libraryReportBody(report){
 const teams=report.teams||[],failures=report.failures||[],own=!!report.league?.own;
 const progress=libraryRealProgress,reading=progress?.status==='reading';
 const total=progress?.total||0,done=progress?.done||0,pct=total?Math.round(done*100/total):0;
 const real=team=>{
  if(!own)return '';
  const has=team.real===true||(team.variants||[]).some(item=>item.source==='real_ai');
  return `<td class="tiny"><button type="button" class="button small" data-real-tactic="${team.club_uid}" ${reading?'disabled':''}>${has?'重新生成':'生成'}</button></td>`;
 };
 const rows=teams.map(team=>`<tr><td>${esc(team.name||'')}</td><td>${esc(team.coach_name||'—')}</td><td>${libraryVariant(team,1)}</td><td>${libraryVariant(team,2)}</td><td class="tiny muted">${team.error?esc(team.error):team.available===false?'暂不可用':'可用'}</td>${real(team)}</tr>`).join('');
 const head=own?'<th>球队</th><th>教练</th><th>第一套</th><th>第二套</th><th>状态</th><th>真实战术</th>':'<th>球队</th><th>教练</th><th>第一套</th><th>第二套</th><th>状态</th>';
 const table=teams.length?`<div class="table-scroll"><table class="library-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`:`<p class="tiny muted">没有找到对手球队</p>`;
 const details=failures.length?`<details><summary>失败 ${failures.length} 项</summary>${failures.map(f=>`<p class="tiny">${esc(f.name||'')}：${esc(f.error||'读取失败')}</p>`).join('')}</details>`:'';
 const summary=report.real?.variant_count&&!reading?`<div class="notice">真实AI战术已就绪：${report.real.count} 队 / ${report.real.variant_count} 套 · 用时 ${Math.round(report.real.elapsed_seconds||0)} 秒</div>`:'';
 const realFailures=(report.real?.failures||[]).length?`<details><summary>真实战术失败 ${report.real.failures.length} 项</summary>${report.real.failures.map(f=>`<p class="tiny">${esc(f.club||('#'+f.club_uid))} · ${esc(f.venue==='A'?'主场':'客场')}：${esc(f.error||'生成失败')}</p>`).join('')}</details>`:'';
 const bar=own&&reading?`<div class="real-progress" role="status"><div class="real-progress-track"><div class="real-progress-bar" style="width:${pct}%"></div></div><p class="tiny muted">${esc(progress.stage||'正在生成真实AI战术')}</p></div>`:'';
 const hint=own?'<p class="tiny muted">真实战术对每个对手生成对手主场、对手客场两套；由本机原版引擎准备，首次较慢。这是受控预览上下文输出，正式比赛由游戏内 AI 重新生成，本工具不逐场重算。</p>':'';
 const realButton=own?`<button id="library-real-all" class="button" ${reading?'disabled':''}>${report.real?.variant_count?'补齐缺失的真实战术':'生成全部真实战术'}</button>`:'';
 const controls=`<div class="save-team-controls"><label>导出目录<input id="library-directory" value="${esc(libraryDirectory())}" placeholder="选择本机文件夹"></label><button id="library-folder" class="button">选择目录…</button><button id="library-export" class="button" ${reading?'disabled':''}>导出全部战术</button><button id="library-pool" class="button primary" ${reading?'disabled':''}>加入随机候选</button>${realButton}</div>`;
 return `${summary}${realFailures}${bar}${table}${details}${hint}${controls}${libraryExportResult()}`;
}
function libraryLeagueCard(){
 if(!libraryLeague)return '';
 const league=libraryLeagueData()||{},meta=[];
 if(league.nation)meta.push(`<span class="tag">${esc(league.nation)}</span>`);
 if(league.club_count)meta.push(`<span class="tag">${league.club_count} 队</span>`);
 const name=league.name||'联赛';
 const body=libraryReport?libraryReportBody(libraryReport):libraryLeagueError?`<p class="tiny muted">联赛战术读取失败</p><button id="library-league-retry" class="button small">重试</button>`:`<div class="notice" role="status" id="library-stage">${esc(libraryStage||'正在读取联赛战术')}</div>`;
 return `<div class="card"><div class="card-head"><h2>${esc(name)}</h2>${meta.length?`<div class="save-team-controls">${meta.join('')}</div>`:''}</div><div class="card-body">${body}</div></div>`;
}
function libraryEmptyDetail(){
 if(!librarySave||librarySave.status!=='complete'||!libraryLeagues)return '';
 if(libraryLeague)return '';
 return `<div class="card"><div class="card-body"><p class="tiny muted">选择联赛查看球队与战术</p></div></div>`;
}
function libraryView(){return `${librarySaveCard()}<div class="library-layout"><div class="library-leagues">${libraryLeaguesCard()}</div><div class="library-detail">${libraryLeagueCard()}${libraryEmptyDetail()}</div></div>`}
function bindLibrary(){
 if(view!=='library')return;
 if($('#library-pick'))$('#library-pick').onclick=async()=>{try{const r=await api('/api/save/pick',{});if(r.path){$('#library-path').value=r.path;readLibrary()}}catch(e){toast(e.message)}};
 if($('#library-read'))$('#library-read').onclick=readLibrary;
 if($('#library-path'))$('#library-path').onkeydown=event=>{if(event.key==='Enter')readLibrary()};
 $$('[data-league]').forEach(button=>button.onclick=()=>selectLibraryLeague(button.dataset.league));
 const search=$('#library-league-search');
 if(search)search.oninput=()=>{
  librarySearch=search.value;
  const query=librarySearch.trim().toLowerCase();let visible=0;
  $$('[data-league-group]').forEach(group=>{
   let count=0;
   group.querySelectorAll('[data-league]').forEach(row=>{const match=!query||row.dataset.leagueSearch.includes(query);row.hidden=!match;if(match)count++});
   group.hidden=!count;visible+=count;
  });
  const empty=$('#library-league-empty');if(empty)empty.hidden=visible>0;
 };
 if($('#library-leagues-retry'))$('#library-leagues-retry').onclick=loadLibraryLeagues;
 if($('#library-league-retry'))$('#library-league-retry').onclick=loadLibraryLeague;
 if($('#library-folder'))$('#library-folder').onclick=async()=>{try{const r=await api('/api/save/pick-folder',{});if(r.path){localStorage.setItem('fm27-export-directory',r.path);$('#library-directory').value=r.path}}catch(e){toast('选择目录失败：'+e.message)}};
 if($('#library-export'))$('#library-export').onclick=exportLibrary;
 if($('#library-pool'))$('#library-pool').onclick=importLibraryPool;
 if($('#library-real-all'))$('#library-real-all').onclick=generateLibraryReal;
 $$('[data-real-tactic]').forEach(button=>button.onclick=()=>generateRealTeam(button));
}
async function readLibrary(){
 const path=$('#library-path')?.value.trim()||'';
 if(!path){toast('请填写存档完整路径');return}
 if(librarySave?.status==='reading')return;
 clearTimeout(libraryTimer);
 libraryLeagueToken++;
 librarySave={id:null,status:'reading',stage:'正在读取存档',source:path};
 libraryLeagues=null;libraryLeaguesLoading=false;libraryLeaguesError='';libraryLeague=null;libraryReport=null;libraryLeagueError=false;libraryExport=null;libraryStage='';librarySearch='';libraryRealProgress=null;libraryRealToken++;
 libraryRefresh();
 try{
  const result=await api('/api/save/import',{path});
  librarySave={id:result.id,status:'reading',stage:result.reused?'存档未变化，复用已解析数据':'正在读取存档',source:path};
  if(result.reused)toast('存档未变化，已复用解析结果');
  libraryRefresh();pollLibrary();
 }catch(e){librarySave={...librarySave,status:'error',stage:'读取存档失败'};toast('读取存档失败：'+e.message);libraryRefresh()}
}
async function pollLibrary(){
 clearTimeout(libraryTimer);
 const id=librarySave?.id;if(!id)return;
 try{
  const value=await api('/api/save/status?id='+id);
  if(librarySave?.id!==id)return;
  librarySave={...librarySave,...value};
  if(value.status==='complete')librarySave.stage='';
  if(value.status==='reading'){libraryRefresh();libraryTimer=setTimeout(pollLibrary,1500);return}
  libraryStage='';
  if(value.status==='error'){toast(value.stage||'存档读取失败');libraryRefresh();return}
  libraryRefresh();
  await loadLibraryLeagues();
 }catch(e){
  if(librarySave?.id!==id)return;
  librarySave={...librarySave,status:'error',stage:'存档读取失败'};
  toast(e.message);libraryRefresh();
 }
}
async function loadLibraryLeagues(){
 const id=librarySave?.id;if(!id)return;
 libraryLeagues=null;libraryLeaguesError='';libraryLeaguesLoading=true;libraryRefresh();
 try{
  const value=await api('/api/save/leagues',{id});
  if(librarySave?.id!==id)return;
  libraryLeagues=value;libraryLeaguesLoading=false;
  if(value.save)librarySave={...librarySave,...value.save};
  if(libraryLeague&&!(value.leagues||[]).some(league=>league.key===libraryLeague)){libraryLeague=null;libraryReport=null;libraryExport=null;libraryLeagueError=false}
  libraryRefresh();
  if(libraryLeague)await loadLibraryLeague();
 }catch(e){
  if(librarySave?.id!==id)return;
  libraryLeaguesLoading=false;libraryLeaguesError=e.message;libraryRefresh();
  toast('联赛列表读取失败：'+e.message);
 }
}
function selectLibraryLeague(key){
 if(libraryLeague===key)return;
 libraryLeague=key;libraryReport=null;libraryExport=null;libraryLeagueError=false;libraryRealProgress=null;libraryRealToken++;
 libraryRefresh();
 loadLibraryLeague();
}
async function loadLibraryLeague(){
 const id=librarySave?.id,key=libraryLeague;if(!id||!key)return;
 const token=++libraryLeagueToken;
 libraryReport=null;libraryExport=null;libraryLeagueError=false;libraryStage='正在读取联赛战术';libraryRefresh();
 try{
  const report=await libraryRequest('/api/save/league-library',{id,league:key},stage=>librarySetStage(stage),()=>token===libraryLeagueToken);
  if(!report||librarySave?.id!==id||libraryLeague!==key)return;
  if(report.status==='error')throw Error(report.stage||'联赛战术读取失败');
  libraryReport=report;libraryStage='';libraryRefresh();
 }catch(e){
  if(librarySave?.id!==id||libraryLeague!==key)return;
  libraryStage='';libraryLeagueError=true;toast('联赛战术读取失败：'+e.message);libraryRefresh();
 }
}
async function exportLibrary(){
 const directory=$('#library-directory')?.value.trim()||'',button=$('#library-export');
 if(!librarySave?.id||!libraryLeague)return;
 if(!directory){toast('请填写或选择导出目录');return}
 if(button){button.disabled=true;button.textContent='正在导出中…'}
 try{
  const result=await api('/api/save/league-export',{id:librarySave.id,league:libraryLeague,directory});
  localStorage.setItem('fm27-export-directory',directory);
  libraryExport=result;libraryRefresh();
  const skipped=result.skipped?.length||0;
  toast(`${result.source==='real_ai'?'已导出真实AI战术':result.source==='mixed'?'已导出真实AI战术与预设':'已导出'} ${result.files?.length||0} 个文件到 ${result.directory||directory}${skipped?'，遗漏 '+skipped+' 套':''}${result.scenario.away_tactic_pool?.enabled?'':'；需要时勾选底部的随机对手战术'}`);
 }catch(e){toast('导出失败：'+e.message);if($('#library-export')){$('#library-export').disabled=false;$('#library-export').textContent='导出全部战术'}}
}
async function generateRealTeam(button){
 const id=librarySave?.id,league=libraryLeague;if(!id||!league)return;
 const label=button.textContent;button.disabled=true;button.textContent='生成中';
 libraryRealProgress={status:'reading',done:0,total:2,stage:'正在生成真实AI战术'};libraryRefresh();
 try{
  const result=await api('/api/save/real-generation',{id,league,club_uid:+button.dataset.realTactic,force:true});
  if(result.status!=='complete')throw Error(result.stage||'真实AI战术生成失败');
  libraryRealProgress=null;
  await loadLibraryLeague();
  toast(`已生成真实AI战术 ${result.variant_count||0} 套`);
 }catch(e){libraryRealProgress=null;libraryRefresh();toast('真实战术生成失败：'+e.message);button.disabled=false;button.textContent=label}
}
async function generateLibraryReal(){
 const id=librarySave?.id,league=libraryLeague;if(!id||!league)return;
 const token=++libraryRealToken;
 libraryRealProgress={status:'reading',done:0,total:0,stage:'正在读取教练与阵容'};libraryRefresh();
 try{
  const started=await api('/api/save/real-generation',{id,league,force:false});
  if(started.status==='complete'){libraryRealProgress=null;await loadLibraryLeague();toast(`真实AI战术已就绪 ${started.variant_count||0} 套`);return}
  libraryRealProgress=started;libraryRefresh();
  await pollLibraryReal(token,id,league);
 }catch(e){if(token!==libraryRealToken)return;libraryRealProgress=null;libraryRefresh();toast('真实战术生成失败：'+e.message)}
}
async function pollLibraryReal(token,id,league){
 while(token===libraryRealToken){
  await new Promise(resolve=>setTimeout(resolve,1000));
  if(token!==libraryRealToken||librarySave?.id!==id||libraryLeague!==league)return;
  let value;
  try{value=await api('/api/save/real-generation-status',{id,league})}
  catch(e){libraryRealProgress=null;libraryRefresh();toast('真实战术生成状态读取失败：'+e.message);return}
  libraryRealProgress=value;
  if(value.status==='reading'){libraryRefresh();continue}
  if(value.status==='error'){libraryRealProgress=null;libraryRefresh();toast('真实战术生成失败：'+(value.stage||'未知错误'));return}
  libraryRealProgress=null;
  await loadLibraryLeague();
  toast(`真实AI战术已生成 ${value.count||0} 队 / ${value.variant_count||0} 套`);
  return;
 }
}
async function importLibraryPool(){
 const button=$('#library-pool');if(!button||!librarySave?.id||!libraryLeague)return;
 button.disabled=true;button.textContent='正在导入…';
 try{
  const result=await libraryRequest('/api/save/league-pool',{id:librarySave.id,league:libraryLeague,scenario:clone(state)},stage=>{if(button)button.textContent=stage||'正在导入…'});
  if(result.status==='error')throw Error(result.stage||'加入随机候选失败');
  state=result.scenario;save();
  const skipped=result.skipped?.length||0;
  toast(`已导入 ${result.imported?.length||0} 套${result.source==='real_ai'?'真实AI战术':result.source==='mixed'?'真实AI战术与预设':'战术'}${skipped?'，遗漏 '+skipped+' 套':''}${result.scenario.away_tactic_pool?.enabled?'':'；需要时勾选底部的随机对手战术'}`);
  randomSelectionPending=false;randomOptionsOpen=false;
  view='tactics';render();
 }catch(e){toast('加入随机候选失败：'+e.message);if($('#library-pool')){$('#library-pool').disabled=false;$('#library-pool').textContent='加入随机候选'}}
}
const libraryBindPrevious=bind;
bind=function(){libraryBindPrevious();bindLibrary()};
