"""Away tactic pool: structural validation, weighted draws and per-match expansion."""
import copy
import random

PROFILE='away-tactic-pool-v1'
MAX_ENTRIES=64
DEFAULT_ATTRIBUTE_VALUE=15
MAX_NAME=60
MAX_WEIGHT=1000
POSITION_ATTRIBUTES=15
POSITION_FAMILIARITY=20
POSITION_ATTRIBUTE_INDEX={'GK':0,'SW':1,'DL':2,'DC':3,'DCR':3,'DCL':3,'DR':4,'DM':5,'DMC':5,'DMR':5,'DML':5,
    'ML':6,'MC':7,'MCL':7,'MCR':7,'MR':8,'AML':9,'AMC':10,'AMCL':10,'AMCR':10,'AMR':11,
    'ST':12,'STR':12,'STL':12,'WBL':13,'WBR':14}


def defaults():
    return {'enabled':False,'entries':[],'uniform':{'enabled':True,'attribute_value':DEFAULT_ATTRIBUTE_VALUE}}


def _integer(value,low,high,label):
    if type(value)is not int or not low<=value<=high:raise ValueError(f'{label}必须为 {low}–{high} 的整数')
    return value


def _flag(value,label):
    if type(value)is not bool:raise ValueError(label+'必须为布尔值')
    return value


def _text(value,label):
    if not isinstance(value,str)or not 1<=len(value.strip())<=MAX_NAME or any(ord(c)<32 for c in value):
        raise ValueError(f'{label}须为1–{MAX_NAME}个可读字符')
    return value.strip()


def _instructions(value,label):
    if not isinstance(value,dict):raise ValueError(label+'格式无效')
    result={}
    for key,item in value.items():
        if not isinstance(key,str)or not key.isascii()or not key.isdigit():raise ValueError(label+'键必须为十进制数字')
        result[str(int(key))]=_integer(item,0,0xffffffff,label)
    return result


def _source_plan(value,label):
    if not isinstance(value,dict)or set(value)!={'value','signature'}or not isinstance(value['value'],dict):raise ValueError(label+'原生方案来源无效')
    signature=value['signature']
    if not isinstance(signature,str)or len(signature)!=64 or any(c not in '0123456789abcdef'for c in signature.lower()):
        raise ValueError(label+'原生方案签名无效')
    return {'value':copy.deepcopy(value['value']),'signature':signature}


def _cell(value,label):
    if not isinstance(value,dict):raise ValueError(label+'位置格式无效')
    position=value.get('position');role=value.get('role');duty=value.get('duty')
    if not isinstance(position,str)or not 1<=len(position)<=16:raise ValueError(label+'位置名称无效')
    if not isinstance(role,str)or not 1<=len(role)<=40:raise ValueError(label+'角色名称无效')
    if not isinstance(duty,str)or not duty.isascii()or not duty.isdigit()or len(duty)>20:raise ValueError(label+'职责位无效')
    return {'position':position,'role':role,'duty':str(int(duty)),
        'instructions':_instructions(value.get('instructions',{}),label+'个人指令'),
        'target_player':_integer(value.get('target_player',255),0,255,label+'盯防球员'),
        'target_position':_integer(value.get('target_position',0),0,0xffffffffffffffff,label+'盯防位置')}


def _phases(value,label):
    if not isinstance(value,list)or len(value)!=2:raise ValueError(label+'必须包含有球和无球两个阶段')
    result=[]
    for cells in value:
        if not isinstance(cells,list)or len(cells)!=11:raise ValueError(label+'每个阶段必须有11个位置')
        result.append([_cell(cell,label)for cell in cells])
    return result


def _tactic(value,label):
    if not isinstance(value,dict):raise ValueError(label+'战术格式无效')
    name=value.get('tactic_name','')
    if not isinstance(name,str)or len(name)>120 or any(ord(c)<32 for c in name):raise ValueError(label+'战术名称无效')
    extra=value.get('native_extra_team_bits')
    if (not isinstance(extra,str)or not extra.isascii()or not extra.isdigit()or len(extra)>39
            or int(extra)>=1<<128):raise ValueError(label+'附加原生战术选项无效')
    tactic={'tactic_name':name,'mentality':_integer(value.get('mentality'),1,7,label+'比赛心态'),
        'instructions':_instructions(value.get('instructions'),label+'球队指令'),
        'native_extra_team_bits':str(int(extra)),'phases':_phases(value.get('phases'),label)}
    if value.get('native_source_plan')is not None:tactic['native_source_plan']=_source_plan(value['native_source_plan'],label)
    return tactic


def _entry(value,number):
    label=f'第 {number+1} 套客队战术'
    if not isinstance(value,dict):raise ValueError(label+'格式无效')
    if set(value)-{'name','weight','tactic'}:raise ValueError(label+'包含未知字段')
    if not isinstance(value.get('name'),str):raise ValueError(f'{label}名称须为1–{MAX_NAME}个可读字符')
    return {'name':_text(value['name'],label+'名称'),
        'weight':_integer(value.get('weight',1),1,MAX_WEIGHT,label+'权重'),
        'tactic':_tactic(value.get('tactic'),label)}


def _uniform(value):
    if not isinstance(value,dict):raise ValueError('统一属性设置格式无效')
    return {'enabled':_flag(value.get('enabled',True),'统一属性开关'),
        'attribute_value':_integer(value.get('attribute_value',DEFAULT_ATTRIBUTE_VALUE),1,20,'统一属性值')}


def normalize(value):
    if not isinstance(value,dict):raise ValueError('客队战术池格式无效')
    if value.get('profile',PROFILE)!=PROFILE:raise ValueError('客队战术池版本无效')
    entries=value.get('entries',[])
    if not isinstance(entries,list)or len(entries)>MAX_ENTRIES:raise ValueError(f'客队战术池最多允许 {MAX_ENTRIES} 套战术')
    normalized=[_entry(item,index)for index,item in enumerate(entries)]
    enabled=_flag(value.get('enabled',False),'客队战术池开关')
    if enabled and not normalized:raise ValueError('启用随机抽取前请先导入客队战术')
    return {'profile':PROFILE,'enabled':enabled,'entries':normalized,
        'uniform':_uniform(value['uniform']if'uniform'in value else defaults()['uniform'])}


def entry_from_team(team,name=None):
    if not isinstance(team,dict):raise ValueError('球队格式无效')
    tactic_name=team.get('tactic_name')if isinstance(team.get('tactic_name'),str)else''
    if name is None:
        label=''.join(c for c in(tactic_name or str(team.get('name')or'客队战术'))if ord(c)>=32).strip()[:MAX_NAME]
        name=label or'客队战术'
    entry={'name':name,'weight':1,'tactic':{'tactic_name':tactic_name,'mentality':team.get('mentality'),
        'instructions':team.get('instructions'),'native_extra_team_bits':team.get('native_extra_team_bits'),
        'phases':team.get('phases')}}
    if 'native_source_plan'in team:entry['tactic']['native_source_plan']=copy.deepcopy(team['native_source_plan'])
    return _entry(entry,0)


def probabilities(entries):
    if not isinstance(entries,list)or not entries:raise ValueError('客队战术池没有可抽取的战术')
    weights=[]
    for index,item in enumerate(entries):
        if not isinstance(item,dict):raise ValueError(f'第 {index+1} 套客队战术格式无效')
        weights.append(_integer(item.get('weight',1),1,MAX_WEIGHT,f'第 {index+1} 套客队战术权重'))
    total=sum(weights)
    return [{'weight':weight,'probability':weight/total}for weight in weights]


def draw_index(entries,seed,salt):
    if type(seed)is not int:raise ValueError('随机种子必须为整数')
    rows=probabilities(entries);target=random.Random(f'{salt}:{seed}').random();cumulative=0.0
    for index,row in enumerate(rows):
        cumulative+=row['probability']
        if target<cumulative:return index
    return len(rows)-1


def draws(pool,seeds,salt):
    entries=normalize(pool)['entries']
    if not isinstance(seeds,(list,tuple)):raise ValueError('随机种子列表格式无效')
    return {seed:draw_index(entries,seed,salt)for seed in seeds}


def apply(team,entry,uniform=None):
    if not isinstance(team,dict):raise ValueError('球队格式无效')
    tactic=_entry(entry,0)['tactic']
    team['tactic_name']=tactic['tactic_name'];team['mentality']=tactic['mentality']
    team['instructions']=copy.deepcopy(tactic['instructions'])
    team['native_extra_team_bits']=tactic['native_extra_team_bits']
    team['phases']=copy.deepcopy(tactic['phases'])
    team.pop('native_source_plan',None)
    if 'native_source_plan'in tactic:team['native_source_plan']=copy.deepcopy(tactic['native_source_plan'])
    options=_uniform(uniform)if uniform is not None else None
    if options and options['enabled']:
        value=options['attribute_value']
        players=team.get('players',[])
        for player in players:
            if not isinstance(player,dict)or not isinstance(player.get('attributes'),list)or len(player['attributes'])!=69:
                raise ValueError('客队球员属性不完整，无法统一为界面值')
            attributes=player['attributes']
            for index in range(POSITION_ATTRIBUTES,69):attributes[index]=value*5
            attributes[POSITION_ATTRIBUTE_INDEX['GK']]=1
        lineup=team.get('lineup')
        if isinstance(lineup,list):
            for phase in team.get('phases')or[]:
                if not isinstance(phase,list):continue
                for slot,cell in enumerate(phase):
                    if slot>=len(lineup)or not isinstance(cell,dict):continue
                    player_index=lineup[slot]
                    if type(player_index)is not int or not 0<=player_index<len(players):continue
                    familiar=POSITION_ATTRIBUTE_INDEX.get(cell.get('position'))
                    if familiar is not None:players[player_index]['attributes'][familiar]=POSITION_FAMILIARITY
    return team


def expand(scenario,index,side=1):
    if not isinstance(scenario,dict)or not isinstance(scenario.get('teams'),list)or len(scenario['teams'])!=2:
        raise ValueError('方案必须包含两支球队')
    side=_integer(side,0,1,'展开侧别')
    if 'away_tactic_pool'not in scenario:raise ValueError('方案缺少客队战术池')
    pool=normalize(scenario['away_tactic_pool']);entries=pool['entries']
    if not entries:raise ValueError('客队战术池没有可抽取的战术')
    index=_integer(index,0,len(entries)-1,'客队战术序号')
    result=copy.deepcopy(scenario);result.pop('away_tactic_pool',None)
    apply(result['teams'][side],entries[index],pool['uniform'])
    return result


def summary(pool,salt=None):
    value=normalize(pool);rows=probabilities(value['entries'])
    result={'profile':value['profile'],'enabled':value['enabled'],'uniform':copy.deepcopy(value['uniform']),
        'entries':[{'index':index,'name':entry['name'],'weight':row['weight'],'probability':row['probability']}
            for index,(entry,row)in enumerate(zip(value['entries'],rows))]}
    if salt is not None:result['salt']=str(salt)
    return result
