"""Bounded desktop native sessions with streamed, independently validated results."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import time
import uuid

from fm27_batch import BatchRunner, MatchCancellation, own_child_processes
from fm27_simulator import inspect_log
import fm27_match_events
from desktop_storage import require_space
from desktop_execution import verify_execution_player, execution_receipts


def sha(path):
    with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,data):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(temporary,path)


def read_rows(path,live=False):
    lines=path.read_text(encoding='utf8').splitlines(keepends=True)
    return [json.loads(line)for i,line in enumerate(lines)if line.strip()and not(live and i==len(lines)-1 and not line.endswith('\n'))]


def merged_rows(receipt,rows):
    events={row['event']for row in rows}
    return receipt['session_rows']+[row for row in receipt['original_bootstrap_rows']if row['event']not in events]+rows


def inspect_saved_run(directory,run,scenario=None):
    log=directory/run['log']
    if not run.get('startup_receipt'):return inspect_log(log)
    path=(directory/run['startup_receipt']).resolve()
    if directory.resolve()not in path.parents or sha(path)!=run['startup_receipt_sha256']:
        raise ValueError('复用宿主启动回执已改变，无法接续此实验')
    receipt=json.loads(path.read_text(encoding='utf8'))
    rows=merged_rows(receipt,read_rows(log))
    if scenario is not None:execution_receipts(rows,scenario)
    return inspect_log(log,rows=rows)


class DesktopWarmRunner(BatchRunner):
    jobs_per_session=64
    _capabilities_cache={}
    postprocess_workers=2

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.session_diagnostics=[]
        self._abort=False
        self.host_sha256=sha(self.root/'fm27_native/FM27Simulator.exe')
        if self.host_sha256 not in self._capabilities_cache:
            result=subprocess.run([str(self.root/'fm27_native/FM27Simulator.exe'),'--worker-capabilities'],
                capture_output=True,timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:value=json.loads(result.stdout)if result.returncode==0 else {}
            except (ValueError,UnicodeError):value={}
            self._capabilities_cache[self.host_sha256]=value
        self.capabilities=self._capabilities_cache[self.host_sha256]
        maximum=self.capabilities.get('max_jobs')
        valid_limit=type(maximum)is int and 1<=maximum<=1000000
        self.counted_sessions=(valid_limit and self.capabilities.get('protocol')==2 and
            self.capabilities.get('execution_context_reset')is True and
            self.capabilities.get('per_match_resource_release')is True)


    def session_size(self, lanes, execution):
        if self.counted_sessions:return min(max(map(len,lanes)),self.capabilities['max_jobs'])
        return 1 if execution else self.jobs_per_session

    def postprocess(self,task,rows,receipt,path,ack,submitted,queued):
        began=time.perf_counter()
        checked=inspect_log(path,rows=merged_rows(receipt,rows))
        for event in ['native_scenario_readback_verified','native_player_tactic_bindings_verified','native_opposition_effective_verified','native_event_observer_stopped','original_match_release_completed']:
            if not any(r['event']==event for r in rows):raise ValueError('缺少原生校验：'+event)
        if 'native_generation'in task['scenario']:
            generated=[r for r in rows if r.get('event')=='source_generation_readback']
            if len(generated)!=2 or not all(r.get('staff_player_identity_and_attributes_verified')and r.get('native_adaptation_verified')for r in generated):raise ValueError('电脑生成战术或源身份未通过回读')
            if not any(r.get('event')=='native_fresh_duel_competition_context'and r.get('carrier_competition_discarded')for r in rows):raise ValueError('新对战赛事上下文未通过核实')
            if task.get('event_details',True)and not any(r.get('event')=='native_player_statistics_identity_verified'and r.get('verified')for r in rows):raise ValueError('球员统计未通过原生身份核对')
        if self.counted_sessions and not any(r.get('event')=='native_execution_context_cleared'and r.get('team_bindings_cleared')for r in rows):raise ValueError('逐场执行力上下文未清除')
        released=next(r for r in rows if r['event']=='original_match_release_completed')
        if not released['tls_context_cleared']:raise ValueError('上一场原生线程上下文未清除')
        execution = execution_receipts(rows, task['scenario'])
        statistics=next((r for r in rows if r['event']=='native_match_statistics'),None)
        if not statistics or len(statistics['teams'])!=2:raise ValueError('缺少原生球队统计')
        for team in statistics['teams']:
            if not(0<=team['completed_passes']<=team['passes']and 0<=team['shots_on_target']<=team['shots']and math.isfinite(team['xg'])and team['xg']>=0):raise ValueError('原生球队统计范围异常')
        score=checked['result']['score']
        if len(score)!=2 or any(type(value)is not int or value<0 for value in score):raise ValueError('原生终场比分无效')
        if checked['score_changes']and checked['score_changes'][-1]['score']!=score:raise ValueError('原生比分变化与终场比分不一致')
        event_details=task.get('event_details',True)
        disabled=any(r.get('event')=='native_event_details_disabled'for r in rows)
        if not event_details:
            if not disabled:raise ValueError('快速模式缺少原生事件采集关闭回执')
            if any(r.get('event')in ['native_goal_event','native_card_event','native_player_match_totals','native_final_incident_registry']for r in rows):raise ValueError('快速模式意外产生球员事件明细')
            events={'collected':False,'disabled':True,'source':'disabled_by_user','goals':[],'cards':[],
                    'reason':'快速模式仅保留原生终场比分和球队统计，未采集或校验球员事件明细'}
        else:
            if disabled:raise ValueError('完整模式的原生事件采集被意外关闭')
            events=fm27_match_events.collect(rows,task['scenario'],task['position_names'])
            if not events.get('collected')or not events.get('scorers_verified_against_native_totals')or not events.get('cards_verified_against_native_totals'):
                detail=json.dumps(events.get('integrity',{'collected':events.get('collected')}),ensure_ascii=False,separators=(',',':'))
                raise ValueError('进球或红黄牌未通过原生计数核对；诊断：'+detail)
            if [sum(g['side']==side for g in events['goals'])for side in range(2)]!=score:
                raise ValueError('进球事件与原生比分不一致')
        timings=next(r for r in rows if r['event']=='native_timings')
        return {'variant':task['variant'],'seed':task['seed'],'result':checked['result'],'episode':None,
                **({'experimental_execution':execution} if execution is not None else {}),
                'generated_plans':[r for r in rows if r.get('event')=='source_generation_readback'],
                'statistics':statistics,'events':events,'score_changes':checked['score_changes'],'log':path.name,
                'verified':True,'attempts':1,'retry_errors':[],'timings':timings,
                'elapsed_seconds':round(time.perf_counter()-submitted,3),
                'elapsed_scope':'session_submission_through_postprocess_including_queue',
                'postprocess_seconds':time.perf_counter()-began,'postprocess_queue_seconds':began-queued,
                'native_elapsed_seconds':timings['total_ms']/1000,'native_elapsed_scope':'job_pipeline_excludes_session_DLL_load_and_activation','engine_compatibility':receipt['compatibility'],
                'engine_dll_sha256':receipt['dll_sha256'],'collector_sha256':self.host_sha256,
                'runtime_mode':'reused_execution_worker' if execution is not None and self.counted_sessions else 'isolated_execution_experiment' if execution is not None else 'reused_native_worker','event_details':event_details,
                'validation_scope':'native_match_score_team_statistics_and_player_events'if event_details else'native_match_score_and_team_statistics',
                'worker_pid':ack['pid'],'worker_job_index':ack['index'],
                'startup_receipt':str(receipt['_path'].relative_to(path.parent)),
                'startup_receipt_sha256':receipt['_sha256']}

    def run(self,tasks,on_result,on_progress=lambda active:None):
        tasks=list(tasks)
        if not tasks:return
        if any(type(t.get('event_details',True))is not bool for t in tasks):raise ValueError('事件明细开关必须为布尔值')
        if len({t.get('event_details',True)for t in tasks})!=1:raise ValueError('同一批次不能混合快速与完整模式')
        own_child_processes()
        if any(t.get('episode')for t in tasks):raise ValueError('定位球片段须使用独立片段入口')
        messages=queue.Queue(maxsize=6)
        lanes=[tasks[i::self.workers]for i in range(min(self.workers,len(tasks)))]
        # New hosts reset per-match execution state; old hosts retain isolation.
        session_size=self.session_size(lanes,any('experimental_execution'in task['scenario']for task in tasks))
        chunks=[lane[offset:offset+session_size]for offset in range(0,max(map(len,lanes)),session_size)for lane in lanes if lane[offset:offset+session_size]]

        def publish(message):
            while not self._abort:
                try:messages.put(message,timeout=.1);return
                except queue.Full:pass

        def session(chunk):
            if self.stop.is_set():return
            root=Path(chunk[0]['path']).parent
            require_space(root,additional_bytes=min(len(chunk),64)*3*1024**2)
            folder=root/'worker_sessions'/uuid.uuid4().hex;folder.mkdir(parents=True)
            startup=folder/'session.jsonl';manifest=folder/'manifest.txt';fields=['FM27DW2',str(len(chunk))]if self.counted_sessions else ['FM27DW1']
            for task in chunk:
                path=Path(task['path'])
                if path.exists():
                    # Only an explicitly resumed batch can reach an existing
                    # path. Keep cancelled/failed attempts and their seeds.
                    for attempt in range(1,10000):
                        other=path.with_name(path.stem+f'.resume{attempt}'+path.suffix)
                        if not other.exists()and not Path(str(other)+'.worker_done').exists():break
                    else:raise ValueError('过多已有尝试记录，须检查现场')
                    task['path']=other
                path=Path(task['path']);path.parent.mkdir(parents=True,exist_ok=True)
                values=[str(Path(task.get('fixture')or self.root/'fm27_native/fixtures/match.pkm').resolve()),
                        str(Path(task['config']).resolve()),str(path.resolve()),str(task['seed']),str(Path(task['dump']).resolve())if task.get('dump')else'-']
                if any('\n'in x or '\r'in x for x in values):raise ValueError('任务路径包含换行符')
                fields.extend(values)
            manifest.write_text('\n'.join(fields)+'\n',encoding='utf8',newline='\n')
            cancellation=MatchCancellation();process=None;key=folder.name;completed=0;receipt=None;failure=None
            began=last_progress=time.perf_counter();cancel_started=None
            try:
                env=os.environ.copy()
                env.pop('FM27_SKIP_EVENT_DETAILS',None)
                if not chunk[0].get('event_details',True):
                    env['FM27_SKIP_EVENT_DETAILS']='1'
                    env.pop('FM27_DESKTOP_EVENTS_AUDIT',None)
                for name in list(env):
                    if name.startswith(('FM27_IMPORT_','FM27_EXPORT_','FM27_EPISODE_','FM27_SAVE_SECTION_','FM27_SAVED_CORE_','FM27_AI_'))or name=='FM27_DESKTOP_STATS_AUDIT':env.pop(name)
                command=[str(self.root/'fm27_native/FM27Simulator.exe'),'--worker-manifest',str(manifest),
                         '--output',str(startup),'--tick-step','1','--cancel-event',cancellation.name]
                with self.lock:
                    if self.stop.is_set():return
                    process=subprocess.Popen(command,cwd=self.root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                    self.processes[key]=process;self.cancellations[key]=cancellation
                while True:
                    while completed<len(chunk)and Path(str(chunk[completed]['path'])+'.worker_done').exists():
                        task=chunk[completed];path=Path(task['path']);rows=read_rows(path)
                        ack=json.loads(Path(str(path)+'.worker_done').read_text(encoding='utf8'))
                        if not(ack['released']and ack['exit_code']==0 and ack['index']==completed+1):raise ValueError('原生逐场释放标记无效')
                        if receipt is None:
                            header=read_rows(startup,live=True)
                            compatibility=next(r for r in header if r['event']=='native_engine_compatibility')
                            if not (compatibility.get('compatible')or compatibility.get('trial_allowed')):raise ValueError('原生关键接口检查失败')
                            bootstrap=[r for r in rows if r['event']in['host_icu_data_initialized','native_engine_bootstrap_returned']]
                            if len(bootstrap)!=2:raise ValueError('首场缺少真实初始化回执')
                            receipt={'session_rows':header,'original_bootstrap_rows':bootstrap,'host_sha256':self.host_sha256,
                                     'dll_sha256':next(r['sha256']for r in header if r['event']=='native_image_fingerprint'),
                                     'compatibility':compatibility,'worker_pid':ack['pid']}
                            save(folder/'startup_receipt.json',receipt)
                            receipt['_path']=folder/'startup_receipt.json';receipt['_sha256']=sha(receipt['_path'])
                        publish(('match',(task,rows,receipt,path,ack,began,time.perf_counter())))
                        completed+=1;last_progress=time.perf_counter()
                        if completed%64==0 and completed<len(chunk):require_space(root,additional_bytes=min(len(chunk)-completed,64)*3*1024**2)
                    if process.poll()is not None:
                        if completed<len(chunk)and Path(str(chunk[completed]['path'])+'.worker_done').exists():continue
                        break
                    now=time.perf_counter()
                    with self.lock:self.active[key]={'variant':chunk[min(completed,len(chunk)-1)]['variant'],
                        'seed':chunk[min(completed,len(chunk)-1)]['seed'],'worker_completed':completed,'worker_total':len(chunk)}
                    timed_out=now-last_progress>(self.cleanup_timeout if completed==len(chunk)else self.timeout)
                    if self.stop.is_set()or timed_out:
                        if cancel_started is None:
                            cancellation.signal();cancel_started=now
                            if timed_out:failure='原生宿主无进展，已请求取消并保留现场'
                        elif now-cancel_started>self.cleanup_timeout:
                            process.kill();process.wait();failure='原生宿主清理超时，强制终止并保留现场'
                    time.sleep(.02)
                output=process.communicate()[0].decode(errors='replace')
                final=read_rows(startup,live=True)if startup.exists()else[]
                cleanup=next((r for r in final if r['event']=='steam_session_cleanup'),None)
                record={'returncode':process.returncode,'completed':completed,'expected':len(chunk),'failure':failure,
                        'stdout':output,'wall_seconds':time.perf_counter()-began,'manifest_sha256':sha(manifest),
                        'steam_session_cleanup':cleanup,'session_log':str(startup.relative_to(root))}
                save(folder/'lifetime.json',record)
                with self.lock:self.session_diagnostics.append(record)
                if completed==len(chunk)and process.returncode in[0,180]:
                    if process.returncode==180 or not cleanup or not cleanup.get('ok'):
                        record['warning']='比赛已逐场完整释放；会话的 Steam 清理未确认，原始诊断已保留'
                        save(folder/'lifetime.json',record)
                elif process.returncode==86 and self.stop.is_set()and not failure:
                    pass  # explicit cancellation; partial log remains unaccepted
                else:
                    current=chunk[min(completed,len(chunk)-1)]
                    publish(('failure',{'variant':current['variant'],'seed':current['seed'],'failed':True,
                        'failure_phase':'native_session','errors':[failure or f'原生会话退出 {process.returncode}，已完成 {completed}/{len(chunk)}'],
                        'attempts':1,'log':Path(current['path']).name,'session_receipt':str((folder/'lifetime.json').relative_to(root))}))
                    publish(('error',RuntimeError('原生会话异常；已完成场次和失败现场均保留，不自动重跑')))
            except BaseException as error:
                if process is not None and process.poll()is None:
                    cancellation.signal()
                    try:process.wait(timeout=self.cleanup_timeout)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                save(folder/'failure.json',{'error':repr(error),'completed':completed,'expected':len(chunk),'entered_logs_and_seeds_retained':True})
                publish(('error',error))
            finally:
                with self.lock:self.processes.pop(key,None);self.cancellations.pop(key,None);self.active.pop(key,None)
                cancellation.close()
                if process is not None:
                    if process.stdout:process.stdout.close()
                    handle=getattr(process,'_handle',None)
                    if handle is not None and hasattr(handle,'Close'):handle.Close()

        error=None
        with ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='fm27-desktop-session')as native,ThreadPoolExecutor(max_workers=self.postprocess_workers,thread_name_prefix='fm27-desktop-post')as post:
            sessions=[native.submit(session,chunk)for chunk in chunks];pending={}
            try:
                while any(not future.done()for future in sessions)or pending or not messages.empty():
                    try:
                        if len(pending)<6:
                            kind,value=messages.get(timeout=.02)
                            if kind=='match':pending[post.submit(self.postprocess,*value)]=value[0]
                            elif kind=='failure':on_result(value)
                            elif kind=='error':
                                if error is None:error=value
                                self.cancel()
                    except queue.Empty:pass
                    for future in list(pending):
                        if not future.done():continue
                        task=pending.pop(future)
                        try:on_result(future.result())
                        except BaseException as caught:
                            if error is None:error=caught
                            self.cancel()
                            on_result({'variant':task['variant'],'seed':task['seed'],'failed':True,'failure_phase':'postprocessing',
                                       'errors':[repr(caught)],'attempts':1,'log':Path(task['path']).name})
                    with self.lock:active=list(self.active.values())
                    on_progress(active)
                for future in sessions:
                    try:future.result()
                    except BaseException as caught:
                        if error is None:error=caught
            except BaseException:
                self._abort=True;self.cancel()
                for future in sessions:future.cancel()
                raise
        if error is not None:raise error
