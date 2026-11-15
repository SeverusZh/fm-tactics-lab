"""Bounded, cancellable native process pool. Every match retains process isolation."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import ctypes
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from fm27_simulator import inspect_log
import fm27_match_events

def resource_limits(logical_cpus,available_bytes):
    # 2494687 tests measured about 332 MiB private/host. Budget 1 GiB per
    # slot (including headroom), plus 2 GiB for the editor and other work.
    slots=max(1,(available_bytes-2*1024**3)//1024**3)
    maximum=max(1,min(8,max(1,logical_cpus//2),slots))
    return {'maximum':256,'recommended':min(4,maximum),'resource_suggested_maximum':maximum,
            'memory_budget_per_worker_mib':1024,'memory_reserve_mib':2048}


def worker_limits():
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong)for n in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
    memory=Memory();memory.length=ctypes.sizeof(memory)
    available=8*1024**3
    if os.name=='nt'and ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):available=memory.available
    return resource_limits(os.cpu_count()or 2,available)


_owner_job=None
_owner_job_pid=None
_owner_job_lock=threading.Lock()

def own_child_processes():
    global _owner_job,_owner_job_pid
    if os.name!='nt':return None
    with _owner_job_lock:
        if _owner_job is not None and _owner_job_pid==os.getpid():return _owner_job
        _owner_job=_new_child_process_job();_owner_job_pid=os.getpid();return _owner_job

def _new_child_process_job():
    """Keep this Windows job handle open: service exit also kills its match hosts.

    Descendants inherit the job, including each host's private native child.
    The handle is deliberately retained until OS process teardown.
    """
    if os.name!='nt':return None
    from ctypes import wintypes
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',wintypes.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',ctypes.c_ulonglong*6),('limits',ctypes.c_size_t*4)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateJobObjectW(None,None);limits=Extended();limits.basic.flags=0x2000
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits))or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        error=ctypes.get_last_error()
        if handle:kernel.CloseHandle(handle)
        raise ctypes.WinError(error)
    return handle

class BatchCancelled(Exception):pass

class MatchCancellation:
    """A per-match event: only this host's session is asked to exit."""
    def __init__(self):
        self.handle=None;self.name=None
        if os.name!='nt':return
        from ctypes import wintypes
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateEventW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype=wintypes.HANDLE
        self.kernel.SetEvent.argtypes=[wintypes.HANDLE];self.kernel.SetEvent.restype=wintypes.BOOL
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE];self.kernel.CloseHandle.restype=wintypes.BOOL
        self.name=f'Local\\FM27MatchCancel_{os.getpid()}_{uuid.uuid4().hex}'
        self.handle=self.kernel.CreateEventW(None,True,False,self.name)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
    def signal(self):
        if self.handle and not self.kernel.SetEvent(self.handle):raise ctypes.WinError(ctypes.get_last_error())
    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None

class BatchRunner:
    def __init__(self,root,workers=1,retries=1,timeout=190):
        self.root=Path(root);self.workers=workers;self.retries=retries;self.timeout=timeout
        self.stop=threading.Event();self.lock=threading.Lock();self.processes={};self.active={};self.cancellations={}
        self.cleanup_timeout=15
    def cancel(self):
        self.stop.set()
        with self.lock:
            for cancellation in self.cancellations.values():cancellation.signal()
    def communicate(self,process,cancellation,path):
        deadline=time.monotonic()+self.timeout;grace=None;reason=None
        while True:
            now=time.monotonic()
            if reason is None and (self.stop.is_set()or now>=deadline):
                reason='cancelled'if self.stop.is_set()else'timeout'
                cancellation.signal();grace=now+self.cleanup_timeout
            if grace is not None and now>=grace:
                process.kill();stdout,_=process.communicate()
                Path(str(path)+'.lifecycle.json').write_text(json.dumps({'reason':reason,'graceful_cleanup_seconds':self.cleanup_timeout,'forced_termination':True,'steam_cleanup_not_confirmed':True}),encoding='utf8')
                if reason=='cancelled':raise BatchCancelled()
                raise RuntimeError('原生宿主超时，清理等待超时后强制结束；Steam释放未确认')
            try:stdout,_=process.communicate(timeout=min(.25,max(.01,(grace or deadline)-now)))
            except subprocess.TimeoutExpired:continue
            if reason:Path(str(path)+'.lifecycle.json').write_text(json.dumps({'reason':reason,'forced_termination':False,'exit_code':process.returncode}),encoding='utf8')
            if reason=='cancelled':raise BatchCancelled()
            if reason=='timeout':raise RuntimeError('原生宿主超时，已请求正常清理后退出')
            return stdout
    def command(self,task,path):
        command=[str(self.root/'fm27_native/FM27Simulator.exe'),'--output',str(path),'--tick-step',str(task.get('tick_step',1))]
        if task['seed']is not None:command+=['--seed',str(task['seed'])]
        if task.get('config'):command+=['--scenario-file',str(task['config'])]
        if task.get('fixture'):command+=['--fixture',str(task['fixture'])]
        return command
    def one(self,task):
        began=time.perf_counter();attempts=[]
        for attempt in range(self.retries+1):
            if self.stop.is_set():raise BatchCancelled()
            path=Path(task['path']);path=path if attempt==0 else path.with_name(path.stem+f'.retry{attempt}'+path.suffix)
            process=None;cancellation=None
            try:
                with self.lock:
                    if self.stop.is_set():raise BatchCancelled()
                    environment=os.environ.copy()
                    if task.get('episode'):
                        episode=task['episode'];environment.update(FM27_EPISODE_TYPE=str(episode['type']),FM27_EPISODE_SIDE=str(episode['attacking_side']),FM27_EPISODE_SECONDS=str(episode['window_seconds']))
                    cancellation=MatchCancellation();command=self.command(task,path)
                    if cancellation.name:command+=['--cancel-event',cancellation.name]
                    process=subprocess.Popen(command,cwd=self.root,env=environment,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    self.processes[task['key']]=process
                    self.cancellations[task['key']]=cancellation
                    self.active[task['key']]={'seed':task['seed'],'variant':task['variant'],'attempt':attempt+1}
                stdout=self.communicate(process,cancellation,path)
                if self.stop.is_set():raise BatchCancelled()
                if process.returncode:raise RuntimeError(f'原生宿主退出 {process.returncode}: {stdout.decode(errors="replace")[-200:]}')
                rows=[json.loads(line)for line in path.read_text(encoding='utf8').splitlines()if line]
                compatibility=next((r for r in rows if r.get('event')=='native_engine_compatibility'),None)
                if not compatibility or not (compatibility.get('compatible')or compatibility.get('trial_allowed')):raise RuntimeError('缺少有效的原生关键接口检查')
                cleanup=next((r for r in rows if r.get('event')=='steam_session_cleanup'),None)
                if not cleanup or not cleanup.get('ok'):raise RuntimeError('本场Steam会话释放未通过校验，停止接纳本场')
                episode=next((r for r in rows if r.get('event')=='native_setpiece_episode_finished'),None)
                if task.get('episode'):
                    if episode is None:raise ValueError('缺少原版定位球片段结束记录')
                    run={'result':{'event':'native_setpiece_episode_finished','full_match_completed':False,'score':[0,0],'tick':episode['end_tick'],'clock':episode['clock']},'score_changes':[r for r in rows if r.get('event')=='observed_score_change']}
                else:run=inspect_log(path)
                for event in (('native_scenario_readback_verified','native_player_tactic_bindings_verified','native_opposition_effective_verified')if task.get('config')else()):
                    if not any(r.get('event')==event for r in rows):raise RuntimeError('缺少原生校验: '+event)
                stats=next((r for r in rows if r.get('event')==('native_episode_statistics'if episode else'native_match_statistics')),None)
                events=fm27_match_events.collect(rows,task['scenario'],task['position_names'])if task.get('scenario')else None
                if episode and events:
                    if events.get('scorers_verified_against_native_totals')is False:raise ValueError('片段进球归属未通过原版终场计数核对')
                    for key in ['goals','cancelled_goals','cards']:events[key]=[r for r in events[key]if episode['found']and episode['start_tick']<r['tick']<=episode.get('window_end_tick',episode['end_tick'])]
                if episode and events:
                    run['result']['score']=[sum(g['side']==side for g in events['goals'])for side in range(2)]
                return {'variant':task['variant'],'seed':task['seed'],'result':run['result'],'episode':episode,'statistics':stats,'events':events,'score_changes':run['score_changes'],'log':path.name,'verified':True,'engine_compatibility':compatibility,'engine_dll_sha256':os.environ.get('FM27_EXPECTED_DLL_SHA256'),'elapsed_seconds':round(time.perf_counter()-began,3),'attempts':attempt+1,'retry_errors':attempts,'timings':next((r for r in rows if r.get('event')=='native_timings'),None)}
            except BatchCancelled:raise
            except Exception as error:
                attempts.append(str(error))
                if attempt==self.retries or (process is not None and process.returncode==180):
                    phase='simulation'
                    try:
                        inspect_log(path);phase='host_exit_after_match'
                    except (ValueError,OSError):pass
                    return {'variant':task['variant'],'seed':task['seed'],'failed':True,'failure_phase':phase,'errors':attempts,'attempts':attempt+1,'log':path.name}
            finally:
                with self.lock:
                    self.processes.pop(task['key'],None);self.active.pop(task['key'],None);self.cancellations.pop(task['key'],None)
                    if cancellation:cancellation.close()
                if process is not None:
                    if process.stdout:process.stdout.close()
                    handle=getattr(process,'_handle',None)
                    if handle is not None and hasattr(handle,'Close'):handle.Close()
    def run(self,tasks,on_result,on_progress=lambda active:None):
        tasks=iter(tasks);pending={};exhausted=False
        with ThreadPoolExecutor(max_workers=self.workers,thread_name_prefix='fm27-match')as pool:
            try:
                while pending or not exhausted:
                    while not exhausted and not self.stop.is_set()and len(pending)<self.workers:
                        task=next(tasks,None)
                        if task is None:exhausted=True;break
                        pending[pool.submit(self.one,task)]=task
                    if self.stop.is_set():break
                    if not pending:break
                    done,_=wait(pending,timeout=.25,return_when=FIRST_COMPLETED)
                    for future in done:
                        task=pending.pop(future)
                        try:result=future.result()
                        except BatchCancelled:continue
                        if not self.stop.is_set():on_result(result)
                    with self.lock:active=list(self.active.values())
                    on_progress(active)
            except BaseException:
                self.cancel();raise
            finally:
                if self.stop.is_set():
                    self.cancel()
                    for future in pending:future.cancel()
