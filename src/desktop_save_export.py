"""Write exported tactics into a local FMF folder with a verified manifest."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import time
import fm27_fmf

PROFILE='saved-tactic-export-v1'
MAX_FILES=400
MAX_PLAN_BYTES=4*1024*1024
ILLEGAL=re.compile(r'[<>:"/\\|?*]')
RESERVED={f'com{i}'for i in range(1,10)}|{f'lpt{i}'for i in range(1,10)}|{'con','prn','aux','nul'}

def _clean(value,limit):
    text=''.join(c for c in value if ord(c)>=32)
    text=ILLEGAL.sub('_',text)
    text=re.sub(r'\s+',' ',text).strip(' .')
    if len(text)>limit:text=text[:limit].rstrip(' .')
    return text

def safe_component(value,fallback,limit=60):
    text=_clean(value if isinstance(value,str) else '' if value is None else str(value),limit)
    if not text:
        text=_clean(fallback if isinstance(fallback,str) else '' if fallback is None else str(fallback),limit)
    if not text:return '战术'
    if text.split('.',1)[0].casefold() in RESERVED:
        text=('_'+text)[:limit].rstrip(' .')
        if not text:return '战术'
    return text

def _stamp():
    return time.strftime('%Y%m%d-%H%M%S')

def _directory(base):
    stem='FM27存档战术-'+_stamp()
    for number in range(1,1000):
        candidate=base/(stem if number==1 else f'{stem}-{number}')
        try:candidate.mkdir()
        except FileExistsError:continue
        return candidate
    raise ValueError('导出目录名称冲突，请稍后重试')

def _unique(value,fallback,used,limit=60):
    candidate=safe_component(value,fallback,limit);number=1
    while candidate.casefold() in used:
        number+=1;suffix=str(number)
        candidate=safe_component(value,fallback,limit-len(suffix))+suffix
    used.add(candidate.casefold())
    return candidate

def _inside(root,path):
    try:path.resolve().relative_to(root.resolve())
    except (OSError,ValueError):return False
    return True

def _atomic(path,payload):
    temporary=path.with_name(path.name+'.tmp')
    try:
        temporary.write_bytes(payload)
        for attempt in range(21):
            try:
                os.replace(temporary,path);return
            except PermissionError:
                if attempt==20:raise
                time.sleep(.025)
    finally:
        if temporary.exists():temporary.unlink()

def _source(value):
    value=value if isinstance(value,dict) else {}
    return {key:value.get(key)for key in ('save_id','source','source_sha256','date','build')}

def _rows(items):
    rows=list(items)if items is not None else []
    if not rows:raise ValueError('没有可导出的战术')
    if len(rows)>MAX_FILES:raise ValueError(f'一次最多导出 {MAX_FILES} 套战术')
    result=[]
    for item in rows:
        if not isinstance(item,dict):raise ValueError('战术导出条目无效')
        club_uid=item.get('club_uid');target=item.get('target');payload=item.get('payload')
        if type(club_uid)is not int or club_uid<0:raise ValueError('战术导出条目球队无效')
        if not isinstance(target,str)or not target:raise ValueError('战术导出条目标识无效')
        if isinstance(payload,memoryview):payload=payload.tobytes()
        if not isinstance(payload,bytes)or not payload:raise ValueError('战术文件内容必须是字节串')
        try:plan=fm27_fmf.tactics_plan(payload)
        except ValueError as error:raise ValueError('战术文件校验失败：'+str(error))
        if not plan:raise ValueError('战术文件缺少内嵌计划')
        if len(plan)>MAX_PLAN_BYTES:raise ValueError('单套战术计划超过 4 MB，无法导出')
        club=item.get('club');name=item.get('tactic_name');report=item.get('report')
        result.append({'club_uid':club_uid,'club':club if isinstance(club,str)else str(club if club is not None else club_uid),
            'target':target,'tactic_name':name if isinstance(name,str)else '',
            'payload':payload,'plan':plan,'report':report if isinstance(report,dict)else {}})
    return result

def _notice(source,folders,files):
    lines=['FM27 存档战术导出','',
        f'本目录由 FM Tactics Lab 从 FM27 生涯存档导出，共 {len(folders)} 支球队、{len(files)} 套战术。',
        f"来源存档：{source.get('source') or '未知'}",
        f"存档日期：{source.get('date') or '未知'}，游戏版本：{source.get('build') or '未知'}",
        '己方战术为存档中的存储战术，同联赛对手战术为教练偏好原装预设。',
        '每套 .fmf 可在工具中重新导入；manifest.json 记录文件清单、内嵌计划校验值与原版回读结果。']
    return '\n'.join(lines)+'\n'

def write(directory,source,items):
    if isinstance(directory,Path):base=directory.expanduser()
    elif isinstance(directory,str)and directory.strip():base=Path(directory).expanduser()
    else:raise ValueError('请选择导出目录')
    if not base.is_absolute():raise ValueError('导出目录必须是绝对路径')
    base=base.resolve()
    if not base.is_dir():raise ValueError('所选导出目录不存在，请重新选择')
    rows=_rows(items);source=_source(source)
    root=_directory(base)
    try:
        folders={}
        for row in rows:folders.setdefault(row['club_uid'],row['club'])
        used_clubs=set();folder_names={uid:_unique(club,f'球队{uid}',used_clubs)for uid,club in folders.items()}
        used_files={};files=[]
        for row in rows:
            club_dir=root/folder_names[row['club_uid']]
            if not _inside(root,club_dir)or club_dir.is_symlink():raise ValueError('导出路径越界，已停止')
            club_dir.mkdir(exist_ok=True)
            used=used_files.setdefault(row['club_uid'],set())
            name=_unique(row['tactic_name'],f"战术{row['target'].rsplit(':',1)[-1]}",used)
            target=club_dir/(name+'.fmf')
            if not _inside(root,target):raise ValueError('导出路径越界，已停止')
            _atomic(target,row['payload'])
            files.append({'file':target.relative_to(root).as_posix(),'club_uid':row['club_uid'],
                'club':row['club'],'target':row['target'],'tactic_name':row['tactic_name'],
                'sha256':hashlib.sha256(row['payload']).hexdigest(),'size':len(row['payload']),
                'plan_sha256':hashlib.sha256(row['plan']).hexdigest(),'plan_size':len(row['plan']),
                'report':row['report']})
        manifest={'profile':PROFILE,'created':datetime.now().astimezone().isoformat(timespec='seconds'),
            'source':source,'files':files,
            'notice':f'本目录包含 {len(folder_names)} 支球队、{len(files)} 套 FM27 战术文件，内嵌计划均已校验。'}
        _atomic(root/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf8'))
        _atomic(root/'导出说明.txt',_notice(source,folder_names,files).encode('utf8'))
    except Exception:
        shutil.rmtree(root,ignore_errors=True)
        raise
    return {'directory':str(root),'profile':PROFILE,'manifest':manifest,'files':files,'failures':[]}
