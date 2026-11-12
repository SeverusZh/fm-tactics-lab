'use strict';
const experimentLabel=document.createElement('label');experimentLabel.innerHTML='实验名称<input id="experiment-name" maxlength="100" placeholder="留空自动命名">';
$('#seed').closest('label').before(experimentLabel);
const executionOptions=document.createElement('details');
executionOptions.className='card experiment-panel';
const executionComponents=[
 ['understanding','战术理解',50],['buy_in','教练认可',25],
 ['opposition','对手情报',15],
];
executionOptions.innerHTML=`
 <summary>战术执行力实验</summary>
 <p class="tiny muted">分别设置双方的三项分数。球员能力贡献按每名球员的 CA 和两阶段角色适配自动计算。</p>
 <label><input id="execution-enabled" type="checkbox">启用</label>
 <div class="table-scroll"><table>
  <thead><tr><th scope="col">分项</th><th scope="col">己方</th><th scope="col">对方</th></tr></thead>
  <tbody>${executionComponents.map(([key,label,weight])=>`<tr>
   <th scope="row">${label} · ${weight}%</th>
   ${['己方','对方'].map((name,i)=>`<td><input id="execution-${i}-${key}" data-execution-component
    aria-label="${name}${label}" type="number" min="0" max="100" step="1" value="70" disabled></td>`).join('')}
  </tr>`).join('')}<tr><th scope="row">球员能力贡献 · 10%</th><td colspan="2">逐球员自动计算</td></tr></tbody>
 </table></div>`;
$('#engine-settings').after(executionOptions);
$('#execution-enabled').onchange=()=>{
 for(const input of $$('[data-execution-component]'))input.disabled=!$('#execution-enabled').checked;
};
const workspaceApiPrevious=api;
api=async function(url,data){
 if(url==='/api/run'&&data){
  data={...data,name:$('#experiment-name').value.trim()||undefined};
  if(data.scenario?.away_tactic_pool?.enabled&&data.reference?.away_tactic_pool)delete data.reference.away_tactic_pool;
  delete data.scenario.experimental_execution;
  if(data.reference)delete data.reference.experimental_execution;
  if($('#execution-enabled').checked){
   const values=[0,1].map(side=>Object.fromEntries(executionComponents.map(([key,label])=>{
    const input=$(`#execution-${side}-${key}`);
    if(input.value===''||!input.checkValidity())throw Error(`${label}须为 0–100 的整数`);
    return [key,Number(input.value)];
   })));
   data.scenario={...data.scenario,experimental_execution:values};
   if(data.reference)data.reference={...data.reference,experimental_execution:values};
  }
 }
 return workspaceApiPrevious(url,data);
};
const workspaceResultsPrevious=resultsView;
resultsView=function(){
 let html=workspaceResultsPrevious();
 if(!selectedJob)return html;
 const j=selectedJob;
 if(j.experimental_execution){
  const row=j.runs[j.detailIndex??Math.max(0,j.runs.length-1)];
  const variant=row?.variant??Object.keys(j.experimental_execution)[0];
  const values=j.experimental_execution[variant];
  if(values){
   const details=values.map((value,side)=>{
    if(typeof value==='number')return `<p>${esc(j.team_names[variant][side])} · ${value}</p>`;
    const parts=executionComponents.map(([key,label])=>`${label} ${value[key]}`).join(' · ');
    if(Object.hasOwn(value,'ability')){
     const manual=executionComponents.reduce((sum,[key,,weight])=>sum+value[key]*weight,0);
     const total=Math.round((manual+10*value.ability)/100);
     return `<p>${esc(j.team_names[variant][side])} · 总分 ${total} · ${parts} · 球员能力贡献 ${value.ability}</p>`;
    }
    const scores=row?.experimental_execution?.[side]?.players?.filter(p=>p.input_ca!==undefined).map(p=>p.overall)||[];
    const min=Math.min(...scores),max=Math.max(...scores);
    const total=scores.length?` · 总分 ${min===max?min:`${min}–${max}`}`:'';
    return `<p>${esc(j.team_names[variant][side])}${total} · ${parts} · 球员能力贡献按球员计算</p>`;
   }).join('');
   html=`<div class="card experiment-panel"><strong>战术执行力实验${row?.experimental_execution?' · 原生采样已核对':''}</strong>${details}</div>`+html;
  }
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
const workspaceBindPrevious=bind;
bind=function(){workspaceBindPrevious();
 if($('#lineup-player'))[...$('#lineup-player').options].forEach(o=>o.disabled=Number(o.value)>=team().roster_size);
 if($('#sp-strategy')&&view==='setpieces'){const select=$('#sp-strategy'),value=spCurrent().strategy;if(![...select.options].some(o=>+o.value===value)){select.add(new Option('原版存储策略（代码 '+value+'）',value));select.value=value;}}
 $$('[data-job]').forEach(b=>{const h=history.find(h=>h.id===b.dataset.job);if(h){b.textContent=(h.name||'实验 '+h.id)+' · '+h.completed+'/'+h.total;b.title=new Date(h.created*1000).toLocaleString(window.FM27I18n.language);}});
 if($('#rename-experiment'))$('#rename-experiment').onclick=async()=>{const name=prompt('实验名称（1–100字）',selectedJob.name||'');if(name===null)return;try{const r=await api('/api/jobs/rename',{id:selectedJob.id,name});selectedJob.name=r.name;const h=history.find(h=>h.id===r.id);if(h)h.name=r.name;if(polledJob?.id===r.id)polledJob.name=r.name;render();}catch(e){toast(e.message)}};
 if($('#delete-experiment'))$('#delete-experiment').onclick=e=>deleteExperiment(e.currentTarget);
 if($('#find-experiment'))$('#find-experiment').oninput=e=>$$('[data-job]').forEach(b=>b.hidden=!b.textContent.toLowerCase().includes(e.target.value.toLowerCase()));
};
