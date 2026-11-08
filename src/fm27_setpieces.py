import os
"""Typed set-piece scenarios, backed by original native routines and enum policies."""
import copy,json
from pathlib import Path
ROOT=Path(os.environ["FM27_ENGINE_ROOT"])
ENUMS=json.loads((ROOT/'fm27_research/setpiece_enum_catalog.json').read_text(encoding='utf8'))
SNAP=json.loads((ROOT/'fm27_native/editor_setpieces_default.json').read_text(encoding='utf8'))
TYPE_NAMES=['防守角球','防守直接任意球','防守边路任意球','防守远距离任意球','防守界外球','进攻角球','进攻直接任意球','进攻边路任意球','进攻远距离任意球','进攻界外球']
CATALOG={**ENUMS,'types':[{'id':i,'label':name,'strategy_kind':'corner_target'if i==5 else 'free_kick_risk'if i in (6,7,8)else 'defensive_line'if i in (2,3)else None,'swing':i in (5,7)}for i,name in enumerate(TYPE_NAMES)],'frequencies':[{'id':0,'label':'较少 · 权重2'},{'id':1,'label':'正常 · 权重5'},{'id':2,'label':'较多 · 权重8'}]}
def defaults(side):
 t=SNAP['teams'][side];routines={}
 for variants in t['routine_variants']:
  routines[str(variants[0]['type'])]=[]
  for i,r in enumerate(variants):
   groups=[[]for _ in range(8)]
   for g in r['groups']:groups[g['id']]=list(g['values'])
   backups=[[0]*len(g)for g in groups]
   for g,j,value in r['backups']:backups[g][j]=value
   routines[str(r['type'])].append({'name':f'{TYPE_NAMES[r["type"]]} {i+1}','opaque_flags':0,'frequency':r['frequency'],'strategy':r['strategy'],'swing':r['swing'],'groups':groups,'backups':backups,'priority':r['priority']})
 raw=bytes.fromhex(t['manager_tactical_hex']);styles=list(raw[0x16f0-0x2e0:0x16f3-0x2e0])
 return {'routines':routines,'throw_styles':styles,'role_priorities':{str(g):[]for g in range(8)}}
DEFAULTS=[defaults(0),defaults(1)]
def normalize(value,side,roster_size):
 def integer(v,lo,hi):
  if type(v)is not int or not lo<=v<=hi:raise ValueError('定位球设置数值无效')
  return v
 if not isinstance(value,dict):raise ValueError('定位球设置格式错误')
 out=copy.deepcopy(DEFAULTS[side]);styles=value['throw_styles']
 if len(styles)!=3:raise ValueError('界外球必须包含后场、中场和前场三种策略')
 out['throw_styles']=[integer(v,0,1)for v in styles]
 for g in range(8):
  v=value['role_priorities'][str(g)]
  if not isinstance(v,list)or len(v)>roster_size or any(type(i)is not int for i in v)or len(set(v))!=len(v):raise ValueError('定位球角色球员顺序无效')
  out['role_priorities'][str(g)]=[integer(i,0,roster_size-1)for i in v]
 for kind in range(10):
  rows=value['routines'][str(kind)];base=DEFAULTS[side]['routines'][str(kind)][0];result=[]
  if not isinstance(rows,list)or not 1<=len(rows)<=3:raise ValueError('每种定位球保留1–3套套路')
  for row in rows:
   r={'name':str(row['name'])[:48],'frequency':integer(row['frequency'],0,2)}
   r['opaque_flags']=integer(row.get('opaque_flags',0),0,255)
   for k in ['strategy','swing']:
    if base[k]==255:
     if row[k]!=255:raise ValueError('该类型定位球不使用此发球策略')
     r[k]=255
    elif k=='strategy' and (kind,row[k]) in ((5,3),(7,6),(8,3)):
     r[k]=row[k]
    else:r[k]=integer(row[k],0,1 if k=='swing'else 2)
   priority=row['priority']
   if not isinstance(priority,list)or sorted(priority)!=sorted(base['priority']):raise ValueError('定位球分配顺序必须保留原版角色类别')
   r['priority']=list(priority)
   if len(row['groups'])!=8 or len(row['backups'])!=8:raise ValueError('定位球任务组不完整')
   r['groups']=[];r['backups']=[]
   for g in range(8):
    tasks=row['groups'][g];backups=row['backups'][g]
    if not isinstance(tasks,list)or len(tasks)>10 or len(backups)!=len(tasks):raise ValueError('定位球任务与备用任务不匹配')
    if tasks and g not in priority:raise ValueError('该定位球不使用此角色类别')
    for task in tasks:
     integer(task,0,15)
     if task not in ENUMS['allowed'][str(g)]:raise ValueError('该定位球角色不能使用所选任务')
    r['groups'].append(list(tasks));r['backups'].append([integer(v,0,15)for v in backups])
   expected=sum(map(len,base['groups']))
   if sum(map(len,r['groups']))!=expected:raise ValueError(f'{TYPE_NAMES[kind]}需要分配{expected}项任务；先移除旧任务再添加新任务')
   result.append(r)
  out['routines'][str(kind)]=result
 return out
def encode(value,side):
 records=[];base=DEFAULTS[side]
 for i,v in enumerate(value['throw_styles']):
  if v!=base['throw_styles'][i]:records.append((46,side,i,0,v))
 for g in range(8):
  rows=value['role_priorities'][str(g)]
  if rows!=base['role_priorities'][str(g)]:
   records.append((30,side,12+g,0xffffffff,0));records.extend((30,side,12+g,i,v)for i,v in enumerate(rows))
 for kind in range(10):
  rows=value['routines'][str(kind)]
  if rows==base['routines'][str(kind)]:continue
  records.append((40,side,kind,0,len(rows)))
  for i,row in enumerate(rows):
   slot=kind*16+i
   records.append((41,side,slot,0,row['frequency']))
   records.append((47,side,slot,0,row.get('opaque_flags',0)))
   if row['strategy']!=255:records.append((41,side,slot,1,row['strategy']))
   if row['swing']!=255:records.append((41,side,slot,2,row['swing']))
   records.append((42,side,slot,0,0))
   for g in row['priority']:
    records.extend((43,side,slot,g,v)for v in row['groups'][g])
   records.extend((44,side,slot,j,g)for j,g in enumerate(row['priority']))
   for g,tasks in enumerate(row['groups']):
    records.extend((45,side,slot,g*32+j,row['backups'][g][j])for j in range(len(tasks)))
 return records
