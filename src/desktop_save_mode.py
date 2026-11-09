"""Save-backed team inputs. Stored plans never masquerade as current AI choices."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,CancelledError
import base64
import copy
import hashlib
import json
import os
import re
import secrets
import struct
import subprocess
import sys
import threading
import time
import shutil
from functools import lru_cache
import desktop_cache_index
import desktop_saved_fixtures
import desktop_opponent_scope
import desktop_recovery_sources
import desktop_ai_state
import desktop_generation_catalog
import desktop_static_plans
import desktop_observed_plans
import desktop_coach_presets
import desktop_source_plans
import desktop_save_export
import fm27_tactic_pool
from desktop_storage import GIB, SAVE_RESERVE_BYTES, require_space
from desktop_save_compat import PROFILE as READER_PROFILE


def read(path):
    return json.loads(path.read_text(encoding='utf8'))

@lru_cache(maxsize=2)
def dataset(path):
    return read(path)

def choose_save_file():
    import ctypes
    from ctypes import wintypes as w
    class OpenFileName(ctypes.Structure):
        _fields_=[('size',w.DWORD),('owner',w.HWND),('instance',w.HINSTANCE),('filter',w.LPCWSTR),
            ('custom_filter',w.LPWSTR),('max_custom',w.DWORD),('filter_index',w.DWORD),
            ('file',w.LPWSTR),('max_file',w.DWORD),('file_title',w.LPWSTR),('max_title',w.DWORD),
            ('initial_directory',w.LPCWSTR),('title',w.LPCWSTR),('flags',w.DWORD),
            ('file_offset',w.WORD),('extension_offset',w.WORD),('default_extension',w.LPCWSTR),
            ('custom_data',ctypes.c_ssize_t),('hook',ctypes.c_void_p),('template',w.LPCWSTR),
            ('reserved',ctypes.c_void_p),('reserved_word',w.DWORD),('flags_ex',w.DWORD)]
    buffer=ctypes.create_unicode_buffer(32768)
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.GetForegroundWindow.restype=w.HWND
    value=OpenFileName();value.size=ctypes.sizeof(value);value.owner=user.GetForegroundWindow()
    value.filter='Football Manager 存档 (*.fm;*.fmf)\0*.fm;*.fmf\0所有文件\0*.*\0\0'
    value.file=ctypes.cast(buffer,w.LPWSTR);value.max_file=len(buffer)
    value.title='选择要读取的 FM27 存档';value.flags=0x80000|0x1000|0x800|0x8
    directory=Path.home()/'Documents/Sports Interactive/Football Manager 27/games'
    if directory.is_dir():value.initial_directory=str(directory)
    api=ctypes.WinDLL('comdlg32',use_last_error=True)
    api.GetOpenFileNameW.argtypes=[ctypes.POINTER(OpenFileName)];api.GetOpenFileNameW.restype=w.BOOL
    if api.GetOpenFileNameW(ctypes.byref(value)): return buffer.value
    code=api.CommDlgExtendedError()
    if code: raise ValueError('无法打开存档选择器，错误码 '+hex(code))
    return None


def choose_folder():
    if sys.platform!='win32':raise ValueError('目录选择仅在 Windows 运行期可用')
    import ctypes
    from ctypes import wintypes as w
    class BrowseInfo(ctypes.Structure):
        _fields_=[('owner',w.HWND),('root',ctypes.c_void_p),('display',w.LPWSTR),('title',w.LPCWSTR),
            ('flags',w.UINT),('callback',ctypes.c_void_p),('data',ctypes.c_void_p),('image',ctypes.c_int)]
    user=ctypes.WinDLL('user32',use_last_error=True);shell=ctypes.WinDLL('shell32',use_last_error=True);ole=ctypes.WinDLL('ole32',use_last_error=True)
    user.GetForegroundWindow.restype=w.HWND
    shell.SHBrowseForFolderW.argtypes=[ctypes.POINTER(BrowseInfo)];shell.SHBrowseForFolderW.restype=ctypes.c_void_p
    shell.SHGetPathFromIDListW.argtypes=[ctypes.c_void_p,w.LPWSTR];shell.SHGetPathFromIDListW.restype=w.BOOL
    ole.CoTaskMemFree.argtypes=[ctypes.c_void_p]
    buffer=ctypes.create_unicode_buffer(32768);value=BrowseInfo()
    value.owner=user.GetForegroundWindow();value.title='选择导出战术的文件夹';value.flags=0x0001|0x0010|0x0040
    pidl=shell.SHBrowseForFolderW(ctypes.byref(value))
    if not pidl:return None
    try:return buffer.value if shell.SHGetPathFromIDListW(pidl,buffer) else None
    finally:ole.CoTaskMemFree(pidl)


class SaveLibrary:
    def __init__(self, app):
        self.app = app
        self.root = app.RUNS.parent/'save_library'
        self.root.mkdir(exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='save-reader')
        self.lock = threading.RLock()
        self.roster_lock = threading.RLock()
        self.active = None

    def folder(self, key):
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{16}', key):
            raise ValueError('无效的存档标识')
        folder = self.root/key
        if not folder.is_dir():
            raise ValueError('存档尚未导入')
        return folder

    def index_data(self,folder):
        return dataset(folder/'dataset.json')

    def start(self, path):
        source = Path(path).expanduser().resolve()
        if source.suffix.lower() not in ('.fm', '.fmf') or not source.is_file():
            raise ValueError('请选择真实的 .fm 存档；.fmf 仅在其内容确为存档时可读取')
        before=source.stat()
        with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        after=source.stat()
        if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('存档正在保存，请稍后重试')
        with self.lock:
            if self.active:
                raise ValueError('已有存档正在解析，请等待完成')
            cached=self.reusable_source(digest)
            if cached:
                self.write(cached/'selected_source.json',{'path':str(source)})
                desktop_recovery_sources.remember(self,source=source,imported=cached/'dataset.json')
                self.write(self.root/'latest.json',{'id':cached.name})
                return {'id':cached.name,'reused':True}
            require_space(self.root, additional_bytes=2*GIB, reserve_bytes=SAVE_RESERVE_BYTES)
            key = secrets.token_hex(8)
            folder = self.root/key
            folder.mkdir()
            self.active = key
            self.write(folder/'progress.json', {'status':'reading','stage':'等待解析','id':key})
            self.pool.submit(self.extract, source, folder, key)
        return {'id':key}

    def reusable_source(self, digest):
        # Older app versions did not keep a small source index. Read only the
        # metadata prefix to migrate them, never load every large dataset.
        for folder in sorted(self.root.iterdir(),key=lambda p:p.name):
            if not folder.is_dir()or not re.fullmatch('[0-9a-f]{16}',folder.name):continue
            try:
                if read(folder/'progress.json').get('status')!='complete':continue
                with (folder/'dataset.json').open('rb')as stream:prefix=stream.read(8192).decode('utf8',errors='replace')
                if not re.search(r'"source_sha256"\s*:\s*"'+digest+'"',prefix):continue
                if not re.search(r'"reader_compatibility_profile"\s*:\s*"'+re.escape(READER_PROFILE)+'"',prefix):continue
                data=dataset(folder/'dataset.json')
                if data['source_sha256']!=digest or data.get('schema')!=4 or 'first_team_counts'not in data:continue
                paths=[folder/'player_index.json',folder/'rosters']
                paths.extend(folder/c['path']for c in data['caches'])
                paths.extend(folder/t['raw_plan']for t in data['tactics']if t.get('raw_plan'))
                if all(p.exists()for p in paths):return folder
            except (OSError,ValueError,KeyError):continue
        return None

    @staticmethod
    def write(path, value):
        tmp = path.with_suffix('.tmp')
        tmp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
        for attempt in range(21):
            try:
                os.replace(tmp,path)
                return
            except PermissionError:
                if attempt==20: raise
                time.sleep(.025)

    def extract(self, source, folder, key):
        try:
            python = os.environ.get('FM27_SAVE_PYTHON', sys.executable)
            env = os.environ.copy()
            env['PYTHONDONTWRITEBYTECODE'] = '1'
            env['PYTHONUTF8'] = '1'
            with (folder/'reader.stdout.log').open('wb') as stdout, (folder/'reader.stderr.log').open('wb') as stderr:
                result = subprocess.run([python,str(Path(__file__).with_name('desktop_save_worker.py')),str(source),str(folder)],
                    env=env,stdout=stdout,stderr=stderr,timeout=1800,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise ValueError(read(folder/'progress.json').get('stage','存档读取失败'))
            # The index lists all retained cache candidates, not guessed club ownership.
            self.write(folder/'progress.json', {'status':'complete','stage':'读取完成，可选择球队与方案','id':key})
            self.write(self.root/'latest.json', {'id':key})
            desktop_recovery_sources.remember(self,source=source,imported=folder/'dataset.json')
        except Exception as error:
            self.write(folder/'progress.json', {'status':'error','stage':str(error),'id':key})
        finally:
            with self.lock:
                self.active = None

    def status(self, key=None):
        if not key:
            key = self.active or (read(self.root/'latest.json')['id'] if (self.root/'latest.json').exists() else None)
        if not key:
            return {'status':'empty'}
        folder = self.folder(key)
        value = {**read(folder/'progress.json'),'id':key}
        if value['status'] != 'complete':
            return value
        data = dataset(folder/'dataset.json')
        if data.get('schema')!=4:raise ValueError('此存档缓存来自旧版本，请重新读取存档')
        if 'first_team_counts' not in data:raise ValueError('此缓存尚未区分一线队，请重新导入存档')
        counts = {int(k):v for k,v in data['first_team_counts'].items() if k!='None'}
        value.update(date=data['date'],build=data['build'],source=data['source'],source_sha256=data['source_sha256'],
                     managed=data['managed'],warnings=data['warnings'],cache_count=len(data['caches']),
                     clubs=[{'uid':c['uid'],'name':c.get('name') or c.get('short_name') or str(c['uid']),
                             'players':counts.get(c['uid'],0)} for c in data['clubs'] if counts.get(c['uid'],0)>=11 and c['uid'] in {m['club_uid']for m in data['managed']}])
        if (folder/'selected_source.json').exists():value['source']=read(folder/'selected_source.json')['path']
        return value

    def ensure_rosters(self, folder, clubs, cancelled=None):
        while not self.roster_lock.acquire(timeout=.1):
            if cancelled and cancelled():raise CancelledError('已取消名单准备')
        try:return self._ensure_rosters(folder,clubs,cancelled)
        finally:self.roster_lock.release()

    def _ensure_rosters(self, folder, clubs, cancelled=None):
        if cancelled and cancelled():raise CancelledError('已取消名单准备')
        needed=[c for c in set(clubs)if not (folder/'rosters'/(str(c)+'.json')).exists()]
        if not needed:return
        (folder/'rosters').mkdir(exist_ok=True)
        data=dataset(folder/'dataset.json')
        source=Path(read(folder/'selected_source.json')['path']if (folder/'selected_source.json').exists()else data['source'])
        request=folder/('roster_request_'+secrets.token_hex(6)+'.json')
        self.write(request,{'source_sha256':data['source_sha256'],'clubs':needed})
        env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
        with request.with_suffix('.log').open('wb')as stream:
            r=subprocess.Popen([os.environ.get('FM27_SAVE_PYTHON',sys.executable),str(Path(__file__).with_name('desktop_save_worker.py')),str(source),str(folder),'--rosters',str(request)],env=env,stdout=stream,stderr=stream,creationflags=subprocess.CREATE_NO_WINDOW)
            started=time.monotonic()
            try:
                while r.poll()is None:
                    if cancelled and cancelled():raise CancelledError('已取消名单准备')
                    if time.monotonic()-started>240:raise ValueError('球员属性准备超时，请查看 '+request.with_suffix('.log').name)
                    time.sleep(.1)
            finally:
                if r.poll()is None:r.terminate();r.wait(timeout=10)
        if r.returncode or not request.with_suffix('.done.json').exists():raise ValueError('所选对手球员属性读取失败，详情见 '+request.with_suffix('.log').name)

    def club(self, key, club):
        folder=self.folder(key)
        data = dataset(folder/'dataset.json')
        club = int(club)
        self.ensure_rosters(folder,[club])
        players = [p for p in read(folder/'rosters'/f'{club}.json') if p.get('unique_id')is not None]
        if len(players)<11:
            raise ValueError('该队不足11名已解析球员')
        return {'players':[{'uid':p['unique_id'],'name':p['name'],'positions':p['positions'],'ca':p['ability']['current']} for p in players],
                'tactics':[{'index':i,'name':t['name'],'team_id':t['team_id'],'available':bool(t.get('raw_plan'))}
                           for i,t in enumerate(data['tactics']) if t.get('club_uid')==club and t.get('team_slot')==0],
                'selections':[s for s in data['selections'] if s.get('club_uid')==club and s.get('team_slot')==0],
                'source_date':data['date']}

    def _source(self, key, folder, data):
        path=read(folder/'selected_source.json')['path']if(folder/'selected_source.json').exists()else data['source']
        return {'save_id':key,'source':path,'source_sha256':data['source_sha256'],'date':data['date'],'build':data['build']}

    @staticmethod
    def _tactic_digest(tactic):
        core={key:tactic.get(key)for key in ('mentality','instructions','native_extra_team_bits','phases')}
        return hashlib.sha256(json.dumps(core,sort_keys=True,ensure_ascii=False).encode('utf8')).hexdigest()

    def _league_scope(self, report):
        league=report.get('league')if isinstance(report.get('league'),dict)else None
        uids=league.get('club_uids')if league and isinstance(league.get('club_uids'),list)else None
        if uids is not None:count=len(uids)
        elif type(report.get('same_league_clubs'))is int and report['same_league_clubs']>0:count=report['same_league_clubs']+1
        else:count=len(report.get('opponents')or[])+1
        return {'league_id':league.get('competition_id')if league else None,'club_count':count}

    def _opponent_teams(self, report):
        teams=[]
        for row in report.get('opponents')or[]:
            coach=row.get('coach')if isinstance(row.get('coach'),dict)else {}
            teams.append({'club_uid':row.get('club_uid'),'name':row.get('name'),'key':row.get('key'),
                'tactic_name':coach.get('preset_name')or row.get('tactic_name')or'教练偏好预设',
                'source':row.get('source'),'available':bool(row.get('available')),'member':row.get('member')})
        return teams

    def _opponent_failures(self, report):
        failures=[{'club_uid':item.get('club_uid'),'name':item.get('name'),'error':item.get('error','教练偏好预设尚不可用')}
                  for item in report.get('failures')or[]]
        covered={item['club_uid']for item in failures}
        failures.extend({'club_uid':item.get('club_uid'),'name':item.get('name'),'error':item.get('reason','教练偏好预设尚不可用')}
                        for item in report.get('unrecovered_clubs')or[]if item.get('club_uid')not in covered)
        return failures

    def league_library(self, key, club):
        folder=self.folder(key);data=dataset(folder/'dataset.json');club=int(club)
        state=self.begin_opponents(key,club)
        if state.get('status')=='reading':return {'status':'reading','stage':state.get('stage','正在读取同联赛教练偏好')}
        if state.get('status')=='error':return {'status':'error','stage':state.get('stage')or'教练偏好读取失败'}
        report=self.inspect_opponents(key,club)
        own=next((c for c in data['clubs']if c['uid']==club),None)or {}
        scope=self._league_scope(report);source=self._source(key,folder,data)
        return {'status':'complete','save':{'id':key,'source':source['source'],'source_sha256':source['source_sha256'],
                'date':source['date'],'build':source['build']},
            'own':{'club_uid':club,'name':own.get('short_name')or own.get('name')or str(club),'nation_id':own.get('nation_id'),
                'league_id':scope['league_id'],'club_count':scope['club_count']},
            'teams':self._opponent_teams(report),'failures':self._opponent_failures(report)}

    def export_league_tactics(self, key, club, directory):
        folder=self.folder(key);data=dataset(folder/'dataset.json');club=int(club)
        if isinstance(directory,Path):target=directory.expanduser()
        elif isinstance(directory,str)and directory.strip():target=Path(directory).expanduser()
        else:raise ValueError('请选择导出目录')
        if not target.is_absolute()or not target.is_dir():raise ValueError('所选导出目录不存在，请重新选择')
        report=self.inspect_opponents(key,club)
        rows=[];failures=[{'club_uid':item['club_uid'],'club':item['name'],'tactic_name':None,'error':item['error']}
                          for item in self._opponent_failures(report)]
        for row in report.get('opponents')or[]:
            coach=row.get('coach')if isinstance(row.get('coach'),dict)else {}
            tactic_name=coach.get('preset_name')or row.get('tactic_name')or'教练偏好预设'
            if not row.get('available'):
                failures.append({'club_uid':row.get('club_uid'),'club':row.get('name'),'tactic_name':tactic_name,
                    'error':'教练偏好预设尚不可用'});continue
            try:
                team=desktop_coach_presets.preset_tactic(self,key,row['key'])
                scenario=copy.deepcopy(self.app.DEFAULT);scenario['teams'][1]=team
                exported=self.app.export_fmf({'side':1,'scenario':self.app.validate_scenario(scenario),'name':team['tactic_name']})
                rows.append({'club_uid':row.get('club_uid'),'club':row.get('name'),'target':row['key'],'tactic_name':tactic_name,
                    'payload':base64.b64decode(exported['file_base64'],validate=True),'report':exported['report']})
            except Exception as error:
                failures.append({'club_uid':row.get('club_uid'),'club':row.get('name'),'tactic_name':tactic_name,'error':str(error)})
        if not rows:raise ValueError('当前联赛没有可导出的教练偏好预设战术'+('：'+'；'.join(f['error']for f in failures[:3])if failures else''))
        result=desktop_save_export.write(str(target),self._source(key,folder,data),rows)
        result['failures']=failures
        result['league']=self._league_scope(report)
        return result

    def import_league_tactics_pool(self, key, club, scenario):
        folder=self.folder(key);club=int(club)
        if not isinstance(scenario,dict):raise ValueError('方案格式无效')
        scenario=copy.deepcopy(scenario)
        state=self.begin_opponents(key,club)
        if state.get('status')=='reading':return {'status':'reading','stage':state.get('stage','正在读取同联赛教练偏好')}
        if state.get('status')=='error':return {'status':'error','stage':state.get('stage')or'教练偏好读取失败'}
        report=self.inspect_opponents(key,club)
        existing=scenario.get('away_tactic_pool')if isinstance(scenario.get('away_tactic_pool'),dict)else None
        if existing is not None:existing=fm27_tactic_pool.normalize(existing)
        pool=existing or fm27_tactic_pool.defaults()
        entries=list(pool['entries'])if existing is not None else []
        seen={self._tactic_digest(entry['tactic'])for entry in entries}
        imported=[];duplicates=0;skipped={item.get('club_uid')for item in report.get('unrecovered_clubs')or[]}
        for row in report.get('opponents')or[]:
            coach=row.get('coach')if isinstance(row.get('coach'),dict)else {}
            tactic_name=coach.get('preset_name')or row.get('tactic_name')or'教练偏好预设'
            if not row.get('available'):skipped.add(row.get('club_uid'));continue
            try:team=desktop_coach_presets.preset_tactic(self,key,row['key'])
            except Exception:skipped.add(row.get('club_uid'));continue
            name=''.join(c for c in(row.get('name')or'')if ord(c)>=32).strip()[:fm27_tactic_pool.MAX_NAME]or'对手战术'
            try:entry=fm27_tactic_pool.entry_from_team(team,name=name)
            except ValueError:skipped.add(row.get('club_uid'));continue
            digest=self._tactic_digest(entry['tactic'])
            if digest in seen:duplicates+=1;continue
            if len(entries)>=fm27_tactic_pool.MAX_ENTRIES:raise ValueError(f'客队战术池最多保存 {fm27_tactic_pool.MAX_ENTRIES} 套战术')
            seen.add(digest);entries.append(entry)
            imported.append({'club_uid':row.get('club_uid'),'club':name,'tactic_name':tactic_name})
        if entries or existing is not None:
            scenario['away_tactic_pool']=fm27_tactic_pool.normalize({**pool,'entries':entries})
        scenario=self.app.validate_scenario(scenario)
        value=scenario.get('away_tactic_pool')if isinstance(scenario.get('away_tactic_pool'),dict)else None
        if value and value.get('entries'):pool_summary=fm27_tactic_pool.summary(value)
        else:
            default=fm27_tactic_pool.defaults()
            pool_summary={'profile':fm27_tactic_pool.PROFILE,'enabled':False,'uniform':default['uniform'],'entries':[]}
        skipped-={item['club_uid']for item in imported}
        return {'status':'complete','scenario':scenario,'imported':imported,'duplicates':duplicates,
            'skipped_unavailable':len(skipped),'pool':pool_summary,'league':self._league_scope(report)}

    def native(self, args, folder, name, extra=None, discover_tactic_boundary=False):
        self.app.desktop_engine.require_available(self.app.ENGINE_COMPATIBILITY)
        self.check_binding(folder)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('FM27_IMPORT_', 'FM27_EXPORT_', 'FM27_FMF_', 'FM27_EPISODE_', 'FM27_SAVE_SECTION_', 'FM27_SAVED_CORE_', 'FM27_AI_', 'FM27_COACH_'))}
        env.update(extra or {})
        log = folder/(name+'.jsonl')
        if log.exists():log=folder/(name+'_'+secrets.token_hex(4)+'.jsonl')
        result = subprocess.run([str(self.app.NATIVE/'FM27Simulator.exe'),*args,'--output',str(log)],
            cwd=self.app.ROOT,env=env,capture_output=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
        rows=[]
        if log.exists():
            for line in log.read_text(encoding='utf8',errors='replace').splitlines():
                try: rows.append(json.loads(line))
                except ValueError: pass
        parsed=next((r for r in rows if r.get('event')=='native_tactic_file_parsed'),{})
        discovered=(discover_tactic_boundary and result.returncode==173 and parsed.get('accepted') and
                    not parsed.get('stream_error') and 0<parsed.get('consumed',0)<parsed.get('size',0))
        if result.returncode and not discovered:
            raise ValueError(f'原版读取器未接受此输入（退出码 {result.returncode}），记录：{log.name}')
        return rows

    def check_binding(self, folder):
        binding={'host_sha256':self.app.desktop_engine.sha(self.app.NATIVE/'FM27Simulator.exe'),
                 'resource_fingerprint':self.app.ENGINE_COMPATIBILITY.get('resource_fingerprint')}
        path=folder/'native_binding.json'
        if path.exists() and read(path)!=binding:
            # Preserve old native evidence, but keep the expensive save decode.
            # Only host-dependent derived artifacts are invalidated.
            with self.lock:
                if path.exists()and read(path)!=binding:
                    archive=folder/'native_cache_history'/secrets.token_hex(8);archive.mkdir(parents=True)
                    files=[path]+list(folder.glob('*_input.json'))+list(folder.glob('parsed_tactic_*.json'))+list(folder.glob('opponents_*.json'))+list(folder.glob('opponent_progress_*.json'))+list(folder.glob('*_inspection_receipt.json'))
                    for item in files:os.replace(item,archive/item.name)
        if not path.exists(): self.write(path,binding)

    def ensure_snapshot(self, folder, entry):
        identity=read(folder/'native_binding.json')
        stamp=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
        shared=self.root/'verified_native_inputs'/stamp/entry['key']
        local=folder/(entry['key']+'_input.json')
        receipt=folder/(entry['key']+'_inspection_receipt.json')
        def valid(snapshot,record):
            try:
                r=read(record)
                return (r['engine']==identity and r['payload_sha256']==entry['key'] and
                        r['native_zero_tick_verified']is True and self.app.desktop_engine.sha(snapshot)==r['snapshot_sha256'])
            except (OSError,ValueError,KeyError):return False
        if valid(local,receipt):return read(local),True
        if valid(shared/'snapshot.json',shared/'receipt.json'):
            snapshot=read(shared/'snapshot.json');self.write(local,snapshot)
            r=read(shared/'receipt.json');r['snapshot_sha256']=self.app.desktop_engine.sha(local);self.write(receipt,r)
            return snapshot,True
        rows=self.native(['--fixture',str(folder/entry['path']),'--dump-input',str(local),'--inspect-fixture'],folder,entry['key']+'_inspect')
        if not any(r.get('event')=='native_fixture_inspected'and r.get('simulation_ticks_executed')==0 for r in rows):
            raise ValueError('缺少零比赛tick的读取确认')
        snapshot=read(local)
        if len(snapshot.get('teams',[]))!=2:raise ValueError('历史输入球队数量无效')
        r={'engine':identity,'payload_sha256':entry['key'],'snapshot_sha256':self.app.desktop_engine.sha(local),'native_zero_tick_verified':True}
        self.write(receipt,r)
        shared.mkdir(parents=True,exist_ok=True)
        self.write(shared/'snapshot.json',snapshot)
        r={**r,'snapshot_sha256':self.app.desktop_engine.sha(shared/'snapshot.json')}
        self.write(shared/'receipt.json',r)
        return snapshot,False

    def club_registry(self, folder, data):
        if all('unique_id'in c and 'teams'in c for c in data['clubs']):return data['clubs']
        registry=folder/'club_registry.json'
        if not registry.exists():
            source=Path(read(folder/'selected_source.json')['path']if (folder/'selected_source.json').exists()else data['source'])
            if not source.is_file():raise ValueError('旧缓存缺少球队唯一ID索引，请重新选择原始存档导入')
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUTF8':'1'}
            log=folder/('registry_'+secrets.token_hex(4)+'.log')
            with log.open('wb')as stream:
                result=subprocess.run([os.environ.get('FM27_SAVE_PYTHON',sys.executable),str(Path(__file__).with_name('desktop_save_worker.py')),str(source),str(folder),'--club-index'],
                    env=env,stdout=stream,stderr=stream,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise ValueError('球队唯一ID索引读取失败，请重新导入存档；详情见 '+log.name)
        value=read(registry)
        if value['source_sha256']!=data['source_sha256']:raise ValueError('原始存档已更新，请重新导入以生成对应的球队索引')
        return value['clubs']

    def native_club_map(self, folder, data):
        registry=self.club_registry(folder,data)
        by_native={};by_local={}
        for c in registry:
            if type(c.get('unique_id'))is int:
                by_local[c['uid']]=c['unique_id'];by_native[c['unique_id']]=c['uid']
        return registry,by_local,by_native

    def parsed_plan(self, key, index):
        folder=self.folder(key)
        self.check_binding(folder)
        data=dataset(folder/'dataset.json')
        if type(index) is not int or not 0<=index<len(data['tactics']):
            raise ValueError('未知存档战术')
        tactic=data['tactics'][index]
        if not tactic.get('raw_plan'):
            raise ValueError('该战术尚未完整解析')
        cached=folder/f'parsed_tactic_{index}.json'
        if cached.exists():
            return read(cached)
        raw_path=folder/tactic['raw_plan']
        # The last human plan may be followed by megabytes of AI rows, not
        # another text-named human plan. Probe a bounded prefix; only the
        # original reader's fully accepted cursor defines the real TAC end.
        probe=raw_path
        if raw_path.stat().st_size>1024*1024:
            probe=folder/f'tactic_{index}_boundary_probe.bin'
            with raw_path.open('rb') as stream:probe.write_bytes(stream.read(1024*1024))
        rows=self.native([],folder,f'parse_tactic_{index}_boundary',{'FM27_IMPORT_TAC':str(probe)},discover_tactic_boundary=True)
        parsed=next((r for r in rows if r.get('event')=='native_tactic_file_parsed'),None)
        if parsed and parsed['accepted'] and not parsed['stream_error'] and 0<parsed['consumed']<=parsed['size']:
            exact=folder/f'tactic_{index}_native_bounded.bin'
            exact.write_bytes((folder/tactic['raw_plan']).read_bytes()[:parsed['consumed']])
            rows=self.native([],folder,f'parse_tactic_{index}_verified',{'FM27_IMPORT_TAC':str(exact)})
            parsed=next((r for r in rows if r.get('event')=='native_tactic_file_parsed'),None)
        if not parsed or not parsed['accepted'] or parsed['stream_error'] or parsed['consumed']!=parsed['size']:
            raise ValueError('存档战术未通过原版完整回读，不使用猜测指令')
        self.write(cached,parsed)
        return parsed

    def apply_plan(self, team, plan):
        app=self.app
        bits=int.from_bytes(bytes.fromhex(plan['team_bits']),'little')
        team.update(mentality=plan['mentality'],native_extra_team_bits=str(bits&~app.TEAM_KNOWN_MASK))
        for g in app.GROUPS.values():
            values=[o['id'] for o in g['options'] if o['native_bit'] and bits>>o['native_bit']&1]
            if len(values)>1:
                raise ValueError('源战术含不能无损表示的同组指令')
            team['instructions'][str(g['id'])]=values[0] if values else next(o['id'] for o in g['options'] if not o['native_bit'])
        mapping=[i if v==255 else v for i,v in enumerate(plan['mapping'])]
        if sorted(mapping)!=list(range(11)):
            raise ValueError('源战术双阶段对应关系无效')
        for phase in range(2):
            for i in range(11):
                r=plan['phases'][phase][mapping[i] if phase else i]
                pos=next((p['id'] for p in app.POSITIONS.values() if p['mask']==r['position']),None)
                flags=int(r['role_flags'])
                role=next((v['id'] for v in app.ROLES.values() if v['phase']==phase and int(v['flags'])==flags&app.ROLE_MASK),None)
                if pos is None or role is None:
                    raise ValueError('源战术包含尚未映射的位置或角色')
                pi=int(r['pi_flags'])
                known=sum(1<<v for v in {o['id'] for g in app.PIS.values() for o in g['options'] if o['id']})
                if pi&~known:
                    raise ValueError('源战术包含尚未映射的个人指令，不静默丢弃')
                if any(sum(bool(pi>>o['id']&1) for o in g['options'] if o['id'])>1 for g in app.PIS.values()):
                    raise ValueError('源战术含不能无损表示的同组个人指令')
                team['phases'][phase][i]={'position':pos,'role':role,'duty':str(flags&~app.ROLE_MASK),
                    'instructions':{str(g['id']):next((o['id'] for o in g['options'] if o['id'] and pi>>o['id']&1),0) for g in app.PIS.values()},
                    'target_player':r['target_player'],'target_position':r['target_position']}
        desktop_source_plans.sign(app,team)

    def player_values(self, p):
        positions=['gk','sw','dl','dc','dr','dm','ml','mc','mr','aml','amc','amr','stc','wbl','wbr']
        values=[p['positions'][k] for k in positions]
        for entry in self.app.CATALOG['attributes'][15:]:
            key=re.sub(r'(?<!^)(?=[A-Z])','_',entry['name']).lower()
            key={'tendency_to_punch':'punching'}.get(key,key)
            values.append(p['raw_left_foot'] if key=='left_foot' else p['raw_right_foot'] if key=='right_foot' else p['raw_attributes'][key])
        if len(values)!=69:
            raise ValueError('球员属性映射不完整')
        profile=copy.deepcopy(self.app.profiles.CONTROLLED_START)
        for key,value in [('height_cm',p['height_cm']),('age',p['age']),('current_ability',p['ability']['current'])]:
            if value is not None: profile[key]=value
        if p['personality']:
            for k in ['professionalism','loyalty','sportsmanship','temperament','pressure','ambition','adaptability']:
                profile[k]=p['personality'][k]
        if p.get('trait_bits') is not None:
            profile.update(traits_low=p['trait_bits']&0xffffffff,traits_high=p['trait_bits']>>32)
        for k in ['home','current','world']:
            profile[k+'_reputation']=p['reputation'][k]
        return values,profile

    def load_team(self, key, club, index, selected, side, scenario, substitutes=None):
        folder=self.folder(key);data=dataset(folder/'dataset.json')
        app=self.app
        scenario=app.validate_scenario(scenario)
        side=app.integer(side,0,1,'球队')
        club=int(club)
        people={p['unique_id']:p for p in read(folder/'rosters'/f'{club}.json') if p.get('unique_id') is not None}
        tactic=data['tactics'][index] if type(index) is int and 0<=index<len(data['tactics']) else None
        if not tactic or tactic.get('club_uid')!=club or tactic.get('team_slot')!=0:
            raise ValueError('请选择该队已解析的一线队存储战术')
        if selected is None:
            starts=sorted((s for s in data['selections'] if s.get('club_uid')==club and s.get('team_slot')==0 and not s['substitute']),key=lambda s:s['slot'])
            automatic=copy.deepcopy(scenario['teams'][side])
            self.apply_plan(automatic,self.parsed_plan(key,index))
            desktop_static_plans.roster(self,key,club,automatic,[s.get('source_uid') for s in starts])
            selected=[p['source_uid'] for p in automatic['players'][:11]]
            if substitutes is None:substitutes=[p['source_uid'] for p in automatic['players'][11:automatic['roster_size']]]
        if len(selected)!=11 or len(set(selected))!=11 or any(u not in people for u in selected):
            raise ValueError('首发必须是该队11名不同的已解析球员')
        team=scenario['teams'][side]
        self.apply_plan(team,self.parsed_plan(key,index))
        setpiece_count=0
        setpiece_warnings=[]
        for kind, rows in data.get('setpieces',{}).get(str(tactic['team_id']),{}).items():
            label=app.setpieces.TYPE_NAMES[int(kind)]
            variants=[{**row,'name':row['name'] or f'{label} {i+1}'} for i,row in enumerate(rows)]
            current=team['setpieces']
            candidate={**current,'routines':{**current['routines'],kind:variants}}
            try:
                team['setpieces']=app.setpieces.normalize(candidate,side,len(team['players']))
            except ValueError as error:
                setpiece_warnings.append(f'{label}保留战术板原设置（{error}）')
            else:
                setpiece_count+=len(variants)
        team['squad']=[]
        for p in people.values():
            values,profile=self.player_values(p)
            team['squad'].append({'name':p['name'],'source_uid':p['unique_id'],'attributes':values,'initial_attributes':values[:],'native_profile':profile})
        team.update(captains=[],takers={k:[] for k in app.TAKER_KEYS},tactic_name=tactic['name'])
        c=next(c for c in data['clubs'] if c['uid']==club)
        team['name']=c.get('short_name') or c['name']
        result=self.select_squad(scenario,side,selected,substitutes or [],initial=True)
        setpiece_notice=f'已载入 {setpiece_count} 套存档定位球套路。' if setpiece_count else '定位球套路沿用战术板设置。'
        return {'scenario':result,'source':{'save_id':key,'club_uid':club,'date':data['date'],
            'tactic_index':index,'tactic_name':tactic['name'],'selected_tactic_confirmed':False,
            'notice':'战术来自存档保存方案，名单按当前球队和位置补齐。属性为存档当天，体能、士气等使用统一开赛条件。'
                     +setpiece_notice+' '+'。'.join(setpiece_warnings),
            'setpiece_routine_count':setpiece_count,
            'roster_count':len(people),'match_roster_count':result['teams'][side]['roster_size']}}

    def select_squad(self, scenario, side, starters, substitutes, initial=False):
        app=self.app
        if not initial:scenario=app.validate_scenario(scenario)
        else:scenario=copy.deepcopy(scenario)
        side=app.integer(side,0,1,'球队')
        team=scenario['teams'][side]
        if not isinstance(starters,list)or len(starters)!=11 or not isinstance(substitutes,list)or len(substitutes)>12:
            raise ValueError('比赛名单须为11名首发和0–12名替补')
        chosen=starters+substitutes
        if any(type(u)is not int for u in chosen)or len(set(chosen))!=len(chosen):raise ValueError('比赛名单不能重复选择球员')
        squad={p['source_uid']:p for p in team.get('squad',[])}
        if any(u not in squad for u in chosen):raise ValueError('比赛名单包含不在一线队的球员')
        old=team['players']
        by_uid={p.get('source_uid'):i for i,p in enumerate(old)if p.get('source_uid')is not None}
        remap={by_uid[u]:i for i,u in enumerate(chosen)if u in by_uid}
        team['players']=copy.deepcopy(app.DEFAULT['teams'][side]['players'])
        if len(chosen)>len(team['players']):raise ValueError('所选比赛名单超出当前宿主容量')
        for i,u in enumerate(chosen):team['players'][i].update(copy.deepcopy(squad[u]))
        for p in team['players'][len(chosen):]:p['name']='未入比赛名单';p.pop('source_uid',None)
        team.update(lineup=list(range(11)),roster_size=len(chosen))
        team['captains']=[remap[i]for i in team['captains']if i in remap]
        team['takers']={k:[remap[i]for i in values if i in remap]for k,values in team['takers'].items()}
        team['setpieces']['role_priorities']={k:[remap[i]for i in values if i in remap]for k,values in team['setpieces']['role_priorities'].items()}
        return app.validate_scenario(scenario)

    OPPONENT_PROFILE='coach-preference-presets-v19'

    def opponent_report(self, path):
        if not path.exists():return None
        value=read(path)
        if value.get('recovery_profile')!=self.OPPONENT_PROFILE:return None
        return value if value.get('binding')==desktop_coach_presets.binding(self,path.parent) else None

    def inspect_opponents(self, key, club):
        folder=self.folder(key);self.check_binding(folder);club=int(club)
        retained=self.opponent_report(folder/f'opponents_{club}.json')
        return retained if retained is not None else desktop_coach_presets.report(self,key,club)

    def begin_opponents(self, key, club):
        folder=self.folder(key);club=int(club)
        self.check_binding(folder)
        path=folder/f'opponents_{club}.json'
        progress=folder/f'opponent_progress_{club}.json'
        retained=self.opponent_report(path)
        if retained is not None:return {'status':'complete',**retained}
        if progress.exists():
            state=read(progress)
            if state.get('status')=='error'and state.get('profile')==self.OPPONENT_PROFILE:
                return state
        with self.lock:
            if self.active:
                stage=folder/'coach_presets/static_coaches/progress.json'
                if not stage.exists():stage=folder/'coach_presets/progress.json'
                try:current=read(stage)['stage']if stage.exists()else'正在读取同联赛教练偏好'
                except (ValueError,KeyError):current='正在读取同联赛教练偏好'
                return {'status':'reading','stage':current}
            self.active=key
            self.write(progress,{'status':'reading','profile':self.OPPONENT_PROFILE,'stage':'正在读取同联赛教练偏好'})
            def scan():
                try:
                    self.inspect_opponents(key,club)
                    self.write(progress,{'status':'complete','profile':self.OPPONENT_PROFILE})
                except Exception as error:
                    self.write(progress,{'status':'error','profile':self.OPPONENT_PROFILE,'stage':str(error)})
                finally:
                    with self.lock: self.active=None
            self.pool.submit(scan)
        return {'status':'reading','stage':'正在读取教练偏好并匹配原装预设，不模拟比赛'}

    def opponent_team(self, key, candidate, side, own_team):
        if str(candidate).startswith('coach:'):
            return desktop_coach_presets.team(self,key,candidate)
        if str(candidate).startswith('observed:'):
            return desktop_observed_plans.team(self,key,candidate,own_team)
        if str(candidate).startswith(('frozen:','generated:')):
            raise ValueError('生成方案不能作为电脑球队实际使用的战术')
        if str(candidate).startswith('stored:'):
            return desktop_saved_fixtures.team(self,key,candidate,side,own_team)
        folder=self.folder(key);data=dataset(folder/'dataset.json')
        self.check_binding(folder)
        if not re.fullmatch('[0-9a-f]{64}',str(candidate)):
            raise ValueError('未知历史方案')
        if not any(c['key']==candidate for c in data['caches']):
            extra=next((e for e in desktop_recovery_sources.entries(self,folder,data) if e['key']==candidate),None)
            if extra is None or self.app.desktop_engine.sha(folder/extra['path'])!=candidate:raise ValueError('历史方案不属于此存档或已核实的同生涯来源')
            self.ensure_snapshot(folder,extra)
        snapshot=read(folder/(candidate+'_input.json'))
        original=snapshot['teams'][side]
        team=copy.deepcopy(self.app.DEFAULT['teams'][1])
        raw=bytes.fromhex(original['manager_tactical_hex'])
        plan={'team_bits':original['creator_hex'][:32],'mentality':bytes.fromhex(original['creator_hex'])[37],
              'mapping':list(raw[0x1fb4-0x2e0:0x1fb4-0x2e0+11]),'phases':[]}
        for phase in range(2):
            cells=[]
            for j,h in enumerate(original['tactical_slots'][phase]):
                b=bytes.fromhex(h);pi=original['personal_instructions'][phase][j]
                cells.append({'position':struct.unpack_from('<I',b)[0],'role_flags':str(struct.unpack_from('<Q',b,64)[0]),
                    'pi_flags':pi['flags'],'target_player':pi['target_player'],'target_position':pi['target_position']})
            plan['phases'].append(cells)
        self.apply_plan(team,plan)
        native_club=struct.unpack_from('<I',bytes.fromhex(original['header_hex']),0x2c)[0]
        _,_,native_to_local=self.native_club_map(folder,data)
        club=native_to_local.get(native_club)
        c=next(c for c in data['clubs'] if c['uid']==club)
        desktop_static_plans.roster(self,key,club,team,[p['id'] for p in original['players']])
        active_count=team['roster_size']
        team.update(name=c.get('short_name') or c['name'],tactic_name='历史比赛方案 '+candidate[:8])
        # Retarget historical individual opposition instructions by source UID,
        # never by the carrier's unrelated native player IDs.
        own_index={p.get('source_uid'):i for i,p in enumerate(own_team['players'][:own_team.get('roster_size',26)]) if p.get('source_uid') is not None}
        prior_own=snapshot['teams'][1-side]['players']
        for i,p in enumerate(prior_own):
            current=own_index.get(p['id'])
            if current is not None: team['opposition']['players'][current]=self.app.unpack_oi(original['opposition'][i])
        stored_positions={r['position']:r['packed'] for r in original['opposition_positions']}
        team['opposition']['positions']={p['id']:self.app.unpack_oi(stored_positions.get(p['mask'],0x80000)) for p in self.app.POSITIONS.values()}
        for cells in team['phases']:
            for cell in cells:
                target=cell['target_player']
                if target!=255:
                    cell['target_player']=own_index.get(prior_own[target]['id'],255) if target<len(prior_own) else 255
        indices={p.get('source_uid'):i for i,p in enumerate(team['players'][:active_count])}
        keys={p['person_key']:indices[p['id']] for p in original['players'] if p['id'] in indices}
        lists={r['offset']:r['players'] for r in original['taker_lists']}
        def indices(offset):
            if offset not in lists: raise ValueError('历史快照缺少主罚名单字段，请重新解析')
            return [keys[k] for k in lists[offset] if k in keys]
        team['captains']=indices(0x1c8)
        team['takers']={name:indices(0x1e0 if i==0 else (i-1)*24) for i,name in enumerate(self.app.TAKER_KEYS)}
        team['setpieces']['role_priorities']={str(g):indices(0xf0+24*g) for g in range(8)}
        # Preserve the native historical set-piece routines, including opaque flags.
        for variants in original['routine_variants']:
            if not variants: continue
            routines=[]
            for i,r in enumerate(variants):
                groups=[[] for _ in range(8)]
                for g in r['groups']: groups[g['id']]=g['values'][:]
                backups=[[0]*len(g) for g in groups]
                for g,j,v in r['backups']: backups[g][j]=v
                routines.append({'name':'历史套路 '+str(i+1),'opaque_flags':r['opaque_flags'],
                    **{k:r[k] for k in ['frequency','strategy','swing','priority']},'groups':groups,'backups':backups})
            team['setpieces']['routines'][str(variants[0]['type'])]=routines
        team['setpieces']['throw_styles']=list(raw[0x16f0-0x2e0:0x16f3-0x2e0])
        return team
