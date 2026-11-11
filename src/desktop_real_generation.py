"""Real AI tactics: save coach fragments feed the original engine's AI preparation."""
import copy
import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import desktop_generation_protocol

PROFILE='source-direct-duel-v1'
FRAGMENTS='staff_fragments'
MANAGER_JOB=16
MAX_ROSTER=23
VARIANT_LABELS={'A':'主场','H':'客场'}
PREP_VERSION=3
_VERIFIED={}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def folder(lib,key):
    return lib.folder(key)/'real_generation'


def _python():
    return os.environ.get('FM27_SAVE_PYTHON') or sys.executable


def _source(lib,key):
    root=lib.folder(key)
    selected=root/'selected_source.json'
    return read(selected)['path'] if selected.exists() else read(root/'dataset.json')['source']


def _run(script,args,log_path,timeout):
    command=[_python(),str(Path(__file__).with_name(script)),*[str(value)for value in args]]
    with log_path.open('wb')as stream:
        return subprocess.run(command,env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'},
            stdout=stream,stderr=stream,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


_FIXTURE_SHA={}


def _fixture_sha(lib):
    path=lib.app.NATIVE/'fixtures/match.pkm'
    try:stat=path.stat()
    except OSError:return None
    stamp=(str(path),stat.st_size,stat.st_mtime_ns)
    if _FIXTURE_SHA.get('stamp')!=stamp:
        _FIXTURE_SHA.clear()
        _FIXTURE_SHA.update(stamp=stamp,sha256=lib.app.desktop_engine.sha(path))
    return _FIXTURE_SHA.get('sha256')


def binding(lib,key):
    """Identity of the engine, fixture and generation protocol behind derived plans."""
    root=lib.folder(key)
    lib.check_binding(root)
    return {'engine':read(root/'native_binding.json'),'fixture_sha256':_fixture_sha(lib),
        'protocol':desktop_generation_protocol.PROFILE,'prep_version':PREP_VERSION}


def plan_cache(lib,key,config_sha256,seed,binding):
    binding_key=hashlib.sha256(json.dumps(binding,sort_keys=True).encode()).hexdigest()[:12]
    return folder(lib,key)/f'plan_{binding_key}_{config_sha256}_{seed}.json'


def ensure(lib,key):
    """Prepared league coaches and players, cached by save digest."""
    root=lib.folder(key);data=lib.index_data(root);out=folder(lib,key);out.mkdir(parents=True,exist_ok=True)
    identity=binding(lib,key)
    source=_source(lib,key)
    stat=Path(source).stat();stamp=(str(source),stat.st_size,stat.st_mtime_ns,data['source_sha256'])
    if stamp not in _VERIFIED:
        with Path(source).open('rb')as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=data['source_sha256']:
                raise ValueError('来源存档已更新，请重新读取存档后再生成真实AI战术')
        if len(_VERIFIED)>8:_VERIFIED.clear()
        _VERIFIED[stamp]=True
    marker=out/'prepare.json'
    prepared_stamp={}
    if marker.exists():
        try:prepared_stamp=read(marker)
        except (OSError,ValueError):prepared_stamp={}
    stale=(prepared_stamp.get('version')!=PREP_VERSION or prepared_stamp.get('source_sha256')!=data['source_sha256'] or
        prepared_stamp.get('binding')!=identity)
    inputs=out/'generation_inputs.json'
    usable=False
    if inputs.exists()and not stale:
        try:usable=read(inputs).get('source_sha256')==data['source_sha256']
        except (OSError,ValueError):usable=False
    if not usable:
        result=_run('desktop_generation_inputs.py',(source,out),out/'inputs.log',300)
        if result.returncode:raise ValueError('真实AI战术源数据准备失败，见 real_generation/inputs.log')
    fragments=out/'staff_fragments.json'
    usable=False
    if fragments.exists()and not stale:
        try:usable=read(fragments).get('source_sha256')==data['source_sha256']
        except (OSError,ValueError):usable=False
    if not usable:
        result=_run('desktop_real_generation_prepare.py',(source,out),out/'prepare.log',300)
        if result.returncode:raise ValueError('真实AI战术教练档案准备失败，见 real_generation/prepare.log')
        lib.write(marker,{'version':PREP_VERSION,'source_sha256':data['source_sha256'],'binding':identity})
    expected=read(fragments)
    if not expected.get('human_ready'):
        raise ValueError('你的主教练档案无法从存档定位：'+str(expected.get('human_error')or'未知原因'))
    stamp={'source_sha256':data['source_sha256'],'fragments_sha256':hashlib.sha256(fragments.read_bytes()).hexdigest(),
        'binding':identity}
    cache=out/'staff_native.json'
    if cache.exists():
        try:
            value=read(cache)
            if value.get('binding')==stamp:return {'inputs':read(inputs),'staff':value['staff'],'staff_native_binding':stamp,'binding':identity}
        except (OSError,ValueError):pass
    rows=lib.native([],root,'real_generation_staff',{'FM27_STAFF_FRAGMENT_DIRECTORY':str(out/FRAGMENTS)})
    native={str(row['selector']):row for row in rows if row.get('event')=='staff_body_read'}
    staff={}
    for row in expected['rows']:
        selector=str(row['person_selector']);entry=native.get(selector)
        if not entry or not entry.get('accepted') or entry.get('error'):
            raise ValueError('教练档案未通过原版读回：'+selector)
        if entry['profile_hex']!=row['profile_hex'] or entry['native_d4_to_f4_hex'][22:38]!=row['codes_hex']:
            raise ValueError('教练档案与原版读回不一致：'+selector)
        staff[selector]={'profile_hex':entry['profile_hex'],'native_d4_to_f4_hex':entry['native_d4_to_f4_hex'],
            'generation_trait_pairs':entry['generation_trait_pairs'],'human':bool(row.get('human')),'uid':row.get('uid')}
    lib.write(cache,{'binding':stamp,'staff':staff})
    return {'inputs':read(inputs),'staff':staff,'staff_native_binding':stamp,'binding':identity}


def manager(inputs,club_uid,human):
    rows=[s for s in inputs.get('staff')or [] if s.get('club_uid')==club_uid
          and (s.get('job')or {}).get('raw')==MANAGER_JOB and s.get('has_contract')
          and bool(s.get('is_human_manager'))==bool(human)]
    rows.sort(key=lambda s:(0 if s.get('team_slot')==0 else 1,s.get('uid')or 0))
    return rows[0] if rows else None


def roster(inputs,club_uid):
    players=[p for p in inputs.get('players')or [] if p.get('club_uid')==club_uid and p.get('unique_id') is not None]
    if len(players)<11:raise ValueError('球队不足11名已解析球员')
    players.sort(key=lambda p:(-(p.get('ability')or {}).get('current')or 0,p.get('unique_id')or 0))
    chosen=players[:MAX_ROSTER]
    if not any(is_goalkeeper(p) for p in chosen):
        keepers=[p for p in players if is_goalkeeper(p)]
        if not keepers:raise ValueError('球队没有可确认的门将')
        chosen=chosen[:-1]+[keepers[0]]
    return chosen


def is_goalkeeper(player):
    return (player.get('positions')or {}).get('gk',0)>=14


def _team(lib,side,name,players,tactic_name):
    result=copy.deepcopy(lib.app.DEFAULT['teams'][side])
    for index,player in enumerate(players):
        values,profile=lib.player_values(player)
        result['players'][index].update(name=player.get('name'),source_uid=player.get('unique_id'),
            attributes=values,native_profile=profile)
    for slot in range(len(players),len(result['players'])):
        result['players'][slot].pop('source_uid',None)
        result['players'][slot]['name']='未入比赛名单'
    result.update(name=name,tactic_name=tactic_name,lineup=list(range(11)),roster_size=len(players),
        captains=[],takers={key:[]for key in lib.app.TAKER_KEYS})
    return result


def _side_record(inputs,club,coach,native,human,players):
    nation=(inputs.get('nations')or {}).get(str(club.get('nation_id')))
    if type(nation)is not int:raise ValueError('球队国家原生编号缺失')
    profile=bytes.fromhex(native['profile_hex'])
    extra=bytes.fromhex(native['native_d4_to_f4_hex'])
    codes=extra[11:19]
    ordered=bytes(codes[index]for index in (0,1,3,2,4,5,7,6))
    if len(profile)!=52 or any(value>100 for value in profile) or any(value>64 for value in ordered):
        raise ValueError('该队主教练档案的参数超出原版生成范围，暂不支持该队的真实战术生成')
    personality=coach['personality']
    traits=native['generation_trait_pairs']
    influence=75 if human else 75+struct.unpack_from('<H',extra,6)[0]//10+max(1,min(20,(profile[51]+2)//5))
    uids=[player['unique_id']for player in players]
    record=bytearray(struct.pack('<4I',int(club['unique_id']),int(coach['unique_id']),
        int(club.get('reputation')or 0),len(uids)))
    record+=profile
    record+=ordered
    record+=bytes(int(personality[key])for key in ('professionalism','loyalty','sportsmanship','temperament','pressure','ambition','adaptability'))
    record+=bytes([int(coach['age'])])
    record+=struct.pack('<23I',*(uids+[0]*(MAX_ROSTER-len(uids))))
    record+=extra[:10]+extra[26:33]+bytes([influence])+struct.pack('<H',len(traits))
    record+=bytes(value for pair in traits for value in pair)
    if len(record)>272:raise ValueError('教练参数与名单超出原生生成容量')
    record+=bytes(272-len(record))
    record+=struct.pack('<4I',1 if human else 0,nation,0xffffffff,0xffffffff)
    return record


def _selection(lib,key,own_club,opponent_club,venue,prepared=None):
    prepared=prepared or ensure(lib,key)
    inputs=prepared['inputs'];staff=prepared['staff']
    own_club=int(own_club);opponent_club=int(opponent_club)
    if venue not in ('H','A'):raise ValueError('真实AI战术只支持主/客场两种上下文')
    clubs={club['uid']:club for club in inputs.get('clubs')or []}
    if own_club not in clubs or opponent_club not in clubs:
        raise ValueError('所选球队不在你当前执教的联赛，无法读取当前教练与名单')
    own_coach=manager(inputs,own_club,True)
    opponent_coach=manager(inputs,opponent_club,False)
    if own_coach is None:raise ValueError('存档中缺少玩家主教练')
    if opponent_coach is None:raise ValueError('该队缺少可核实的现任主教练')
    own_native=staff.get(str(own_coach.get('person_selector')))
    opponent_native=staff.get(str(opponent_coach.get('person_selector')))
    if own_native is None or opponent_native is None:raise ValueError('双方主教练档案尚未通过原版读回')
    own_players=roster(inputs,own_club)
    opponent_players=roster(inputs,opponent_club)
    return {'inputs':inputs,'clubs':clubs,'own_coach':own_coach,'opponent_coach':opponent_coach,
        'own_native':own_native,'opponent_native':opponent_native,
        'own_players':own_players,'opponent_players':opponent_players}


def preview(lib,key,own_club,opponent_club,venue='H',seed=0,prepared=None):
    prepared=prepared or ensure(lib,key)
    identity=prepared.get('binding')
    if identity is None:
        prepared=ensure(lib,key);identity=prepared['binding']
    context=_selection(lib,key,own_club,opponent_club,venue,prepared)
    inputs=context['inputs'];clubs=context['clubs']
    own=context['own_coach'];opponent=context['opponent_coach']
    home = venue=='H'
    first,second = (own,opponent) if home else (opponent,own)
    first_players,second_players = ((context['own_players'],context['opponent_players']) if home
        else (context['opponent_players'],context['own_players']))
    first_native,second_native = ((context['own_native'],context['opponent_native']) if home
        else (context['opponent_native'],context['own_native']))
    first_club = clubs[int(own_club)] if home else clubs[int(opponent_club)]
    second_club = clubs[int(opponent_club)] if home else clubs[int(own_club)]
    ai_side = 1 if home else 0
    payload=bytearray(b'FM27DUL1')
    payload+=_side_record(inputs,first_club,first,first_native,home,first_players)
    payload+=_side_record(inputs,second_club,second,second_native,not home,second_players)
    first_team=_team(lib,0,first_club.get('short_name')or first_club.get('name')or'主队',first_players,'真实AI战术预览 · 主队')
    second_team=_team(lib,1,second_club.get('short_name')or second_club.get('name')or'客队',second_players,'本场原生AI生成')
    scenario=copy.deepcopy(lib.app.DEFAULT);scenario['teams']=[first_team,second_team]
    scenario['native_generation']={'profile':desktop_generation_protocol.PROFILE,'payload_hex':payload.hex()}
    config=lib.app.encode_scenario(scenario,absolute=True)
    digest=hashlib.sha256(config).hexdigest()
    root=folder(lib,key);cfg=root/f'preview_{digest[:16]}.bin';cfg.write_bytes(config)
    name='real_generation_preview_'+digest[:16]
    cache=plan_cache(lib,key,digest[:16],seed,identity)
    if cache.exists():
        try:plan=read(cache)
        except (OSError,ValueError):plan=None
    else:plan=None
    if plan is None:
        rows=lib.native(['--fixture',str(lib.app.ROOT/'fm27_native/fixtures/match.pkm'),
            '--scenario-file',str(cfg),'--seed',str(seed),'--inspect-fixture'],lib.folder(key),name)
        plans=[row for row in rows if row.get('event')=='source_generation_readback']
        if len(plans)!=2:raise ValueError('原版引擎未返回完整的双方战术回读，见 '+name+'.jsonl')
        plan=next(row for row in plans if row.get('side')==ai_side)
        lib.write(cache,plan)
    opponent_players=context['opponent_players']
    opponent_club_row=clubs[int(opponent_club)]
    opponent_team=_team(lib,1,opponent_club_row.get('short_name')or opponent_club_row.get('name')or'对手',opponent_players,'本场原生AI生成')
    lib.apply_plan(opponent_team,plan)
    indices={player.get('source_uid'):index for index,player in enumerate(opponent_team['players'][:opponent_team['roster_size']])}
    try:opponent_team['lineup']=[indices[uid]for uid in plan['lineup_source_uids']]
    except KeyError:raise ValueError('原版战术首发与名单不一致')
    return {'team':opponent_team,'native_plan':plan,'venue':venue,'seed':seed,
        'payload_sha256':hashlib.sha256(payload).hexdigest(),'config_sha256':digest,
        'own_club':int(own_club),'opponent_club':int(opponent_club),
        'own_coach':own.get('name'),'opponent_coach':opponent.get('name'),
        'own_roster':[player['unique_id']for player in context['own_players']],
        'opponent_roster':[player['unique_id']for player in opponent_players]}


def variant_label(venue,club=None):
    word=VARIANT_LABELS.get(venue)or venue
    return f'{club}{word}战术' if club else f'{word}战术'


def variant_name(lib,club,coach,venue):
    import desktop_save_export
    parts=[desktop_save_export.safe_component(club,'俱乐部',24),
           desktop_save_export.safe_component(coach,'主教练',24),f'{VARIANT_LABELS[venue]}战术']
    return '-'.join(part for part in parts if part)


def team_from_plan(lib,key,plan,roster,club_uid,tactic_name,prepared=None):
    """Rebuild the generated opponent team from a stored plan and roster."""
    prepared=prepared or ensure(lib,key)
    inputs=prepared['inputs']
    players={player['unique_id']:player for player in inputs.get('players')or []}
    try:chosen=[players[uid]for uid in roster]
    except KeyError:raise ValueError('真实AI战术名单与当前存档不匹配，请重新生成')
    club=next((item for item in inputs.get('clubs')or [] if item['uid']==int(club_uid)),None)
    if club is None:raise ValueError('真实AI战术球队不属于当前执教联赛')
    team=_team(lib,1,club.get('short_name')or club.get('name')or'对手',chosen,tactic_name)
    lib.apply_plan(team,plan)
    indices={player.get('source_uid'):index for index,player in enumerate(team['players'][:team['roster_size']])}
    try:team['lineup']=[indices[uid]for uid in plan['lineup_source_uids']]
    except KeyError:raise ValueError('真实AI战术首发与名单不一致')
    return team


def record(lib,key,result,prepared=None,created=None):
    """One stored variant: engine plan, its roster and generation receipt."""
    import datetime
    opponent=result['team'];venue=result['venue'];club=opponent.get('name')
    return {'index':1 if venue=='A' else 2,'venue':venue,
        'label':variant_label(venue,club),
        'name':variant_name(lib,club,result.get('opponent_coach')or'',venue),
        'tactic_name':opponent.get('tactic_name'),'plan':result['native_plan'],
        'roster':result['opponent_roster'],'club_uid':result['opponent_club'],
        'club':opponent.get('name'),'coach':result.get('opponent_coach')or'',
        'plan_sha256':hashlib.sha256(json.dumps(result['native_plan'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        'payload_sha256':result['payload_sha256'],'config_sha256':result['config_sha256'],
        'generated_at':created or datetime.datetime.now().astimezone().isoformat(timespec='seconds')}
