"""Loopback tactics editor: validated inputs -> original native match host."""
from __future__ import annotations
import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor,CancelledError
from datetime import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse,parse_qs
from fm27_simulator import inspect_log
from fm27_batch import BatchRunner, BatchCancelled, worker_limits, own_child_processes
from desktop_warm_batch import DesktopWarmRunner, inspect_saved_run
BATCH_LIMITS=worker_limits()
import fm27_setpieces as setpieces
import fm27_phase_inputs as phase_inputs
import fm27_profiles as profiles
import fm27_fmf
import fm27_tactic_pool
import fm27_match_events
import desktop_generation_protocol
import desktop_locale
import desktop_generation_catalog
import desktop_source_plans
from desktop_storage import require_space
import fm27_agent_contract as agent_contract
import fm27_agent_server as agent_server

ROOT = Path(os.environ["FM27_ENGINE_ROOT"])
WEB = Path(__file__).resolve().parent / 'tactics_ui'
RUNS = Path(os.environ['FM27_DESKTOP_DATA']) / 'runs'
RUNS.mkdir(parents=True,exist_ok=True)
NATIVE = ROOT / 'fm27_native'
import desktop_engine
ENGINE_COMPATIBILITY = desktop_engine.initialize(ROOT)
ENGINE_DLL_SHA256 = ENGINE_COMPATIBILITY['actual_dll_sha256']
EXECUTION_EXPERIMENT_DLLS = {
    '252ff8fb5b7a4a5a5464db6ba632e309eef9b6e65ffa992ae20575a189e66c6a',
    'f79b0a3413dd0e3f461b0afbc3ff397003f4a26d7525a30717428de6a8b91196',
}
EXECUTION_COMPONENTS = ('understanding', 'buy_in', 'opposition', 'ability')
CATALOG = json.loads((WEB/'catalog.json').read_text(encoding='utf8'))
phase_inputs.annotate(CATALOG)
CATALOG['setpieces']=setpieces.CATALOG
SNAPSHOT = json.loads((NATIVE/'editor_manual_default.json').read_text(encoding='utf8'))
ADVANCED = json.loads((NATIVE/'editor_advanced_snapshot.json').read_text(encoding='utf8'))
ROLE_MASK = 0xfffffffbf91fffff
ROLES = {r['id']:r for r in CATALOG['roles']}
POSITIONS = {p['id']:p for p in CATALOG['positions']}
GROUPS = {g['id']:g for g in CATALOG['team_instructions']}
TEAM_KNOWN_MASK=sum(1<<bit for bit in {o['native_bit']for g in GROUPS.values()for o in g['options']if o['native_bit']})
PIS = {g['id']:g for g in CATALOG['player_instructions']}
TAKER_KEYS=['penalties']+[f'{kind}_{direction}_{"foot"if kind in ("corners","wide_free_kicks")else "side"}'for kind in ('corners','direct_free_kicks','wide_free_kicks','deep_free_kicks','throw_ins')for direction in ('left','right')]
POLICY_VERSION='1a080000'
APP_VERSION='1109.3'
STATIC_FILES={'/team-bulk.js':'team-bulk.js','/desktop-workspace.js':'desktop-workspace.js','/match-events.js':'match-events.js','/desktop.js':'desktop.js','/desktop.css':'desktop.css','/':'index.html','/app.js':'app.js','/advanced.js':'advanced.js','/setpieces.js':'setpieces.js','/batch.js':'batch.js','/style.css':'style.css','/save-mode.js':'save-mode.js','/save-mode.css':'save-mode.css','/engine-settings.js':'engine-settings.js','/squad-editor.js':'squad-editor.js','/tactic-pool.js':'tactic-pool.js','/tactic-library.js':'tactic-library.js','/i18n.js':'i18n.js','/i18n-en.js':'i18n-en.js'}
AGENT_TOKEN=None
AGENT_ROUTER=None
AGENT_SERVER=None
def unpack_oi(value):
    return {'press':value&7,'mark':(value>>3)&7,'tackle':(value>>8)&7,'foot':(value>>11)&7,'personal':bool(value&0x80000)}
def pack_oi(row):
    return row['press']|(row['mark']<<3)|(row['tackle']<<8)|(row['foot']<<11)|(0x80000 if row['personal']else 0)
OOP_MAP=[]
for t in SNAPSHOT['teams']:
    raw=bytes.fromhex(t['manager_tactical_hex'])
    mapping=[i if v==255 else v for i,v in enumerate(raw[0x1fb4-0x2e0:0x1fb4-0x2e0+11])]
    if sorted(mapping)!=list(range(11)):raise ValueError('fixture OOP map is not a permutation')
    OOP_MAP.append(mapping)

def defaults():
    teams=[]
    for side,t in enumerate(SNAPSHOT['teams']):
        creator=bytes.fromhex(t['creator_hex']);bits=int.from_bytes(creator[:16],'little')
        instructions={}
        for g in GROUPS.values():
            active=[o['id']for o in g['options'] if o['native_bit'] and bits>>o['native_bit']&1]
            if len(active)>1:raise ValueError('ambiguous fixture team instruction')
            instructions[str(g['id'])]=active[0] if active else next((o['id']for o in g['options'] if not o['native_bit']),g['options'][0]['id'])
        phases=[]
        for phase in range(2):
            cells=[]
            for i in range(11):
                native_slot=OOP_MAP[side][i] if phase else i
                h=t['tactical_slots'][phase][native_slot]
                cell=bytes.fromhex(h);pos=struct.unpack_from('<I',cell)[0];flag=struct.unpack_from('<Q',cell,64)[0]&ROLE_MASK
                role=next((r for r in ROLES.values() if r['phase']==phase and int(r['flags'])==flag),None)
                if not role:raise ValueError(f'fixture role not in UI: {phase}:{flag}')
                position=next(p['id']for p in POSITIONS.values() if p['mask']==pos)
                pi=t['personal_instructions'][phase][native_slot];flags=int(pi['flags'])
                values={str(g['id']):next((o['id']for o in g['options'] if o['id'] and flags>>o['id']&1),0)for g in PIS.values()}
                cells.append({'position':position,'role':role['id'],'duty':str(struct.unpack_from('<Q',cell,64)[0]&~ROLE_MASK),'instructions':values,'target_player':pi['target_player'],'target_position':pi['target_position']})
            phases.append(cells)
        oi=ADVANCED['teams'][side]
        positional={p['id']:unpack_oi(next((r['packed']for r in oi['opposition_positions']if r['position']==p['mask']),0x80000))for p in CATALOG['positions']}
        teams.append({'name':['主队','客队'][side],'tactic_name':'','native_extra_team_bits':str(bits&~TEAM_KNOWN_MASK),'mentality':creator[0x25],'instructions':instructions,'lineup':list(range(11)),
                      'opposition':{'players':[unpack_oi(v)for v in oi['opposition'][:SNAPSHOT['teams'][1-side]['count']]],'positions':positional},
                      'captains':[],'takers':{k:[]for k in TAKER_KEYS},'setpieces':copy.deepcopy(setpieces.DEFAULTS[side]),
                      'phases':phases,'players':[{'name':f'{["主","客"][side]}队球员 {p["index"]+1:02d}','native_id':p['id'],'attributes':p['attributes'],'native_profile':copy.deepcopy(profiles.CONTROLLED_START)}for p in t['players']]})
    return {'schema':3,'rules':'game','fixture':'bundled_match_pkm','teams':teams}

DEFAULT = defaults()
def cell_policy(side,phase,index,cell):
    native=OOP_MAP[side][index] if phase else index
    raw=bytes.fromhex(SNAPSHOT['teams'][side]['tactical_slots'][phase][native])
    duty=int(cell.get('duty',str(struct.unpack_from('<Q',raw,64)[0]&~ROLE_MASK)))
    key=f'{phase}:{cell["position"]}:{cell["role"]}:{duty}'
    return CATALOG['pi_policies'].get(key,{}).get(POLICY_VERSION,'1'*43)

def role_options(cells,phase,position):
    count=sum(bool(POSITIONS[c['position']]['mask']&16)for c in cells)
    dm=sum(bool(POSITIONS[c['position']]['mask']&0x80)for c in cells)
    return CATALOG['role_eligibility_context'][f'{3 if count>=3 else 0}:{int(dm==1)}'][position][phase]

def team_conflicts(instructions):
    active={next(o['native_bit']for o in GROUPS[int(g)]['options']if o['id']==v):int(g)for g,v in instructions.items()}
    return [(active[a],active[b])for a,b in CATALOG['team_conflicting_bits']if a in active and b in active]
def integer(value,low,high,label):
    if type(value)is not int or not low<=value<=high:raise ValueError(f'{label}必须为 {low}–{high} 的整数')
    return value

def validate_scenario(data):
    data=phase_inputs.unpack(data,CATALOG)
    if isinstance(data,dict)and data.get('schema')==1:
        # v1 indexed OOP entries by raw native cell; v2 indexes both phases by
        # the same player slot. Preserve the actual native assignment on import.
        data=copy.deepcopy(data)
        try:
            if len(data['teams'])!=2:raise ValueError('旧版名单不完整')
            for side,t in enumerate(data['teams']):
                old=t['phases'][1]
                if len(old)!=11:raise ValueError('旧版无球阵型不完整')
                t['phases'][1]=[old[n]for n in OOP_MAP[side]]
        except (KeyError,IndexError,TypeError):raise ValueError('旧版方案格式无效')
        data['schema']=2
    if isinstance(data,dict)and data.get('schema')==2:
        data=copy.deepcopy(data);data.update(schema=3,rules='lab')
    if not isinstance(data,dict)or data.get('schema')!=3 or data.get('fixture')!='bundled_match_pkm':raise ValueError('方案格式或比赛样本不匹配')
    if data.get('rules')not in ('game','lab'):raise ValueError('未知角色限制模式')
    teams=data.get('teams')
    if not isinstance(teams,list)or len(teams)!=2:raise ValueError('必须包含两支球队')
    # Normalize to a bounded, typed document. No address, path, native offset or code input.
    normalized=copy.deepcopy(DEFAULT)
    normalized['rules']=data['rules']
    for side,t in enumerate(teams):
        n=normalized['teams'][side];base=DEFAULT['teams'][side]
        source=desktop_source_plans.baseline(sys.modules[__name__],t)
        if source is not None:n['native_source_plan']=copy.deepcopy(t['native_source_plan'])
        n['name']=str(t.get('name',''))[:40]
        n['tactic_name']=str(t.get('tactic_name',''))[:120]
        try:extra=int(t.get('native_extra_team_bits',base['native_extra_team_bits']))
        except (TypeError,ValueError):raise ValueError('附加原生战术选项格式无效')
        if extra<0 or extra>=1<<128 or extra&TEAM_KNOWN_MASK:raise ValueError('附加原生选项越界或与已命名指令重复')
        n['native_extra_team_bits']=str(extra)
        n['mentality']=integer(t['mentality'],1,7,'比赛心态')
        if 'roster_size'in t:n['roster_size']=integer(t['roster_size'],11,len(base['players']),'比赛名单人数')
        for g in GROUPS.values():
            val=t['instructions'].get(str(g['id']),base['instructions'][str(g['id'])]);integer(val,0,0xffffffff,'球队指令')
            if val not in [o['id']for o in g['options']]:raise ValueError('未知球队指令选项')
            n['instructions'][str(g['id'])]=val
        if data['rules']=='game'and team_conflicts(n['instructions'])and not(source and source['instructions']==n['instructions']):raise ValueError('同一侧的内套与外套互斥，请将其中一项恢复标准')
        if not isinstance(t['players'],list)or len(t['players'])!=len(base['players']):raise ValueError('名单长度不匹配')
        for i,p in enumerate(t['players']):
            if p.get('native_id')!=base['players'][i]['native_id']:raise ValueError('球员顺序或标识不匹配')
            if len(p['attributes'])!=69:raise ValueError('每名球员必须包含69项原生输入')
            n['players'][i]['name']=str(p['name'])[:48]
            n['players'][i]['attributes']=[integer(v,0 if a<15 else 1,20 if a<15 else 100,'属性')for a,v in enumerate(p['attributes'])]
            n['players'][i]['native_profile']=profiles.normalize(p.get('native_profile',{}));n['players'][i]['native_profile'].update(profiles.CONTROLLED_START)
            if 'source_uid'in p:n['players'][i]['source_uid']=integer(p['source_uid'],0,0xffffffff,'源球员UID')
        if 'squad' in t:
            if not isinstance(t['squad'],list):raise ValueError('一线队名单格式无效')
            squad=[];seen=set()
            active={p.get('source_uid'):p for p in n['players'][:t.get('roster_size',len(n['players']))] if p.get('source_uid')is not None}
            for p in t['squad']:
                uid=integer(p['source_uid'],0,0xffffffff,'一线队球员UID')
                if uid in seen:raise ValueError('一线队名单存在重复球员')
                seen.add(uid)
                if len(p['attributes'])!=69:raise ValueError('一线队球员属性不完整')
                entry={'source_uid':uid,'name':str(p['name'])[:48],
                    'attributes':[integer(v,0,20 if a<15 else 100,'一线队属性')for a,v in enumerate(p['attributes'])],
                    'native_profile':profiles.normalize(p.get('native_profile',{}))}
                baseline=p.get('initial_attributes',p['attributes'])
                if len(baseline)!=69:raise ValueError('一线队原始属性不完整')
                entry['initial_attributes']=[integer(v,0,20 if a<15 else 100,'原始属性')for a,v in enumerate(baseline)]
                if uid in active:
                    for field in ['name','attributes','native_profile']:entry[field]=copy.deepcopy(active[uid][field])
                squad.append(entry)
            if any(uid not in seen for uid in active):raise ValueError('比赛名单包含一线队名单之外的球员')
            n['squad']=squad
        if len(t['lineup'])!=11 or len(set(t['lineup']))!=11:raise ValueError('首发必须是11名不同球员')
        n['lineup']=[integer(i,0,len(base['players'])-1,'首发球员')for i in t['lineup']]
        if any(i>=t.get('roster_size',len(base['players'])) for i in n['lineup']):raise ValueError('首发包含未进入比赛名单的球员')
        caps=t.get('captains',base['captains'])
        if not isinstance(caps,list)or len(caps)>len(base['players'])or len(set(caps))!=len(caps):raise ValueError('队长优先顺序无效')
        n['captains']=[integer(i,0,len(base['players'])-1,'队长')for i in caps]
        n['setpieces']=setpieces.normalize(t.get('setpieces',base['setpieces']),side,len(base['players']))
        takers=t.get('takers',base['takers'])
        if isinstance(takers,dict)and set(takers)=={k.replace('_side','_foot')for k in TAKER_KEYS}:
            takers={k:takers[k.replace('_side','_foot')]for k in TAKER_KEYS}
        if not isinstance(takers,dict)or set(takers)!=set(TAKER_KEYS):raise ValueError('定位球主罚名单分类不符')
        for k in TAKER_KEYS:
            values=takers[k]
            if not isinstance(values,list)or len(values)>len(base['players'])or any(type(v)is not int for v in values)or len(set(values))!=len(values):raise ValueError('定位球主罚顺序无效')
            n['takers'][k]=[integer(v,0,len(base['players'])-1,'主罚球员')for v in values]
        opp=t.get('opposition',base['opposition'])
        if len(opp['players'])!=len(base['opposition']['players']):raise ValueError('针对性指令的对方名单长度不符')
        def oi_row(row):
            result={k:integer(row[k],0,maximum,'针对性指令')for k,maximum in [('press',2),('mark',2),('tackle',3),('foot',3)]}
            if type(row['personal'])is not bool:raise ValueError('针对性指令模式无效')
            result['personal']=row['personal'];return result
        n['opposition']['players']=[oi_row(r)for r in opp['players']]
        n['opposition']['positions']={p:oi_row(opp['positions'][p])for p in POSITIONS}
        if len(t['phases'])!=2:raise ValueError('必须配置有球和无球阶段')
        for phase,cells in enumerate(t['phases']):
            if len(cells)!=11:raise ValueError('每个阶段必须有11个位置')
            positions=[c['position']for c in cells]
            if positions.count('GK')!=1 or positions[0]!='GK' or len(set(positions))!=11:raise ValueError('每个阶段必须有一名门将且位置不能重复；0号位置为门将')
            for i,c in enumerate(cells):
                if c['position']not in POSITIONS or c['role']not in ROLES or ROLES[c['role']]['phase']!=phase:raise ValueError('未知位置或阶段角色')
                ncell=n['phases'][phase][i];ncell['position']=c['position'];ncell['role']=c['role']
                retained=desktop_source_plans.cell(source,phase,c)
                if data['rules']=='game'and not retained and c['role']not in role_options(cells,phase,c['position']):
                    options=role_options(cells,phase,c['position'])
                    labels=[f"{ROLES.get(item,{}).get('label') or item}({item})"for item in options]
                    stage='有球'if phase==0 else'无球'
                    raise ValueError(f"位置 {c['position']} 在{stage}阶段不可使用角色 {c['role']}；可用角色：{'、'.join(labels)}")
                original=base['phases'][phase][i]
                duty=str(c.get('duty','0'if c['role']!=original['role']else original['duty']))
                if duty not in ('0','2097152','4194304','8388608','33554432','67108864','17179869184'):raise ValueError('未知角色职责位')
                ncell['duty']=duty
                policy=cell_policy(side,phase,i,ncell)
                for g in PIS.values():
                    v=c['instructions'].get(str(g['id']))
                    if type(v)is not int or v not in [o['id']for o in g['options']]:raise ValueError('未知个人指令选项')
                    ncell['instructions'][str(g['id'])]=v
                    preserved=retained is not None and retained['instructions'].get(str(g['id']))==v
                    if data['rules']=='game'and v and not preserved and (g['phase']!=phase or policy[v]!='0'):raise ValueError(f'{g["label"]}被当前角色限制；请使用角色预设或更换角色')
                target=integer(c['target_player'],0,255,'盯防球员')
                if target!=255 and target>=len(DEFAULT['teams'][1-side]['players']):raise ValueError('盯防球员不存在')
                ncell['target_player']=target
                if c['target_position']not in [0]+[p['mask']for p in POSITIONS.values()]:raise ValueError('盯防位置不存在')
                ncell['target_position']=c['target_position']
                if ncell['instructions']['14']==34 and target==255:raise ValueError('指定盯防需要选择对方名单序号')
                if ncell['instructions']['14']==35 and not ncell['target_position']:raise ValueError('指定盯防需要选择位置')
    if 'native_generation'in data:
        normalized['native_generation']=desktop_generation_protocol.normalize(data['native_generation'],normalized['teams'])
    if 'experimental_execution' in data:
        if 'native_generation' in data:
            raise ValueError('实验执行力目前只支持已加载的战术方案')
        values = data['experimental_execution']
        if not isinstance(values, list) or len(values) != 2:
            raise ValueError('请分别设置两队的实验执行力')
        if ENGINE_DLL_SHA256 not in EXECUTION_EXPERIMENT_DLLS:
            raise ValueError('当前 FM27 引擎版本尚未验证实验执行力')
        execution = []
        for value in values:
            if isinstance(value, dict):
                if set(value) not in (set(EXECUTION_COMPONENTS[:3]), set(EXECUTION_COMPONENTS)):
                    raise ValueError('请填写战术理解、教练认可和对手情报')
                value = {key: integer(value[key], 0, 100, '实验执行力分项')
                         for key in EXECUTION_COMPONENTS if key in value}
            else:
                value = integer(value, 0, 100, '实验执行力')
            execution.append(value)
        normalized['experimental_execution'] = execution
    if data.get('away_tactic_pool')is not None:
        normalized['away_tactic_pool']=fm27_tactic_pool.normalize(data['away_tactic_pool'])
    return normalized

def enabled_pool(scenario):
    if not isinstance(scenario,dict):return None
    value=scenario.get('away_tactic_pool')
    return value if isinstance(value,dict)and value.get('enabled')else None

def encode_scenario(data,absolute=False):
    data=validate_scenario(data);records=[]
    for side, value in enumerate(data.get('experimental_execution', [])):
        if isinstance(value, dict):
            records.extend((61, side, index, 0, value[key])
                           for index, key in enumerate(EXECUTION_COMPONENTS, 1) if key in value)
        else:
            records.append((61, side, 0, 0, value))
    for side,t in enumerate(data['teams']):
        base=DEFAULT['teams'][side];records.append((10,side,0,0,1))
        if 'roster_size'in t:records.append((17,side,0,0,t['roster_size']))
        records.extend(setpieces.encode(t['setpieces'],side))
        # Signed native-source values may include fixed/non-editable PI bits.
        # Newly edited values still pass the strict server policy above.
        records.append((13,side,0,0,int(data['rules']=='game'and not desktop_source_plans.baseline(sys.modules[__name__],t))))
        records.extend((12,side,i,0,native)for i,native in enumerate(OOP_MAP[side]))
        for i,p in enumerate(t['players']):
            if i>=t.get('roster_size',len(t['players'])):continue
            for key,value in p.get('native_profile',{}).items():records.append((15,side,i,profiles.FIELDS[key][0],value))
            for a,v in enumerate(p['attributes']):
                if absolute or v!=base['players'][i]['attributes'][a]:records.append((1,side,i,a,v))
        for g,v in t['instructions'].items():
            if absolute or v!=base['instructions'][g]:records.append((2,side,int(g),0,v))
        extra=int(t.get('native_extra_team_bits',base['native_extra_team_bits']));old_extra=int(base['native_extra_team_bits'])
        for bit in range(128):
            if not(TEAM_KNOWN_MASK>>bit&1)and(absolute or(extra^old_extra)>>bit&1):records.append((60,side,bit,0,extra>>bit&1))
        if absolute or t['mentality']!=base['mentality']:records.append((3,side,0,0,t['mentality']))
        for phase,cells in enumerate(t['phases']):
            for i,c in enumerate(cells):
                b=base['phases'][phase][i];slot=phase*16+(OOP_MAP[side][i] if phase else i)
                if absolute or c['role']!=b['role']:
                    flags=int(ROLES[c['role']]['flags']);records.append((4,side,slot,flags>>32,flags&0xffffffff))
                if absolute or c['position']!=b['position']:records.append((5,side,slot,0,POSITIONS[c['position']]['mask']))
                if absolute or c['duty']!=b['duty']:
                    duty=int(c['duty']);records.append((14,side,slot,duty>>32,duty&0xffffffff))
                if absolute:records.append((18,side,slot,0,0))
                for group,value in c['instructions'].items():
                    # A role change changes the override-map key; explicitly carry edited settings.
                    if absolute or value!=b['instructions'][group] or (c['role']!=b['role'] and value):records.append((6,side,slot,int(group),value))
                if absolute or c['target_player']!=b['target_player'] or (c['role']!=b['role'] and c['target_player']!=255):records.append((7,side,slot,0,c['target_player']))
                if absolute or c['target_position']!=b['target_position'] or (c['role']!=b['role'] and c['target_position']):records.append((7,side,slot,1,c['target_position']))
        if absolute or t['lineup']!=base['lineup']:
            records.extend((11,side,i,0,p)for i,p in enumerate(t['lineup']))
        other=data['teams'][1-side];order=other['lineup']+[i for i in range(len(other['players']))if i not in other['lineup']]
        for i,row in enumerate(t['opposition']['players']):
            if row!=base['opposition']['players'][i]:records.append((20,side,order.index(i),0,pack_oi(row)))
        for pos,row in t['opposition']['positions'].items():
            if row!=base['opposition']['positions'][pos]:records.append((21,side,POSITIONS[pos]['mask'],0,pack_oi(row)))
        if t['captains']!=base['captains']:
            records.append((30,side,0,0xffffffff,0))
            records.extend((30,side,0,j,i)for j,i in enumerate(t['captains']))
            captain=next((i for i in t['captains']if i in t['lineup']),0xffffffff)
            records.append((31,side,0,0,captain))
        for list_id,k in enumerate(TAKER_KEYS,1):
            if t['takers'][k]!=base['takers'][k]:
                records.append((30,side,list_id,0xffffffff,0))
                records.extend((30,side,list_id,j,i)for j,i in enumerate(t['takers'][k]))
    config=b'FM27CFG1'+struct.pack('<I',len(records))+b''.join(struct.pack('<5I',*r)for r in records)
    return desktop_generation_protocol.encode(config,data['native_generation'])if 'native_generation'in data else config

def repair_saved_scenario(data):
    source=copy.deepcopy(data);source['rules']='lab'
    n=validate_scenario(source);n['rules']='game';changes=[]
    for side,t in enumerate(n['teams']):
        source=desktop_source_plans.baseline(sys.modules[__name__],t)
        if team_conflicts(t['instructions'])and not(source and source['instructions']==t['instructions']):
            t['instructions']['31']=next(o['id']for o in GROUPS[31]['options']if o['native_bit']==0)
            changes.append('同侧内套／外套冲突已恢复其中一项为标准')
        for phase,cells in enumerate(t['phases']):
            for i,c in enumerate(cells):
                allowed=role_options(cells,phase,c['position']);base=DEFAULT['teams'][side]['phases'][phase][i]
                retained=desktop_source_plans.cell(source,phase,c)
                if not retained and c['role']not in allowed:
                    c['role']=base['role']if base['role']in allowed else allowed[0];c['duty']='0';changes.append('已调整不适用于位置／阵型的角色')
                policy=cell_policy(side,phase,i,c)
                for g in PIS.values():
                    v=c['instructions'][str(g['id'])]
                    if v and (g['phase']!=phase or policy[v]!='0')and not(retained is not None and retained['instructions'].get(str(g['id']))==v):
                        c['instructions'][str(g['id'])]=0;changes.append('已恢复角色固定／不适用的个人指令')
    return {'scenario':validate_scenario(n),'changes':sorted(set(changes))}

def metrics(runs):
    if not runs:return None
    scores=[r['result']['score']for r in runs];n=len(scores);w=sum(a>b for a,b in scores);draw=sum(a==b for a,b in scores)
    p=w/n;z=1.959963984540054;den=1+z*z/n;center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return {'n':n,'wins':w,'draws':draw,'losses':n-w-draw,'win_rate':p,'win_interval':[max(0,center-half),min(1,center+half)],'goals_for':sum(a for a,b in scores)/n,'goals_against':sum(b for a,b in scores)/n,'points':(3*w+draw)/n}

LOCK=threading.RLock();JOBS={};POOL=ThreadPoolExecutor(max_workers=1)
RUN_GATE=agent_server.RunGate()
class EngineBusy(ValueError):pass
IMPORT_LOCK=threading.Lock()
import desktop_save_mode
import sys
SAVE_LIBRARY=desktop_save_mode.SaveLibrary(sys.modules[__name__])

def require_league_idle(label):
    if SAVE_LIBRARY.real_active:raise ValueError('请等待真实AI战术生成完成')
    if SAVE_LIBRARY.active:raise ValueError('请等待存档及历史输入解析完成')
    with LOCK:
        if any(j['status']in ('queued','running')for j in JOBS.values()):raise ValueError('请等待比赛结束后再'+label)

def experiment_name(value, fallback):
    if value is None: return fallback
    if not isinstance(value,str) or not 1<=len(value.strip())<=100 or any(ord(c)<32 for c in value):
        raise ValueError('实验名称须为1–100个可读字符')
    return value.strip()

def create_save_job(data):
    desktop_engine.require_available(ENGINE_COMPATIBILITY)
    if SAVE_LIBRARY.real_active: raise ValueError('请等待真实AI战术生成完成')
    if SAVE_LIBRARY.active: raise ValueError('请等待存档／对手解析完成')
    scenario=validate_scenario(data['scenario'])
    reference=validate_scenario(data['reference']) if data.get('reference') else None
    if enabled_pool(scenario)or enabled_pool(reference):raise ValueError('随机客队战术池仅支持自由推演，存档对战不可用')
    own=integer(data.get('club_uid'),0,0xffffffff,'己方球队')
    selected=data.get('opponents')
    if not isinstance(selected,list) or not 1<=len(selected)<=40 or len({v['key'] for v in selected})!=len(selected):
        raise ValueError('请选择1–40个不重复的真实对手方案')
    count=integer(data.get('count'),2,10000,'每队场数')
    if count%2: raise ValueError('主客场各半时，每队场数必须为偶数')
    require_space(RUNS,additional_bytes=len(selected)*count*(2 if reference else 1)*3*1024**2)
    first=integer(data.get('first_seed'),0,0xffffffff,'起始种子')
    if first+count//2-1>0xffffffff: raise ValueError('种子超出范围')
    workers=integer(data.get('workers',1),1,BATCH_LIMITS['maximum'],'并行数')
    event_details=data.get('event_details',True)
    if type(event_details)is not bool: raise ValueError('事件明细开关无效')
    with LOCK:
        if any(j['status']in ('queued','running')for j in JOBS.values()):raise ValueError('已有比赛运行中')
        key=secrets.token_hex(6);directory=RUNS/f'{datetime.now():%Y%m%d_%H%M%S}_{key}';directory.mkdir()
        job={'batch_schema':1,'id':key,'status':'queued','preparing':True,'stage':'正在准备同联赛对手',
             'workers':workers,'completed':0,'total':len(selected)*count*(2 if reference else 1),
             'runs':[],'metrics':{},'failures':[],'active':[],'created':time.time(),
             'output_dir':str(directory),'_dir':directory,'_cancel':False,
             'name':experiment_name(data.get('name'),f"{scenario['teams'][0]['name']} · {len(selected)}队"),
             'experiment_type':'save_opponents','schedule':{},'variant_names':{},'team_names':{},
             'mode':'comparison'if reference else'single','event_details':event_details}
        JOBS[key]=job;persist(job)
    def stage(text):
        with LOCK:
            if job.get('_cancel'):raise CancelledError('已取消比赛准备')
            job['stage']=text;persist(job)
    def prepare():
        try:
            admitted=SAVE_LIBRARY.inspect_opponents(data['save_id'],own)['opponents']
            valid={v['key']:v for v in admitted}
            chosen_clubs=[valid[c['key']]['club_uid'] for c in selected if c['key'] in valid]
            if len(chosen_clubs)!=len(set(chosen_clubs)):raise ValueError('同一球队请选择一套历史方案，避免重复加权')
            if len(chosen_clubs)!=len(selected):raise ValueError('所选对手不属于当前同联赛列表')
            stage('正在批量读取所选 '+str(len(chosen_clubs))+' 队球员属性，整份存档只读取一次')
            SAVE_LIBRARY.ensure_rosters(SAVE_LIBRARY.folder(data['save_id']),chosen_clubs,cancelled=lambda:job.get('_cancel',False))
            variants=[];schedule={}
            for index,choice in enumerate(selected):
                stage('正在准备对手 '+str(index+1)+' / '+str(len(selected)))
                opponent=valid.get(choice['key'])
                if not opponent or not opponent.get('available'): raise ValueError('对手方案未核实')
                team=SAVE_LIBRARY.opponent_team(data['save_id'],opponent.get('fixture_key',opponent['key']),opponent['side'],scenario['teams'][0])
                opponent={**opponent,'match_roster_count':team.get('roster_size',len(team['players'])),'cache_roster_count':team.get('roster_size',len(team['players']))}
                for venue in ['H','A']:
                    for group,source in ([('A',reference),('B',scenario)] if reference else [('B',scenario)]):
                        target=copy.deepcopy(source)
                        target.pop('native_generation',None)
                        target['teams'][1]=copy.deepcopy(team)
                        if venue=='A':
                            target['teams']=[transplant_team(target['teams'][1],0),transplant_team(target['teams'][0],1)]
                            if 'experimental_execution' in target:
                                target['experimental_execution'].reverse()
                        label=f'{group}_{index}_{venue}'
                        if opponent.get('source_kind')=='original_ai_generation':
                            target['native_generation']=desktop_generation_catalog.scenario_profile(SAVE_LIBRARY,data['save_id'],own,opponent['club_uid'],0 if venue=='H'else 1,target['teams'])
                        target=validate_scenario(target)
                        variants.append((label,target))
                        schedule[label]={'group':group,'opponent':opponent['name'],'opponent_key':opponent['key'],
                            'source_kind':opponent.get('source_kind','historical_match'),
                            'source_save':opponent.get('source_save'),
                            'tested_side':0 if venue=='H' else 1,'venue':venue,'source':opponent['source'],'member':opponent['member'],
                            'cache_roster_count':opponent['cache_roster_count'],'match_roster_count':opponent['match_roster_count'],
                            'excluded_substitute_uids':opponent['excluded_substitute_uids']}
            seeds=list(range(first,first+count//2))
            with LOCK:
                if job.get('_cancel'):raise CancelledError('已取消比赛准备')
                key=job['id'];directory=job['_dir']
                for label,s in variants:
                    (directory/f'{label}.json').write_text(json.dumps(s,ensure_ascii=False),encoding='utf8')
                    (directory/f'{label}.bin').write_bytes(encode_scenario(s))
                source=SAVE_LIBRARY.status(data['save_id'])
                provenance={'host_sha256':hashlib.sha256((NATIVE/'FM27Simulator.exe').read_bytes()).hexdigest(),
                    'fixture_sha256':hashlib.sha256((NATIVE/'fixtures/match.pkm').read_bytes()).hexdigest(),
                    'native_dll_sha256':ENGINE_DLL_SHA256,'engine_resource_fingerprint':ENGINE_COMPATIBILITY['resource_fingerprint'],
                    'engine_compatibility':copy.deepcopy(ENGINE_COMPATIBILITY),'seeds':seeds,'event_details':event_details,
                    'config_hashes':{v:hashlib.sha256((directory/f'{v}.bin').read_bytes()).hexdigest()for v,_ in variants},
                    'save_source':{k:source[k]for k in ['id','source','source_sha256','date','build']},'schedule':schedule}
                (directory/'provenance.json').write_text(json.dumps(provenance,ensure_ascii=False),encoding='utf8')
                prepared={'batch_schema':1,'workers':workers,'failures':[],'active':[],'id':key,'status':'queued','completed':0,
                    'total':len(seeds)*len(variants),'runs':[],'metrics':{},'created':time.time(),'output_dir':str(directory),'_dir':directory,
                    'name':experiment_name(data.get('name'),f"{scenario['teams'][0]['name']} · {len(selected)}队 · {count}场/队"),
                    'experiment_type':'save_opponents','schedule':schedule,'event_details':event_details,
                    'engine_compatibility':copy.deepcopy(ENGINE_COMPATIBILITY),'runtime_mode':'reused_native_worker','jobs_per_native_session':64,
                    'initial_state_policy':{'id':'controlled-start-v3','player_values':copy.deepcopy(profiles.CONTROLLED_START),'morale_verified':True,'cohesion_verified':True},
                    'mode':'comparison'if reference else'single','variant_names':{v:f"{schedule[v]['opponent']} · {'主场'if schedule[v]['venue']=='H'else'客场'} · {schedule[v]['group']}"for v,_ in variants},
                    'team_names':{v:[t['name']for t in s['teams']]for v,s in variants}}
                prepared['created']=job['created'];job.update(prepared);job['preparing']=False;job['stage']=None;persist(job)
            execute(job,variants,seeds)
        except CancelledError:
            with LOCK:job.update(status='cancelled',preparing=False,stage='已取消比赛准备',finished=time.time());persist(job)
        except Exception as error:
            with LOCK:job.update(status='error',preparing=False,stage='比赛准备失败',error=str(error),finished=time.time());persist(job)
    POOL.submit(prepare)
    return {'id':key}

def transplant_team(source, side):
    target=copy.deepcopy(source)
    base=DEFAULT['teams'][side]
    count=source.get('roster_size',len(source['players']))
    if count>len(base['players']): raise ValueError('阵容人数超出该主客场宿主容量')
    target['players']=copy.deepcopy(base['players'])
    for i,p in enumerate(source['players'][:count]):
        target['players'][i]=copy.deepcopy(p)
        target['players'][i]['native_id']=base['players'][i]['native_id']
    target['roster_size']=count
    neutral=unpack_oi(0x80000)
    target['opposition']['players']=(target['opposition']['players']+[copy.deepcopy(neutral)for _ in base['opposition']['players']])[:len(base['opposition']['players'])]
    return target

def export_fmf(data):
    side=integer(data['side'],0,1,'球队');scenario=validate_scenario(data['scenario']);team=scenario['teams'][side]
    title=str(data.get('name')or team.get('tactic_name')or team['name']or'战术')[:100]
    title=''.join(c for c in title if c not in '\\/:*?"<>|'and ord(c)>=32).strip(' .')or'战术'
    directory=RUNS.parent/'exports'/secrets.token_hex(8);directory.mkdir(parents=True);config=directory/'scenario.bin';config.write_bytes(encode_scenario(scenario,absolute=True));plan=directory/'tactic.tac';log=directory/'native_write.jsonl'
    env={k:v for k,v in os.environ.items()if k not in ['FM27_IMPORT_TAC','FM27_IMPORT_FMF','FM27_FMF_DETAILS','FM27_FMF_AUDIT','FM27_DESKTOP_STATS_AUDIT']};env.update(FM27_EXPORT_TAC=str(plan),FM27_EXPORT_SIDE=str(side),FM27_EXPORT_TITLE=title)
    with IMPORT_LOCK:
        desktop_engine.require_available(ENGINE_COMPATIBILITY)
        env['FM27_GAME_ROOT']=os.environ.get('FM27_GAME_ROOT','')
        env['FM27_EXPECTED_DLL_SHA256']=os.environ['FM27_EXPECTED_DLL_SHA256']
        try:result=subprocess.run([str(NATIVE/'FM27Simulator.exe'),'--scenario-file',str(config),'--output',str(log)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:raise ValueError('原版战术写入超时，未生成导出文件')
    if result.returncode or not plan.is_file():raise ValueError('原版战术序列化失败，未导出')
    payload=fm27_fmf.tactics_archive(plan.read_bytes(),title);path=directory/(title+'.fmf');path.write_bytes(payload)
    # Verify the archive and the original serialized plan through the same game
    # parser used by imports. A download is returned only after semantic parity.
    imported=import_fmf({'side':side,'scenario':scenario,'file_base64':base64.b64encode(payload).decode()});actual=imported['scenario']['teams'][side]
    keys=['mentality','instructions','native_extra_team_bits','phases']
    differences=[key for key in keys if actual[key]!=team[key]]
    if differences:raise ValueError('导出后原版回读不一致：'+','.join(differences))
    report={'name':title,'sha256':hashlib.sha256(payload).hexdigest(),'native_roundtrip_verified':True,'verified_sections':keys,'notice':'FMF 导出当前球队的双阶段阵型、角色、球队／球员指令及心态。球员属性、针对性指令与定位球不随此文件导出；完整工具配置请另存 JSON。'}
    (directory/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return {'filename':title+'.fmf','file_base64':base64.b64encode(payload).decode(),'report':report}

def import_fmf(data):
    side=integer(data['side'],0,1,'球队');scenario=validate_scenario(data['scenario'])
    try:payload=base64.b64decode(data['file_base64'],validate=True)
    except (ValueError,TypeError):raise ValueError('FMF 文件编码无效')
    if not 26<=len(payload)<=4*1024*1024 or payload[:6]not in(bytes.fromhex('02016166652e'),bytes.fromhex('0201666d662e')):raise ValueError('不是受支持的 FMF 归档，或文件超过 4 MB')
    directory=RUNS.parent/'imports'/secrets.token_hex(8);directory.mkdir(parents=True);source=directory/'input.fmf';source.write_bytes(payload);output=directory/'native_import.jsonl'
    env={k:v for k,v in os.environ.items()if k not in['FM27_IMPORT_TAC','FM27_DESKTOP_STATS_AUDIT']};env['FM27_IMPORT_FMF']=str(source)
    with IMPORT_LOCK:
        desktop_engine.require_available(ENGINE_COMPATIBILITY)
        env['FM27_GAME_ROOT']=os.environ.get('FM27_GAME_ROOT','')
        env['FM27_EXPECTED_DLL_SHA256']=os.environ['FM27_EXPECTED_DLL_SHA256']
        try:result=subprocess.run([str(NATIVE/'FM27Simulator.exe'),'--output',str(output)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:raise ValueError('原版 FMF 解析超时，文件未导入')
    try:rows=[json.loads(l)for l in output.read_text(encoding='utf8').splitlines()]
    except (OSError,ValueError):raise ValueError('原版解析未生成完整记录，文件未导入')
    parsed=next((r for r in rows if r.get('event')=='native_tactic_file_parsed'),None);decoded=next((r for r in rows if r.get('event')=='native_fmf_decoded'),None)
    routine=next((r for r in rows if r.get('event')=='native_setpiece_file_parsed'),None)
    if routine and not result.returncode and routine['accepted']and not routine['stream_error']:
        target=data.get('setpiece_target')
        if not target:raise ValueError('这是定位球套路，请在定位球页面导入')
        kind=integer(target['type'],0,9,'定位球类型');variant=integer(target['variant'],0,2,'套路序号')
        if kind!=routine['type']:raise ValueError('文件类型为'+setpieces.TYPE_NAMES[routine['type']]+'，请切换到对应类别后导入')
        variants=scenario['teams'][side]['setpieces']['routines'][str(kind)]
        if variant>=len(variants):raise ValueError('目标套路不存在')
        backups=[[0]*len(g)for g in routine['groups']]
        for g,i,v in routine['backups']:
            if g>=8 or i>=len(backups[g]):raise ValueError('定位球备用任务越界')
            backups[g][i]=v
        variants[variant]={'name':bytes.fromhex(decoded['name_utf8_hex']).decode('utf8')[:64],'frequency':routine['frequency'],'strategy':routine['strategy'],'swing':routine['swing'],'groups':routine['groups'],'backups':backups,'priority':routine['priority'],'opaque_flags':routine['opaque_flags']}
        scenario=validate_scenario(scenario);report={'setpiece_type':kind,'notice':'已通过原版解析器导入'+setpieces.TYPE_NAMES[kind]+'套路；包含任务、备用任务、分配顺序、发球策略和频率。','native_roundtrip_verified':True}
        (directory/'import_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return {'scenario':scenario,'report':report}
    if result.returncode or not parsed or not decoded or not parsed['accepted']or parsed['stream_error']:raise ValueError('本机游戏解析器未完整接受此战术，未改动当前配置')
    team=scenario['teams'][side]
    SAVE_LIBRARY.apply_plan(team,parsed)
    team['tactic_name']=bytes.fromhex(decoded['name_utf8_hex']).decode('utf8')[:120]
    repaired={'scenario':validate_scenario(scenario),'changes':[]}
    report={'source_sha256':hashlib.sha256(payload).hexdigest(),'tactic_name':team['tactic_name'],'core_bytes_consumed':parsed['consumed'],'decoded_bytes':parsed['size'],'preserved_extra_native_bits':[i for i in range(128)if int(team['native_extra_team_bits'])>>i&1],'normalization':repaired['changes'],'retained_sections':['球员与属性','定位球套路','针对性指令','主罚与队长名单'],'notice':'已导入当前球队的双阶段阵型、角色、指令及心态。球员、定位球、针对性指令和主罚名单保留当前配置。'}
    (directory/'import_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return {'scenario':repaired['scenario'],'report':report}

def import_pool_fmf(data):
    scenario=validate_scenario(data['scenario'])
    imported=import_fmf({'side':1,'scenario':scenario,'file_base64':data['file_base64']})
    entry=fm27_tactic_pool.entry_from_team(imported['scenario']['teams'][1],data.get('name'))
    pool=scenario.get('away_tactic_pool')or fm27_tactic_pool.defaults();entries=list(pool['entries'])
    if len(entries)>=fm27_tactic_pool.MAX_ENTRIES:raise ValueError(f'客队战术池最多保存 {fm27_tactic_pool.MAX_ENTRIES} 套战术')
    entries.append(entry)
    scenario['away_tactic_pool']=fm27_tactic_pool.normalize({**pool,'entries':entries})
    scenario=validate_scenario(scenario)
    report=dict(imported['report']);report['tactic_name']=entry['name'];report['sha256']=report.get('source_sha256')
    return {'scenario':scenario,'entry':entry,'report':report,'pool':fm27_tactic_pool.summary(scenario['away_tactic_pool'])}

def export_setpiece(data):
    side=integer(data['side'],0,1,'球队');scenario=validate_scenario(data['scenario']);kind=integer(data['type'],0,9,'定位球类型');variant=integer(data['variant'],0,2,'套路序号');rows=scenario['teams'][side]['setpieces']['routines'][str(kind)]
    if variant>=len(rows):raise ValueError('套路不存在')
    routine=rows[variant];payload=fm27_fmf.setpiece_archive(kind,routine)
    restored=import_fmf({'side':side,'scenario':scenario,'setpiece_target':{'type':kind,'variant':variant},'file_base64':base64.b64encode(payload).decode()})
    actual=restored['scenario']['teams'][side]['setpieces']['routines'][str(kind)][variant]
    if actual!=routine:raise ValueError('定位球导出回读不一致，未下载')
    name=''.join(c for c in routine['name']if c not in '\\/:*?"<>|'and ord(c)>=32).strip(' .')or'定位球'
    return {'filename':name+'.fmf','file_base64':base64.b64encode(payload).decode(),'report':{'native_roundtrip_verified':True,'notice':'定位球 FMF 已通过原版回读核验。'}}

def persist(job):
    with LOCK:
        public={k:v for k,v in job.items() if not k.startswith('_')}
        temporary=job['_dir']/'summary.tmp'
        temporary.write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf8')
        os.replace(temporary,job['_dir']/'summary.json')

def episode_metrics(runs,side):
    valid=[r for r in runs if r.get('episode',{}).get('found')];n=len(valid)
    return {'generated':len(runs),'n':n,'unavailable':len(runs)-n,'goals_for':sum(r['result']['score'][side]for r in valid),'goals_against':sum(r['result']['score'][1-side]for r in valid),'goals_per_100':sum(r['result']['score'][side]for r in valid)*100/n if n else None,'conceded_per_100':sum(r['result']['score'][1-side]for r in valid)*100/n if n else None,'shots_per_100':sum(r['statistics']['teams'][side]['shots']for r in valid)*100/n if n else None,'xg_per_100':sum(r['statistics']['teams'][side]['xg']for r in valid)*100/n if n else None}

def update_metrics(job,scenarios):
    if job.get('tactic_pool'):
        entries=job['tactic_pool'].get('entries',[])
        counts=fm27_tactic_pool.completed_draw_counts(job['runs'],len(entries))
        total=len(job['_pool_draws']) if '_pool_draws' in job else job['tactic_pool'].get('draws',{}).get('total',sum(counts.values()))
        job['tactic_pool']['draws']={'total':total,'counts':counts}
    if job.get('experiment_type')=='save_opponents':
        def oriented(run):
            result=copy.deepcopy(run)
            if job['schedule'][run['variant']]['tested_side']==1: result['result']['score'].reverse()
            return result
        def save_metrics(runs):
            value=metrics([oriented(r)for r in runs])
            if value:
                stats=[(r['statistics']['teams'][job['schedule'][r['variant']]['tested_side']],r['statistics']['teams'][1-job['schedule'][r['variant']]['tested_side']])for r in runs]
                value.update(xg=sum(a['xg']for a,b in stats)/len(stats),xga=sum(b['xg']for a,b in stats)/len(stats),
                    possession=sum(a['possession']for a,b in stats)/len(stats),shots=sum(a['shots']for a,b in stats)/len(stats),
                    pass_completion=sum(a['completed_passes']for a,b in stats)/max(1,sum(a['passes']for a,b in stats)))
            return value
        groups=['A','B'] if job['mode']=='comparison' else ['B']
        job['metrics']={g:save_metrics([r for r in job['runs'] if job['schedule'][r['variant']]['group']==g]) for g in groups}
        job['opponent_metrics']={key:{g:save_metrics([r for r in job['runs'] if job['schedule'][r['variant']]['group']==g and job['schedule'][r['variant']]['opponent_key']==key])for g in groups}for key in {v['opponent_key']for v in job['schedule'].values()}}
        pairs={}
        for run in job['runs']:
            spec=job['schedule'][run['variant']]
            pairs.setdefault((spec['opponent_key'],spec['venue'],run['seed']),{})[spec['group']]=oriented(run)
        complete=[v for v in pairs.values()if 'A'in v and 'B'in v]
        job['paired']={'n':len(complete),'goal_difference_delta':sum((v['B']['result']['score'][0]-v['B']['result']['score'][1])-(v['A']['result']['score'][0]-v['A']['result']['score'][1])for v in complete)/len(complete)if complete else None}
        return
    if job.get('experiment_type')=='setpiece_episode':
        job['metrics']={v:episode_metrics([r for r in job['runs']if r['variant']==v],job['episode_settings']['tested_side'])for v,s in scenarios}
        job['distributions']={v:fm27_match_events.distribution([r for r in job['runs']if r['variant']==v and r.get('episode',{}).get('found')])for v,s in scenarios}
        return
    job['metrics']={v:metrics([r for r in job['runs']if r['variant']==v])for v,s in scenarios}
    job['distributions']={v:fm27_match_events.distribution([r for r in job['runs']if r['variant']==v])for v,s in scenarios}
    if len(scenarios)==2:
        aa={r['seed']:r for r in job['runs']if r['variant']=='A'};bb={r['seed']:r for r in job['runs']if r['variant']=='B'}
        pairs=[(aa[k],bb[k])for k in aa.keys()&bb.keys()]
        job['paired']={'n':len(pairs),'goal_difference_delta':sum((b['result']['score'][0]-b['result']['score'][1])-(a['result']['score'][0]-a['result']['score'][1])for a,b in pairs)/len(pairs)if pairs else None}

def execute(job,scenarios,seeds):
    with RUN_GATE:
        with LOCK:
            if job.get('_cancel')or job.get('status')=='cancelled':
                job['_cancel']=True
                if job.get('status')!='cancelled':job.update(status='cancelled',finished=time.time())
                job.update(current=None,active=[],eta_seconds=None)
                job.pop('_pool_variants',None);job.pop('_pool_draws',None)
                persist(job)
                return
        _execute(job,scenarios,seeds)

def _execute(job,scenarios,seeds):
    began=time.perf_counter();previous=job.get('elapsed_seconds',0);initial=job['completed'];last_save=0
    runner=BatchRunner(ROOT,job['workers'],retries=1)if job.get('episode_settings')else DesktopWarmRunner(ROOT,job['workers'],retries=0)
    execution_settings = {label:s['experimental_execution'] for label,s in scenarios if 'experimental_execution' in s}
    if execution_settings:
        runner.jobs_per_session = 1
        job.update(runtime_mode='isolated_pool_execution_experiment' if job.get('_pool_variants') else 'isolated_execution_experiment', jobs_per_native_session=1,
                   experimental_execution=execution_settings)
    with LOCK:
        job['_runner']=runner;job['status']='running';job['started']=time.time()
        if job.get('_cancel'):runner.cancel()
    try:
        completed={(r['variant'],r['seed'])for r in job['runs']}
        pool_variants=job.get('_pool_variants')or{}
        tasks=[]
        for index,seed in enumerate(seeds):
            for label,_ in scenarios:
                if(label,seed)in completed:continue
                if pool_variants:
                    entry_index=job['_pool_draws'][str(seed)];scenario=pool_variants[label][entry_index];config=job['_dir']/f'{label}_pool{entry_index}.bin'
                else:
                    scenario=next(s for v,s in scenarios if v==label);config=job['_dir']/f'{label}.bin'
                task={'key':f'{label}:{seed}','variant':label,'seed':seed,'scenario':scenario,
                    'position_names':{p['mask']:p['id']for p in POSITIONS.values()},'episode':job.get('episode_settings'),
                    'config':config,'path':job['_dir']/f'{index:04d}_{label}_seed_{seed}.jsonl'}
                if pool_variants:
                    task['tactic_pool_entry']=entry_index;task['tactic_pool_name']=job['tactic_pool']['entries'][entry_index]['name']
                tasks.append(task)
        for task in tasks:task['event_details']=job.get('event_details',True)
        def result(run):
            with LOCK:
                if pool_variants:
                    entry_index=job['_pool_draws'][str(run['seed'])];entry=job['tactic_pool']['entries'][entry_index]
                    run['tactic_pool_entry']={'index':entry_index,'name':entry['name'],'weight':entry['weight'],'probability':entry['probability']}
                if run.get('failed'):job['failures'].append(run)
                else:
                    run['log_sha256']=hashlib.sha256((job['_dir']/run['log']).read_bytes()).hexdigest()
                    run['sequence']=len(job['runs'])+1
                    job['runs'].append(run);job['runs'].sort(key=lambda r:(r['seed'],r['variant']));job['completed']=len(job['runs']);update_metrics(job,scenarios)
                persist(job)
        def progress(active):
            nonlocal last_save
            with LOCK:
                elapsed=time.perf_counter()-began;n=job['completed']-initial
                job.update(active=active,current=active[0]if active else None,elapsed_seconds=round(previous+elapsed,3),matches_per_minute=round(n*60/elapsed,2)if elapsed else 0,eta_seconds=round((job['total']-job['completed'])*elapsed/n)if n else None)
                if elapsed-last_save>=1:persist(job);last_save=elapsed
        runner.run(tasks,result,progress)
        with LOCK:
            job['status']='error'if job['failures']else('cancelled'if runner.stop.is_set()else'complete')
            if job['failures']:job['error']=f"{len(job['failures'])}项原生比赛或数据校验失败；现场与原种子保留，未自动重跑整场比赛"
    except (BatchCancelled, CancelledError):
        with LOCK:job['status']='cancelled';job['error']=None
    except Exception as e:
        with LOCK:job['status']='error';job['error']=str(e)
    finally:
        with LOCK:
            if hasattr(runner,'session_diagnostics'):job['session_diagnostics']=runner.session_diagnostics
            job.pop('_runner',None);job['finished']=time.time();job['current']=None;job['active']=[];job['elapsed_seconds']=round(previous+time.perf_counter()-began,3)
            job.pop('_pool_variants',None);job.pop('_pool_draws',None)
            if job['status']=='complete':job['eta_seconds']=0
            persist(job)

def resume_job(job,workers):
    if job.get('initial_state_policy',{}).get('id')!='controlled-start-v3':raise ValueError('旧实验的开赛状态规则不同，请新建实验，避免混合结果')
    if job.get('batch_schema')!=1:raise ValueError('旧任务缺少批量校验记录，请新建实验')
    provenance=json.loads((job['_dir']/'provenance.json').read_text(encoding='utf8'))
    if job.get('event_details',True)!=provenance.get('event_details',True):raise ValueError('事件采集模式与原任务不同，不能混合续跑')
    if provenance.get('native_dll_sha256')!=ENGINE_DLL_SHA256 or provenance.get('engine_resource_fingerprint')!=ENGINE_COMPATIBILITY['resource_fingerprint']:raise ValueError('实际引擎或比赛资源与本实验不同，请新建实验以免混合结果')
    for name,path in [('host_sha256',NATIVE/'FM27Simulator.exe'),('fixture_sha256',NATIVE/'fixtures/match.pkm')]:
        if provenance[name]!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('引擎或比赛样本已改变，请新建实验以免混合结果')
    scenarios=[]
    for label,digest in provenance['config_hashes'].items():
        config=job['_dir']/f'{label}.bin'
        if hashlib.sha256(config.read_bytes()).hexdigest()!=digest:raise ValueError('保存的战术输入已改变')
        scenario=json.loads((job['_dir']/f'{label}.json').read_text(encoding='utf8'))
        if encode_scenario(scenario)!=config.read_bytes():raise ValueError('方案与已保存的比赛输入不一致')
        scenarios.append((label,scenario))
    pool=provenance.get('pool')
    if pool:
        configs=provenance.get('configs')
        if not isinstance(configs,list)or not configs:raise ValueError('该实验缺少客队战术池展开方案，无法续跑')
        entries=pool.get('entries')
        if not isinstance(entries,list)or not entries:raise ValueError('该实验的客队战术池条目记录不完整')
        if str(pool.get('salt'))!=str(job['id']):raise ValueError('客队战术池随机抽取来源与任务不符')
        groups={}
        for item in configs:
            config=job['_dir']/item['config_file'];document=job['_dir']/item['scenario_file']
            if hashlib.sha256(config.read_bytes()).hexdigest()!=item['config_sha256']:raise ValueError('保存的客队战术池输入已改变')
            if hashlib.sha256(document.read_bytes()).hexdigest()!=item['scenario_sha256']:raise ValueError('保存的客队战术池方案已改变')
            scenario=json.loads(document.read_text(encoding='utf8'))
            if encode_scenario(scenario)!=config.read_bytes():raise ValueError('客队战术池方案与已保存的比赛输入不一致')
            groups.setdefault(item['label'],{})[item['entry']]=scenario
        if set(groups)!={label for label,_ in scenarios}:raise ValueError('客队战术池展开方案与实验方案不符')
        for label,items in groups.items():
            if sorted(items)!=list(range(len(entries))):raise ValueError('客队战术池展开方案序号不连续')
            groups[label]=[items[index]for index in range(len(entries))]
        draws=pool.get('draws')
        if not isinstance(draws,dict)or set(draws)!={str(seed)for seed in provenance['seeds']}:raise ValueError('客队战术池随机抽取记录不完整')
        for index in draws.values():
            if type(index)is not int or not 0<=index<len(entries):raise ValueError('客队战术池随机抽取记录越界')
        job['_pool_variants']=groups;job['_pool_draws']={seed:index for seed,index in draws.items()}
        if not isinstance(job.get('tactic_pool'),dict):
            job['tactic_pool']={'profile':str(pool.get('profile')or fm27_tactic_pool.PROFILE),'enabled':True,'salt':str(pool['salt']),
                'uniform':copy.deepcopy(pool.get('uniform',fm27_tactic_pool.defaults()['uniform'])),'entries':copy.deepcopy(entries),
                'draws':{'total':len(draws),'counts':{str(index):0 for index in range(len(entries))}}}
    for run in job['runs']:
        expected=dict(scenarios)[run['variant']]
        if pool:
            index=job['_pool_draws'][str(run['seed'])]
            if run.get('tactic_pool_entry',{}).get('index')!=index:
                raise ValueError('已完成比赛的客队战术与原抽签不符')
            expected=job['_pool_variants'][run['variant']][index]
        path=job['_dir']/run['log']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=run['log_sha256']:raise ValueError('已完成比赛日志已改变')
        if inspect_saved_run(job['_dir'],run,expected)['result']!=run['result']:raise ValueError('已完成比赛结果校验失败')
    if job['completed']>=job['total']:raise ValueError('该实验已经完成')
    if job.get('failures'):job.setdefault('failure_history',[]).extend(copy.deepcopy(job['failures']))
    job.update(status='queued',workers=workers,failures=[],error=None,_cancel=False)
    persist(job);POOL.submit(execute,job,scenarios,provenance['seeds'])

class DesktopPresence:
    """One lease per app document; reloads get an eight-second grace period."""
    def __init__(self):
        self.lock=threading.Lock();self.pages={};self.seen=False;self.empty_since=None
    def update(self,data):
        key=data.get('page');action=data.get('action')
        if not isinstance(key,str)or not 1<=len(key)<=100 or action not in('open','close'):raise ValueError('Invalid desktop presence')
        with self.lock:
            if action=='open':self.pages[key]=time.monotonic();self.seen=True;self.empty_since=None
            else:self.pages.pop(key,None)
        return self.status()
    def status(self):
        with self.lock:
            now=time.monotonic();self.pages={k:v for k,v in self.pages.items()if now-v<180}
            if self.pages:self.empty_since=None
            elif self.seen and self.empty_since is None:self.empty_since=now
            return {'pages':len(self.pages),'seen':self.seen,'close_ready':self.empty_since is not None and now-self.empty_since>=8}
DESKTOP_PRESENCE=DesktopPresence()

def agent_versions():
    adapter=None
    try:adapter=json.loads((NATIVE/'adapter_version.json').read_text(encoding='utf8')).get('version')
    except (OSError,ValueError):pass
    profile=ENGINE_COMPATIBILITY.get('profile') if isinstance(ENGINE_COMPATIBILITY,dict) else None
    return {'server':APP_VERSION,'adapter':adapter,'engine_build':profile.get('version') if isinstance(profile,dict) else None,'scenario_schema':3,'batch_schema':1}

def start_run(data,path='/api/run',allow_queue=True):
    """Create one match batch; the web UI forbids concurrency, the agent queues it."""
    if path not in ('/api/run','/api/run-episodes'):raise ValueError('未知运行类型')
    if SAVE_LIBRARY.real_active:raise ValueError('请等待真实AI战术生成完成后运行比赛')
    if SAVE_LIBRARY.active:raise ValueError('请等待存档及历史输入解析完成后运行比赛')
    event_details=data.get('event_details',True)
    if type(event_details)is not bool:raise ValueError('事件明细开关必须为布尔值')
    if path=='/api/run-episodes'and not event_details:raise ValueError('定位球片段需要事件明细；快速模式仅适用于整场比赛')
    scenario=validate_scenario(data['scenario']);reference=validate_scenario(data['reference']) if data.get('reference')else None
    if path=='/api/run-episodes'and(enabled_pool(scenario)or enabled_pool(reference)):
        raise ValueError('随机客队战术池不支持定位球片段')
    episode=None
    if path=='/api/run-episodes':
        if any('experimental_execution' in item for item in (scenario, reference) if item is not None):
            raise ValueError('实验执行力目前仅支持整场比赛')
        tested_type=integer(data['type'],0,9,'定位球类型');tested_side=integer(data['side'],0,1,'测试球队');variant=integer(data.get('variant',0),0,2,'套路序号');seconds=integer(data.get('window_seconds',30),5,120,'观察窗口秒数')
        for target in [scenario]+([reference]if reference else[]):
            routines=target['teams'][tested_side]['setpieces']['routines'][str(tested_type)]
            if variant>=len(routines):raise ValueError('测试套路不存在')
            target['teams'][tested_side]['setpieces']['routines'][str(tested_type)]=[copy.deepcopy(routines[variant])]
        episode={'type':tested_type if tested_type>=5 else tested_type+5,'tested_type':tested_type,'tested_side':tested_side,'attacking_side':tested_side if tested_type>=5 else 1-tested_side,'window_seconds':seconds}
    seeds=data['seeds']
    if not isinstance(seeds,list)or not 1<=len(seeds)<=10000 or len(set(seeds))!=len(seeds):raise ValueError('需要1–10000个不重复种子')
    seeds=[integer(s,0,0xffffffff,'随机种子')for s in seeds]
    workers=integer(data.get('workers',BATCH_LIMITS['recommended']),1,BATCH_LIMITS['maximum'],'并行数')
    variants=[('A',reference),('B',scenario)]if reference else[('B',scenario)]
    pool=scenario.get('away_tactic_pool')if isinstance(scenario.get('away_tactic_pool'),dict)else None
    if pool is None and reference:pool=reference.get('away_tactic_pool')if isinstance(reference.get('away_tactic_pool'),dict)else None
    if not(pool and pool.get('enabled')):pool=None
    expanded={}
    if pool:
        if any('native_generation' in item for _,item in variants):
            raise ValueError('随机客队战术池不能与电脑生成战术同时使用')
        expanded={label:[validate_scenario(fm27_tactic_pool.expand({**item,'away_tactic_pool':pool},index))for index in range(len(pool['entries']))]for label,item in variants}
    with LOCK:
        desktop_engine.require_available(ENGINE_COMPATIBILITY)
        if not allow_queue and any(j['status']in ('queued','running')for j in JOBS.values()):
            raise EngineBusy('已有比赛运行中，请等待或取消')
        key=secrets.token_hex(6);directory=RUNS/f'{datetime.now():%Y%m%d_%H%M%S}_{key}';directory.mkdir(parents=True)
        for label,item in variants:
            (directory/f'{label}.json').write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf8');(directory/f'{label}.bin').write_bytes(encode_scenario(item))
            (directory/f'{label}.phases.json').write_text(json.dumps(phase_inputs.pack(item,CATALOG),ensure_ascii=False,indent=2),encoding='utf8')
        pool_summary=pool_draws=None;configs=[]
        if pool:
            pool_summary=fm27_tactic_pool.summary(pool,key);pool_draws=fm27_tactic_pool.draws(pool,seeds,key)
            for label,items in expanded.items():
                for entry_index,item in enumerate(items):
                    document=json.dumps(item,ensure_ascii=False,indent=2).encode('utf8');payload=encode_scenario(item)
                    (directory/f'{label}_pool{entry_index}.json').write_bytes(document);(directory/f'{label}_pool{entry_index}.bin').write_bytes(payload)
                    configs.append({'label':label,'entry':entry_index,'entry_name':pool['entries'][entry_index]['name'],
                        'config_file':f'{label}_pool{entry_index}.bin','config_sha256':hashlib.sha256(payload).hexdigest(),
                        'scenario_file':f'{label}_pool{entry_index}.json','scenario_sha256':hashlib.sha256(document).hexdigest()})
        provenance={'host_sha256':hashlib.sha256((NATIVE/'FM27Simulator.exe').read_bytes()).hexdigest(),'fixture_sha256':hashlib.sha256((NATIVE/'fixtures/match.pkm').read_bytes()).hexdigest(),'native_dll_sha256':ENGINE_DLL_SHA256,'engine_compatibility':copy.deepcopy(ENGINE_COMPATIBILITY),'engine_resource_fingerprint':ENGINE_COMPATIBILITY['resource_fingerprint'],'seeds':seeds,'fixture_me_version':'26.8.0.0','config_hashes':{label:hashlib.sha256((directory/f'{label}.bin').read_bytes()).hexdigest()for label,_ in variants}}
        provenance['event_details']=event_details
        if pool:
            provenance['pool']={'profile':pool_summary['profile'],'enabled':True,'salt':key,'uniform':copy.deepcopy(pool_summary['uniform']),
                'entries':copy.deepcopy(pool_summary['entries']),'draws':{str(seed):index for seed,index in pool_draws.items()}}
            provenance['configs']=copy.deepcopy(configs)
        (directory/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf8')
        job={'batch_schema':1,'workers':workers,'failures':[],'active':[],'id':key,'status':'queued','completed':0,'total':len(seeds)*len(variants),'runs':[],'metrics':{},'created':time.time(),'output_dir':str(directory),'_dir':directory}
        job['name']=experiment_name(data.get('name'),f"{scenario['teams'][0]['name']} · {scenario['teams'][0].get('tactic_name') or '战术实验'} · {len(seeds)}场")
        job['event_details']=event_details
        job['engine_compatibility']=copy.deepcopy(ENGINE_COMPATIBILITY)
        job['runtime_mode']='isolated_native_episode'if episode else'reused_native_worker'
        job['jobs_per_native_session']=1 if episode else 64
        job['initial_state_policy']={'id':'controlled-start-v3','player_values':copy.deepcopy(profiles.CONTROLLED_START),'morale_verified':True,'cohesion_verified':True}
        job['mode']='comparison'if reference else'single';job['variant_names']={label:item['teams'][0].get('tactic_name','')for label,item in variants}
        job['team_names']={label:[t['name']for t in item['teams']]for label,item in variants}
        if episode:job.update(experiment_type='setpiece_episode',episode_settings=episode)
        elif pool:
            job['tactic_pool']={**pool_summary,'draws':{'total':len(pool_draws),'counts':{str(index):0 for index in range(len(pool['entries']))}}}
            job['_pool_variants']=expanded;job['_pool_draws']={str(seed):index for seed,index in pool_draws.items()}
        JOBS[key]=job;persist(job);POOL.submit(execute,job,variants,seeds)
        position=agent_server.run_queue_state(JOBS).get(key)
        return {'id':key,'total':job['total'],'workers':workers,'mode':job['mode'],
                'seed_count':len(seeds),'queued':position is not None and position>1,
                'queue_position':position,'variant_names':job['variant_names']}

def select_engine(path):
    global ENGINE_COMPATIBILITY,ENGINE_DLL_SHA256
    if not isinstance(path,str)or not path.strip():raise ValueError('请填写游戏安装目录')
    selected=str(Path(path.strip()).resolve())
    with IMPORT_LOCK,LOCK:
        if SAVE_LIBRARY.active:raise ValueError('存档／历史输入解析中不能更换引擎')
        if any(j['status']in('queued','running')for j in JOBS.values()):raise ValueError('已有比赛运行中，不能更换游戏目录')
        os.environ['FM27_GAME_ROOT']=selected
        ENGINE_COMPATIBILITY=desktop_engine.initialize(ROOT)
        ENGINE_DLL_SHA256=ENGINE_COMPATIBILITY['actual_dll_sha256']
        (RUNS.parent/'game-root.txt').write_text(selected,encoding='utf-8-sig')
        return ENGINE_COMPATIBILITY

def request_shutdown():
    with LOCK:
        for job in JOBS.values():
            if job.get('status')in('queued','running'):
                job['_cancel']=True
                runner=job.get('_runner')
                if runner is not None:runner.cancel()
    def stop():
        time.sleep(.2)
        if AGENT_SERVER is not None:AGENT_SERVER.shutdown()
    threading.Thread(target=stop,daemon=True).start()

def cancel_job(job):
    runner=None
    with LOCK:
        if job.get('status')=='running':runner=job.get('_runner')
        agent_server.cancel_run_state(job)
        persist(job)
    if runner is not None:runner.cancel()
    return {'accepted':True}

def resume_job_api(job,data):
    workers=integer(data.get('workers',BATCH_LIMITS['recommended']),1,BATCH_LIMITS['maximum'],'并行数')
    with LOCK:
        desktop_engine.require_available(ENGINE_COMPATIBILITY)
        if any(j['status']in('queued','running')for j in JOBS.values()):raise EngineBusy('已有比赛运行中')
        resume_job(job,workers)
    return {'id':job['id']}

def rename_job(job,name):
    with LOCK:
        job['name']=experiment_name(name,'未命名实验');persist(job)
        return {'id':job['id'],'name':job['name']}

def delete_job(job):
    if job['status']in('queued','running')or'_runner'in job:raise ValueError('请等待实验结束或取消后再删除')
    directory=job['_dir'];root=RUNS.resolve()
    if (directory.parent.resolve()!=root or directory.resolve().parent!=root or directory.is_symlink() or directory.is_junction()):raise ValueError('实验目录无效')
    try:
        if directory.exists():shutil.rmtree(directory)
    except OSError as error:
        if directory.is_dir()and not(directory/'summary.json').exists():persist(job)
        raise OSError(f'无法完整删除实验文件，请关闭占用文件后重试。{error}') from None
    with LOCK:JOBS.pop(job['id'],None)
    return {'id':job['id']}

class Handler(BaseHTTPRequestHandler):
    server_version='FM27Lab/1.0'
    def send(self,value,status=200,kind='application/json; charset=utf-8',headers=None):
        body=value if isinstance(value,bytes)else json.dumps(value,ensure_ascii=False).encode('utf8')
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        for name,header_value in (headers or {}).items():self.send_header(name,header_value)
        self.end_headers();self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        if not self.agent_guard(path):return
        if path==agent_contract.PREFIX or path.startswith(agent_contract.PREFIX+'/'):
            return self.agent_get(path)
        if path=='/api/desktop-presence':return self.send(DESKTOP_PRESENCE.status())
        if path=='/api/locale':return self.send(desktop_locale.system_language())
        if path=='/api/catalog':return self.send(CATALOG)
        if path=='/api/defaults':return self.send(DEFAULT)
        if path=='/api/phase-defaults':return self.send(phase_inputs.pack(DEFAULT,CATALOG))
        if path=='/api/status':return self.send({'engine':'original_native','engine_compatibility':ENGINE_COMPATIBILITY,'server_pid':os.getpid(),'application_version':'v1111.2','fmf_version_validation':'original_game_reader','fixture_me_version':'26.8.0.0','independent':True,'team_groups':len(GROUPS),'team_options':sum(len(g['options'])for g in GROUPS.values()),'player_groups':17,'roles':79,'batch':{'max_matches_per_variant':10000,**BATCH_LIMITS,'isolation':'bounded_reused_native_sessions','jobs_per_native_session':64,'postprocess_workers':2,'whole_match_automatic_retries':0}})
        if path=='/api/save/status':
            query=parse_qs(urlparse(self.path).query)
            try: return self.send(SAVE_LIBRARY.status(query.get('id',[None])[0]))
            except (ValueError,OSError) as error: return self.send({'error':str(error)},400)
        if path=='/api/save/leagues':
            query=parse_qs(urlparse(self.path).query)
            try: return self.send(SAVE_LIBRARY.league_catalog(query.get('id',[None])[0]))
            except (ValueError,OSError) as error: return self.send({'error':str(error)},400)
        if path=='/api/jobs':
            with LOCK:return self.send([{k:v for k,v in j.items()if not k.startswith('_')and(k!='runs'or parse_qs(urlparse(self.path).query).get('brief')!=['1'])}for j in sorted(JOBS.values(),key=lambda j:j.get('created',0))])
        parts=path.strip('/').split('/')
        if len(parts)>=3 and parts[:2]==['api','jobs']:
            with LOCK:
                job=JOBS.get(parts[2])
                if not job:return self.send({'error':'任务不存在'},404)
                if len(parts)==3:
                    progress=parse_qs(urlparse(self.path).query).get('progress');unchanged=progress==[str(job['completed'])]
                    delta=bool(progress and progress[0].isdigit()and int(progress[0])<=job['completed']and all('sequence'in r for r in job['runs']))
                    response={k:v for k,v in job.items()if not k.startswith('_')and(k!='runs'or not(unchanged or delta))};response['runs_unchanged']=unchanged
                    if delta and not unchanged:response['runs_delta']=[r for r in job['runs']if r['sequence']>int(progress[0])]
                    return self.send(response)
                if len(parts)==4 and parts[3]=='export':
                    package={'summary':{k:v for k,v in job.items() if not k.startswith('_')},'scenarios':{}}
                    for variant in job.get('schedule',{}) or ('A','B'):
                        p=job['_dir']/f'{variant}.json'
                        if p.exists():package['scenarios'][variant]=phase_inputs.pack(json.loads(p.read_text(encoding='utf8')),CATALOG)
                    package['provenance']=json.loads((job['_dir']/'provenance.json').read_text(encoding='utf8'))
                    return self.send(package)
                if len(parts)==5 and parts[3]=='logs':
                    name=parts[4]
                    if name not in [r['log']for r in job['runs']]:return self.send({'error':'日志不存在'},404)
                    return self.send((job['_dir']/name).read_bytes(),kind='application/x-ndjson; charset=utf-8')
        if path in STATIC_FILES:
            name=STATIC_FILES[path];kind={'html':'text/html','js':'text/javascript','css':'text/css'}[name.split('.')[-1]]
            headers={'Set-Cookie':f'fm27_session={AGENT_TOKEN}; HttpOnly; SameSite=Strict; Path=/'}if path=='/'else None
            return self.send((WEB/name).read_bytes(),kind=kind+'; charset=utf-8',headers=headers)
        self.send({'error':'不存在'},404)
    def do_POST(self):
        origin=self.headers.get('Origin')
        if origin and origin!=f'http://{self.headers.get("Host")}':return self.send({'error':'拒绝跨站调用'},403)
        path=urlparse(self.path).path
        if not self.agent_guard(path):return
        try:
            length=int(self.headers.get('Content-Length',0))
            if length==0 and (path==agent_contract.PREFIX or path.startswith(agent_contract.PREFIX+'/')):
                data={}
            else:
                limit=8000000 if path in ('/api/import-fmf','/api/pool/import-fmf','/api/save/league-pool') else (6000000 if path==agent_contract.PREFIX+'/fmf/import' else 1500000)
                if not 0<length<=limit:raise ValueError('请求大小无效')
                data=json.loads(self.rfile.read(length))
            if path==agent_contract.PREFIX or path.startswith(agent_contract.PREFIX+'/'):return self.agent_post(path,data)
            if path=='/api/jobs/rename':
                with LOCK:
                    job=JOBS.get(data.get('id'))
                    if not job: raise ValueError('实验不存在')
                    job['name']=experiment_name(data.get('name'),'未命名实验');persist(job)
                    return self.send({'id':job['id'],'name':job['name']})
            if path=='/api/jobs/delete':
                with LOCK:
                    job=JOBS.get(data.get('id'))
                    if not job:return self.send({'error':'实验不存在'},404)
                    if job['status'] in ('queued','running') or '_runner' in job:
                        return self.send({'error':'请等待实验结束或取消后再删除'},409)
                    directory=job['_dir']
                    root=RUNS.resolve()
                    if (directory.parent.resolve()!=root or directory.resolve().parent!=root
                            or directory.is_symlink() or directory.is_junction()):
                        raise ValueError('实验目录无效')
                    try:
                        if directory.exists():shutil.rmtree(directory)
                    except OSError as e:
                        if directory.is_dir() and not (directory/'summary.json').exists():persist(job)
                        return self.send({'error':f'无法完整删除实验文件，请关闭占用文件后重试。{e}'},500)
                    del JOBS[job['id']]
                return self.send({'id':job['id']})
            if path.startswith('/api/save/'):
                if path=='/api/save/pick': return self.send({'path':desktop_save_mode.choose_save_file()})
                if path=='/api/save/pick-folder': return self.send({'path':desktop_save_mode.choose_folder()})
                if path=='/api/save/leagues':
                    return self.send(SAVE_LIBRARY.league_catalog(data['id']))
                if path=='/api/save/league-library':
                    return self.send(SAVE_LIBRARY.league_library(data['id'],data['league']))
                if path=='/api/save/league-export':
                    require_league_idle('导出存档战术')
                    return self.send(SAVE_LIBRARY.export_league_tactics(data['id'],data['league'],data['directory']))
                if path=='/api/save/real-generation-status':
                    return self.send(SAVE_LIBRARY.real_generation_status(data['id'],data['league']))
                if path=='/api/save/real-generation':
                    require_league_idle('生成真实AI战术')
                    if data.get('club_uid') is not None:
                        return self.send(SAVE_LIBRARY.generate_real_team(data['id'],data['league'],data['club_uid'],bool(data.get('force'))))
                    return self.send(SAVE_LIBRARY.start_real_generation(data['id'],data['league'],data.get('clubs'),bool(data.get('force'))))
                if path=='/api/save/league-pool':
                    require_league_idle('导入客队战术池')
                    return self.send(SAVE_LIBRARY.import_league_tactics_pool(data['id'],data['league'],data['scenario']))
                if path=='/api/save/import': return self.send(SAVE_LIBRARY.start(data['path']),202)
                if path=='/api/save/club': return self.send(SAVE_LIBRARY.club(data['id'],data['club_uid']))
                if path=='/api/save/load':
                    with IMPORT_LOCK,LOCK:
                        if any(j['status']in ('queued','running')for j in JOBS.values()):raise ValueError('请等待比赛结束后载入新球队')
                        return self.send(SAVE_LIBRARY.load_team(data['id'],data['club_uid'],data['tactic_index'],data.get('lineup'),0,data['scenario'],data.get('bench')))
                if path=='/api/save/selection':
                    return self.send({'scenario':SAVE_LIBRARY.select_squad(data['scenario'],0,data['lineup'],data['bench'])})
                if path=='/api/save/opponents':
                    with LOCK:
                        if any(j['status']in ('queued','running')for j in JOBS.values()): raise ValueError('请等待比赛结束后解析历史输入')
                        return self.send(SAVE_LIBRARY.begin_opponents(data['id'],data['club_uid']))
                if path=='/api/save/preview':
                    report=SAVE_LIBRARY.inspect_opponents(data['id'],data['club_uid'])
                    opponent=next((o for o in report['opponents'] if o['key']==data['key']),None)
                    if not opponent: raise ValueError('对手方案未通过核实')
                    scenario=validate_scenario(data['scenario'])
                    if opponent.get('source_kind')=='original_ai_generation':
                        return self.send(desktop_generation_catalog.preview(SAVE_LIBRARY,data['id'],int(data['club_uid']),opponent,scenario))
                    team=SAVE_LIBRARY.opponent_team(data['id'],opponent.get('fixture_key',opponent['key']),opponent['side'],scenario['teams'][0])
                    return self.send({'team':team,'source':{**opponent,'match_roster_count':team.get('roster_size',len(team['players'])),'roster_pending':False}})
                if path=='/api/save/run': return self.send(create_save_job(data),202)
            if path=='/api/desktop-presence':return self.send(DESKTOP_PRESENCE.update(data))
            if path=='/api/engine/select':
                global ENGINE_COMPATIBILITY,ENGINE_DLL_SHA256
                selected=data.get('path')
                if not isinstance(selected,str) or not selected.strip():raise ValueError('请填写游戏安装目录')
                selected=str(Path(selected.strip()).resolve())
                with IMPORT_LOCK,LOCK:
                    if SAVE_LIBRARY.real_active:return self.send({'error':'真实AI战术生成中不能更换游戏目录'},409)
                    if SAVE_LIBRARY.active:raise ValueError('存档／历史输入解析中不能更换引擎')
                    if any(j['status']in ('queued','running')for j in JOBS.values()):return self.send({'error':'比赛运行中不能更换游戏目录'},409)
                    os.environ['FM27_GAME_ROOT']=selected
                    ENGINE_COMPATIBILITY=desktop_engine.initialize(ROOT)
                    ENGINE_DLL_SHA256=ENGINE_COMPATIBILITY['actual_dll_sha256']
                    (RUNS.parent/'game-root.txt').write_text(selected,encoding='utf-8-sig')
                    return self.send(ENGINE_COMPATIBILITY)
            if path in ('/api/import-fmf','/api/pool/import-fmf','/api/export-fmf','/api/export-setpiece'):
                desktop_engine.require_available(ENGINE_COMPATIBILITY)
            if path=='/api/import-fmf':return self.send(import_fmf(data))
            if path=='/api/pool/import-fmf':return self.send(import_pool_fmf(data))
            if path=='/api/export-fmf':return self.send(export_fmf(data))
            if path=='/api/export-setpiece':return self.send(export_setpiece(data))
            if path=='/api/validate':return self.send({'scenario':validate_scenario(data),'records':(len(encode_scenario(data))-12)//20})
            if path=='/api/phase-plan':return self.send({'scenario':phase_inputs.pack(validate_scenario(data),CATALOG)})
            if path=='/api/repair':return self.send(repair_saved_scenario(data))
            if path in('/api/run','/api/run-episodes'):
                return self.send(start_run(data,path,allow_queue=False),202)
            if path=='/api/resume':
                job=JOBS.get(data.get('id'))
                if not job:raise ValueError('任务不存在')
                return self.send(resume_job_api(job,data),202)
            if path=='/api/cancel':
                job=JOBS.get(data.get('id'))
                return self.send(cancel_job(job) if job else {'accepted':False})
            return self.send({'error':'不存在'},404)
        except EngineBusy as e:return self.send({'error':str(e)},409)
        except (KeyError,TypeError,ValueError,OverflowError) as e:return self.send({'error':str(e)},400)
        except Exception as e:return self.send({'error':str(e)},500)
    def agent_guard(self,path):
        if not agent_contract.host_allowed(self.headers.get('Host'),self.server.server_address[1]):
            return self.agent_error(agent_server.AgentHttpError(403,'forbidden_host','Host 不在白名单'))
        if agent_contract.is_exempt(path,STATIC_FILES):return True
        if agent_contract.authorized(self.headers,AGENT_TOKEN):return True
        return self.agent_error(agent_server.AgentHttpError(401,'unauthorized','缺少或错误 token'))
    def agent_error(self,error):
        headers={'Retry-After':str(error.retry_after_seconds)}if error.retry_after_seconds is not None else None
        return self.send(error.payload(),error.status,headers=headers)
    def agent_get(self,path):
        query={key:values[0]for key,values in parse_qs(urlparse(self.path).query).items()}
        try:status,payload,headers=AGENT_ROUTER.get(path,query)
        except agent_server.AgentHttpError as error:return self.agent_error(error)
        except Exception as error:return self.agent_error(agent_server.AgentHttpError(500,'internal_error',str(error)))
        if isinstance(payload,(bytes,bytearray)):
            content_type=(headers or {}).pop('Content-Type','application/octet-stream')
            return self.send(bytes(payload),status,content_type,headers=headers)
        return self.send(payload,status,headers=headers)
    def agent_post(self,path,data):
        try:status,payload,headers=AGENT_ROUTER.post(path,data,self.headers)
        except agent_server.AgentHttpError as error:return self.agent_error(error)
        except Exception as error:return self.agent_error(agent_server.AgentHttpError(500,'internal_error',str(error)))
        return self.send(payload,status,headers=headers)

def main():
    global AGENT_TOKEN,AGENT_ROUTER,AGENT_SERVER
    process_owner=own_child_processes()
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);args=p.parse_args()
    for summary in sorted((RUNS).glob('*/summary.json'),reverse=True)[:40]:
        try:
            job=json.loads(summary.read_text(encoding='utf8'))
            if not isinstance(job.get('runs'),list)or not isinstance(job.get('id'),str):continue
            job['_dir']=summary.parent
            if job.get('status')in ('queued','running'):
                job.update(status='interrupted',error='服务重启，任务未完整完成；已完成比赛仍可查看。',current=None,active=[],eta_seconds=None)
            JOBS[job['id']]=job
        except (ValueError,OSError):continue
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    AGENT_SERVER=server;AGENT_TOKEN=agent_contract.new_token();port=server.server_address[1]
    AGENT_ROUTER=agent_server.Router(sys.modules[__name__],token=AGENT_TOKEN,port=port)
    endpoint=agent_contract.build_endpoint(port=port,token=AGENT_TOKEN,data_dir=RUNS.parent,engine_root=ROOT,game_root=os.environ.get('FM27_GAME_ROOT',''),versions=agent_versions(),capabilities=AGENT_ROUTER.manifest()['capabilities'],limits=AGENT_ROUTER.limits())
    try:
        agent_contract.write_endpoint(RUNS.parent,endpoint)
        agent_contract.write_agent_scripts(RUNS.parent,Path(__file__).resolve().parent,sys.executable)
    except OSError as error:
        print(f'Agent endpoint unavailable: {error}',file=sys.stderr,flush=True)
    print(f'FM27 tactics lab: http://127.0.0.1:{port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:
        with LOCK:
            for job in JOBS.values():
                if job.get('status')in ('queued','running'):
                    job['_cancel']=True
                    if job.get('_runner'):job['_runner'].cancel()
        server.server_close();POOL.shutdown(wait=False,cancel_futures=True)
        agent_contract.remove_endpoint(RUNS.parent)
if __name__=='__main__':main()
