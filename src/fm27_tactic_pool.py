"""Away tactic pool: structural validation, weighted draws and per-match expansion."""
import copy
import json
import random

PROFILE='away-tactic-pool-v1'
MAX_ENTRIES=128
DEFAULT_ATTRIBUTE_VALUE=15
MAX_NAME=80
MAX_WEIGHT=1000
MAX_ROUNDS=1000
MAX_ROSTER=26
MAX_ROSTER_BYTES=1500000
MAX_ROTATION_MATCHES=10000
POSITION_ATTRIBUTES=15
POSITION_FAMILIARITY=20
POSITION_ATTRIBUTE_INDEX={'GK':0,'SW':1,'DL':2,'DC':3,'DCR':3,'DCL':3,'DR':4,'DM':5,'DMC':5,'DMR':5,'DML':5,
    'ML':6,'MC':7,'MCL':7,'MCR':7,'MR':8,'AML':9,'AMC':10,'AMCL':10,'AMCR':10,'AMR':11,
    'ST':12,'STR':12,'STL':12,'WBL':13,'WBR':14}


def defaults():
    return {'enabled':False,'entries':[],'uniform':{'enabled':True,'attribute_value':DEFAULT_ATTRIBUTE_VALUE},
        'rotation':{'enabled':False,'rounds':1},'real':{'enabled':False}}


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
    if set(value)-{'name','weight','tactic','roster'}:raise ValueError(label+'包含未知字段')
    if not isinstance(value.get('name'),str):raise ValueError(f'{label}名称须为1–{MAX_NAME}个可读字符')
    result={'name':_text(value['name'],label+'名称'),
        'weight':_integer(value.get('weight',1),1,MAX_WEIGHT,label+'权重'),
        'tactic':_tactic(value.get('tactic'),label)}
    if value.get('roster')is not None:result['roster']=_roster(value['roster'],label)
    return result


def _uniform(value):
    if not isinstance(value,dict):raise ValueError('统一属性设置格式无效')
    return {'enabled':_flag(value.get('enabled',True),'统一属性开关'),
        'attribute_value':_integer(value.get('attribute_value',DEFAULT_ATTRIBUTE_VALUE),1,20,'统一属性值')}


def _rotation(value):
    if not isinstance(value,dict):raise ValueError('轮战模式设置格式无效')
    if set(value)-{'enabled','rounds'}:raise ValueError('轮战模式设置包含未知字段')
    return {'enabled':_flag(value.get('enabled',False),'轮战模式开关'),
        'rounds':_integer(value.get('rounds',1),1,MAX_ROUNDS,'轮战每套轮数')}


def _real(value):
    if not isinstance(value,dict):raise ValueError('真实名单设置格式无效')
    if set(value)-{'enabled'}:raise ValueError('真实名单设置包含未知字段')
    return {'enabled':_flag(value.get('enabled',False),'真实名单开关')}


def _roster_name(value,limit,label):
    if not isinstance(value,str)or any(ord(c)<32 for c in value)or len(value)>limit:
        raise ValueError(f'{label}须为不超过 {limit} 个可读字符')
    return value.strip()


def _roster_player(value,label):
    if not isinstance(value,dict)or set(value)-{'name','source_uid','attributes','native_profile'}:
        raise ValueError(label+'格式无效')
    if not isinstance(value.get('name'),str)or not 1<=len(value['name'].strip())<=48 or any(ord(c)<32 for c in value['name']):
        raise ValueError(label+'球员名称须为1–48个可读字符')
    attributes=value.get('attributes')
    if not isinstance(attributes,list)or len(attributes)!=69:raise ValueError(label+'球员属性不完整')
    normalized=[_integer(item,0 if index<POSITION_ATTRIBUTES else 1,20 if index<POSITION_ATTRIBUTES else 100,label+'属性')
        for index,item in enumerate(attributes)]
    profile=value.get('native_profile',{})
    if not isinstance(profile,dict):raise ValueError(label+'球员扩展输入格式无效')
    return {'name':value['name'].strip(),'source_uid':_integer(value.get('source_uid'),0,0xffffffff,label+'源球员UID'),
        'attributes':normalized,'native_profile':copy.deepcopy(profile)}


def _roster(value,label):
    if not isinstance(value,dict)or set(value)-{'club_uid','club','coach','source','roster_size','lineup','players'}:
        raise ValueError(label+'存档名单格式无效')
    players=value.get('players')
    if not isinstance(players,list)or not 11<=len(players)<=MAX_ROSTER:raise ValueError(f'{label}存档名单须包含 11–{MAX_ROSTER} 名球员')
    normalized=[_roster_player(item,label+'存档名单第 '+str(index+1)+' 名球员')for index,item in enumerate(players)]
    size=_integer(value.get('roster_size',len(normalized)),11,len(normalized),label+'存档名单人数')
    if size!=len(normalized):raise ValueError(label+'存档名单人数与球员数量不一致')
    if len({item['source_uid']for item in normalized})!=size:raise ValueError(label+'存档名单包含重复球员')
    lineup=value.get('lineup')
    if not isinstance(lineup,list)or len(lineup)!=11 or len(set(lineup))!=11:raise ValueError(label+'存档名单首发须为11名不同球员')
    source=value.get('source')
    if source not in ('real_ai','coach_preset'):raise ValueError(label+'存档名单来源无效')
    return {'club_uid':_integer(value.get('club_uid'),0,0xffffffff,label+'存档球队编号'),
        'club':_roster_name(value.get('club'),40,label+'存档球队名称'),
        'coach':_roster_name(value.get('coach'),60,label+'存档主教练名称'),
        'source':source,'roster_size':size,
        'lineup':[_integer(item,0,size-1,label+'存档名单首发')for item in lineup],
        'players':normalized}


def normalize(value):
    if not isinstance(value,dict):raise ValueError('客队战术池格式无效')
    if value.get('profile',PROFILE)!=PROFILE:raise ValueError('客队战术池版本无效')
    entries=value.get('entries',[])
    if not isinstance(entries,list)or len(entries)>MAX_ENTRIES:raise ValueError(f'客队战术池最多允许 {MAX_ENTRIES} 套战术')
    normalized=[_entry(item,index)for index,item in enumerate(entries)]
    enabled=_flag(value.get('enabled',False),'客队战术池开关')
    if enabled and not normalized:raise ValueError('启用客队战术池前请先导入客队战术')
    rotation=_rotation(value['rotation']if'rotation'in value else defaults()['rotation'])
    real=_real(value['real']if'real'in value else defaults()['real'])
    if real['enabled']:
        missing=[item['name']for item in normalized if 'roster'not in item]
        if missing:
            detail='、'.join(missing[:3])+('等'if len(missing)>3 else'')
            raise ValueError('真实名单模式需要每套客队战术都带存档球员名单，缺少：'+detail)
    rosters=[item['roster']for item in normalized if 'roster'in item]
    if rosters:
        size=len(json.dumps(rosters,ensure_ascii=False,separators=(',',':')).encode('utf8'))
        if size>MAX_ROSTER_BYTES:
            raise ValueError(f'带存档名单的候选战术合计约 {size/1000000:.2f} MB，超过 {MAX_ROSTER_BYTES/1000000:.2f} MB 上限；请减少带名单的候选或清理条目')
    if rotation['enabled'] and normalized and len(normalized)*rotation['rounds']>MAX_ROTATION_MATCHES:
        raise ValueError(f'轮战每方案最多 {MAX_ROTATION_MATCHES} 场，当前 {len(normalized)} 套 × {rotation["rounds"]} 轮 = {len(normalized)*rotation["rounds"]} 场')
    return {'profile':PROFILE,'enabled':enabled,'entries':normalized,
        'uniform':_uniform(value['uniform']if'uniform'in value else defaults()['uniform']),
        'rotation':rotation,'real':real}


def entry_from_team(team,name=None,roster=None):
    if not isinstance(team,dict):raise ValueError('球队格式无效')
    tactic_name=team.get('tactic_name')if isinstance(team.get('tactic_name'),str)else''
    if name is None:
        label=''.join(c for c in(tactic_name or str(team.get('name')or'客队战术'))if ord(c)>=32).strip()[:MAX_NAME]
        name=label or'客队战术'
    entry={'name':name,'weight':1,'tactic':{'tactic_name':tactic_name,'mentality':team.get('mentality'),
        'instructions':team.get('instructions'),'native_extra_team_bits':team.get('native_extra_team_bits'),
        'phases':team.get('phases')}}
    if 'native_source_plan'in team:entry['tactic']['native_source_plan']=copy.deepcopy(team['native_source_plan'])
    if roster is not None:entry['roster']=copy.deepcopy(roster)
    return _entry(entry,0)


def roster_from_team(team,club_uid,club,coach,source):
    if not isinstance(team,dict):raise ValueError('球队格式无效')
    players=team.get('players')
    if not isinstance(players,list)or len(players)<11:raise ValueError('球队没有可保存的一线队名单')
    size=min(team.get('roster_size')or len(players),len(players),MAX_ROSTER)
    if size<11:raise ValueError('球队比赛名单不足11人，无法保存真实名单')
    saved=[]
    for index,player in enumerate(players[:size]):
        if not isinstance(player,dict)or player.get('source_uid')is None or not isinstance(player.get('attributes'),list):
            raise ValueError(f'球队名单第 {index+1} 名球员缺少存档来源或属性')
        saved.append({'name':player.get('name')or f'球员 {index+1}','source_uid':player['source_uid'],
            'attributes':copy.deepcopy(player['attributes']),'native_profile':copy.deepcopy(player.get('native_profile')or {})})
    lineup=team.get('lineup')
    if not isinstance(lineup,list)or len(lineup)!=11 or any(type(index)is not int or not 0<=index<size for index in lineup):
        raise ValueError('球队首发名单不完整，无法保存真实名单')
    return _roster({'club_uid':club_uid,'club':club,'coach':coach,'source':source,'roster_size':size,
        'lineup':copy.deepcopy(lineup),'players':saved},'球队')


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


def rotation_matches(pool):
    value=normalize(pool)
    return len(value['entries'])*value['rotation']['rounds']


def rotation_message(pool,count):
    value=normalize(pool)
    entries=len(value['entries']);rounds=value['rotation']['rounds']
    return f'轮战模式每方案需要 {entries} 套 × {rounds} 轮 = {entries*rounds} 场，当前种子数为 {count}'


def draws(pool,seeds,salt):
    value=normalize(pool);entries=value['entries']
    if not isinstance(seeds,(list,tuple)):raise ValueError('随机种子列表格式无效')
    if value['rotation']['enabled']:
        if len(seeds)!=len(entries)*value['rotation']['rounds']:raise ValueError(rotation_message(value,len(seeds)))
        return {seed:index%len(entries)for index,seed in enumerate(seeds)}
    return {seed:draw_index(entries,seed,salt)for seed in seeds}


def completed_draw_counts(runs, entry_count):
    counts = {str(index): 0 for index in range(entry_count)}
    by_seed = {}
    for run in runs:
        entry = run.get('tactic_pool_entry')
        if entry is None:
            continue
        index = _integer(entry['index'], 0, entry_count - 1, '客队战术序号')
        seed = run['seed']
        if seed in by_seed and by_seed[seed] != index:
            raise ValueError('同种子对照的客队战术不一致')
        by_seed[seed] = index
    for index in by_seed.values():
        counts[str(index)] += 1
    return counts


def apply(team,entry,uniform=None,real=False):
    return _apply_team(team,_entry(entry,0),uniform,real)


def _apply_team(team,normalized,uniform=None,real=False):
    if not isinstance(team,dict):raise ValueError('球队格式无效')
    tactic=normalized['tactic']
    team['tactic_name']=tactic['tactic_name'];team['mentality']=tactic['mentality']
    team['instructions']=copy.deepcopy(tactic['instructions'])
    team['native_extra_team_bits']=tactic['native_extra_team_bits']
    team['phases']=copy.deepcopy(tactic['phases'])
    team.pop('native_source_plan',None)
    if 'native_source_plan'in tactic:team['native_source_plan']=copy.deepcopy(tactic['native_source_plan'])
    if real:
        roster=normalized.get('roster')
        if roster is None:raise ValueError('真实名单模式缺少存档球员名单')
        _apply_roster(team,roster)
        return team
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
        if not isinstance(lineup,list)or len(lineup)<11:
            raise ValueError('客队首发名单不完整，无法统一战术位置熟练度')
        for phase in team.get('phases')or []:
            if not isinstance(phase,list)or len(phase)!=11:
                raise ValueError('客队战术阶段不完整，无法统一战术位置熟练度')
            for slot,cell in enumerate(phase):
                if not isinstance(cell,dict):raise ValueError('客队战术位置格式无效')
                player_index=lineup[slot]
                if type(player_index)is not int or not 0<=player_index<len(players):
                    raise ValueError('客队首发名单包含无效球员序号')
                familiar=POSITION_ATTRIBUTE_INDEX.get(cell.get('position'))
                if familiar is None:raise ValueError('战术包含未知位置，无法统一熟练度：'+str(cell.get('position')))
                players[player_index]['attributes'][familiar]=POSITION_FAMILIARITY
        verify(team,value)
    return team


def _apply_roster(team,roster):
    players=team.get('players')
    if not isinstance(players,list)or len(players)<11:raise ValueError('客队名单容量不足，无法应用存档名单')
    count=roster['roster_size']
    if count>len(players):raise ValueError('存档名单人数超出客队容量')
    old_uids={index:player.get('source_uid')for index,player in enumerate(players)}
    old_captains=list(team.get('captains')or [])
    old_takers={key:list(values)for key,values in(team.get('takers')or {}).items()}
    priorities=team.get('setpieces',{}).get('role_priorities')
    priorities={key:list(values)for key,values in priorities.items()}if isinstance(priorities,dict)else None
    for index,player in enumerate(players):
        player.pop('source_uid',None)
        if index<count:
            saved=roster['players'][index]
            player.update(name=saved['name'],source_uid=saved['source_uid'],
                attributes=copy.deepcopy(saved['attributes']),native_profile=copy.deepcopy(saved['native_profile']))
        else:
            player['name']='未入比赛名单'
    team['roster_size']=count
    team['lineup']=list(roster['lineup'])
    team.pop('squad',None)
    remap={player.get('source_uid'):index for index,player in enumerate(players[:count])if player.get('source_uid')is not None}
    def remapped(values):
        result=[]
        for index in values:
            if index in old_uids and old_uids[index]in remap:
                target=remap[old_uids[index]]
                if target not in result:result.append(target)
        return result
    team['captains']=remapped(old_captains)
    team['takers']={key:remapped(values)for key,values in old_takers.items()}
    if priorities is not None:team['setpieces']['role_priorities']={key:remapped(values)for key,values in priorities.items()}
    verify_roster(team,roster)
    return team


def verify_roster(team,roster):
    players=team.get('players')or []
    if team.get('roster_size')!=roster['roster_size']or roster['roster_size']>len(players):
        raise ValueError('存档名单人数未应用到客队')
    if team.get('lineup')!=list(roster['lineup']):raise ValueError('存档名单首发未应用到客队')
    for index,saved in enumerate(roster['players']):
        player=players[index]
        if player.get('source_uid')!=saved['source_uid']:raise ValueError('存档球员来源未应用到客队')
        if player.get('attributes')!=saved['attributes']:raise ValueError('存档球员属性未应用到客队')
    return True


def verify(team,value):
    """Every starter must be fully familiar with the tactic position and carry the uniform panel value."""
    players=team.get('players')or [];lineup=team.get('lineup')or []
    if len(lineup)<11:raise ValueError('客队首发名单不完整')
    for phase in team.get('phases')or []:
        for slot,cell in enumerate(phase):
            index=lineup[slot];familiar=POSITION_ATTRIBUTE_INDEX.get(cell.get('position'))
            if familiar is None:raise ValueError('战术包含未知位置，无法核对熟练度：'+str(cell.get('position')))
            attributes=players[index]['attributes']
            if attributes[familiar]!=POSITION_FAMILIARITY:
                raise ValueError('战术位置熟练度未达到满值')
            if any(attributes[position]!=value*5 for position in range(POSITION_ATTRIBUTES,69)):
                raise ValueError('统一球员属性未达到设定面板值')
    return True


def expand(scenario,index,side=1,pool_value=None):
    if not isinstance(scenario,dict)or not isinstance(scenario.get('teams'),list)or len(scenario['teams'])!=2:
        raise ValueError('方案必须包含两支球队')
    side=_integer(side,0,1,'展开侧别')
    if 'away_tactic_pool'not in scenario:raise ValueError('方案缺少客队战术池')
    pool=normalize(scenario['away_tactic_pool'])if pool_value is None else pool_value
    entries=pool['entries']
    if not entries:raise ValueError('客队战术池没有可抽取的战术')
    index=_integer(index,0,len(entries)-1,'客队战术序号')
    result=copy.deepcopy({key:value for key,value in scenario.items()if key!='away_tactic_pool'})
    _apply_team(result['teams'][side],entries[index],pool['uniform'],real=pool['real']['enabled'])
    return result


def summary(pool,salt=None):
    value=normalize(pool);rows=probabilities(value['entries'])
    result={'profile':value['profile'],'enabled':value['enabled'],
        'mode':'rotation'if value['rotation']['enabled']else'random','rounds':value['rotation']['rounds'],
        'players':'real'if value['real']['enabled']else'uniform','uniform':copy.deepcopy(value['uniform']),
        'entries':[{'index':index,'name':entry['name'],'weight':row['weight'],
            'probability':None if value['rotation']['enabled'] else row['probability'],
            'roster':'roster'in entry}
            for index,(entry,row)in enumerate(zip(value['entries'],rows))]}
    if salt is not None:result['salt']=str(salt)
    return result
