'use strict';
const formatDuration=s=>s==null?'估算中':s<60?`${Math.round(s)} 秒`:`${Math.floor(s/60)} 分 ${Math.round(s%60)} 秒`;
const batchResultsView=resultsView,batchBind=bind;
resultsView=function(){
 const html=batchResultsView(),j=selectedJob;if(!j?.batch_schema)return html;
 const resumable=['cancelled','error','interrupted'].includes(j.status)&&j.completed<j.total;
 return `<div class="card batch-status"><div class="card-head"><div><h3>批量推演 · ${j.workers} 路并行 · ${j.event_details===false?'快速模式':'完整模式'}</h3><div class="subtitle">已完成 ${j.completed} / ${j.total} 场 · 失败 ${j.failures?.length||0} 场 · ${j.matches_per_minute||0} 场/分钟</div></div><div>${resumable?'<button id="batch-resume" class="button primary">继续未完成场次</button>':''} <button id="batch-csv" class="button">导出逐场 CSV</button></div></div><div class="card-body tiny">累计用时 ${formatDuration(j.elapsed_seconds)} · ${j.status==='complete'?'全部完成':`预计剩余 ${formatDuration(j.eta_seconds)}`} · ${isComparison(j)?'同种子分别运行对照战术与本次战术':'单战术模拟，仅运行本次战术'}；${j.event_details===false?'仅保留原生终场比分和球队统计；未采集或校验射手、助攻和红黄牌明细。':''}${j.runtime_mode==='reused_native_worker'?'整场比赛复用原生宿主，失败保留现场，不自动重跑。':j.experiment_type==='setpiece_episode'?'定位球片段使用独立宿主。':'该记录使用逐场宿主。'}${j.active?.length?'<br>运行中：'+j.active.map(a=>`${esc(variantLabel(a.variant,j))} / 种子 ${a.seed}${a.attempt>1?' / 重试':''}`).join('；'):''}</div></div>${html}`;
};
bind=function(){
 batchBind();
 if($('#batch-resume'))$('#batch-resume').onclick=async()=>{try{const response=await api('/api/resume',{id:selectedJob.id,workers:Number($('#workers').value)});activeJob=response.id;await poll()}catch(e){toast(e.message)}};
 if($('#batch-csv'))$('#batch-csv').onclick=()=>{
  const header=['模式','方案','种子','主队进球','客队进球','耗时秒','尝试次数','日志'],rows=selectedJob.runs.map(r=>[selectedJob.event_details===false?'快速（仅比分/统计）':'完整',variantLabel(r.variant),r.seed,...r.result.score,r.elapsed_seconds??'',r.attempts??1,r.log]);
  const csv='\ufeff'+[header,...rows].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download=`FM27-${selectedJob.id}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 };
};
api('/api/status').then(status=>{const limits=status.batch,element=$('#workers');element.innerHTML=Array.from({length:limits.maximum},(_,i)=>`<option value="${i+1}" ${i+1===limits.recommended?'selected':''}>${i+1} 路</option>`).join('');element.title=`根据本机处理器和可用内存建议 ${limits.recommended} 路，最多 ${limits.maximum} 路`;}).catch(e=>toast(e.message));

const quickModeLabel=document.createElement('label');quickModeLabel.className='compare-toggle';
quickModeLabel.title='整场比赛仅采集比分和球队统计；不采集或校验射手、助攻、红黄牌明细。定位球片段仍使用完整模式。仅影响新任务。';
quickModeLabel.innerHTML='<input id="quick-score-mode" type="checkbox">快速模式（仅比分/统计）';
$('#run').before(quickModeLabel);
const apiBeforeQuickMode=api;
api=async function(url,data){
 if(url==='/api/run'&&data)data={...data,event_details:!$('#quick-score-mode').checked};
 return apiBeforeQuickMode(url,data);
};
window.addEventListener('DOMContentLoaded',()=>{
 const detailedEventsView=eventsView;
 eventsView=function(run){return run?.events?.disabled?'<p class="tiny muted">快速模式：本场未采集射手、助攻及红黄牌明细，比分与球队统计已核对。</p>':detailedEventsView(run);};
});
