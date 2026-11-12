"""Desktop entry for source coaches + real players, generated afresh per match."""
import copy,hashlib,json,os,re,struct,subprocess,sys
import tempfile
from pathlib import Path
from desktop_generation_bindings import bind
from desktop_save_compact import read_table
from desktop_storage import bounded_output
from desktop_generation_protocol import PROFILE


def read(path):return json.loads(path.read_text(encoding='utf8'))


def ensure(lib,key):
    root=lib.folder(key);dataset=read(root/'dataset.json');folder=root/'generation';bounded_output(folder)
    cache=folder/'catalog.json'
    binding={'source_sha256':dataset['source_sha256'],'engine':read(root/'native_binding.json'),'profile':PROFILE}
    if cache.exists()and read(cache).get('binding')==binding:return read(cache)
    folder.mkdir(exist_ok=True)
    inputs=folder/'generation_inputs.json'
    if not inputs.exists()or read(inputs)['source_sha256']!=dataset['source_sha256']:
        source=read(root/'selected_source.json')['path']if(root/'selected_source.json').exists()else dataset['source']
        with(folder/'prepare.log').open('wb')as log:
            p=subprocess.run([os.environ.get('FM27_SAVE_PYTHON',sys.executable),str(Path(__file__).with_name('desktop_generation_prepare.py')),source,str(folder)],
                             env={**os.environ,'PYTHONUTF8':'1'},stdout=log,stderr=log,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
        if p.returncode:raise ValueError('电脑球队源数据准备失败，见 generation/prepare.log')
    d=read(inputs);table=read(folder/'source_team_table.json');context=read(folder/'duel_context.json')
    if any(v['source_sha256']!=dataset['source_sha256']for v in (d,table,context)):raise ValueError('Generation source mismatch')
    native=lib.native([],root,'generation_staff',{'FM27_STAFF_FRAGMENT_DIRECTORY':str(folder/'staff_fragments')})
    staff=[r for r in native if r.get('event')=='staff_body_read']
    expected=read(folder/'staff_fragments.json')['rows']
    if len(staff)!=len(expected):raise ValueError('Native coaching profile count mismatch')
    for row in expected:
        r=next((r for r in staff if r['selector']==row['person_selector']),None)
        if not r or not r['accepted']or r['error']or r['profile_hex']!=row['profile_hex']:raise ValueError('Native coaching profile mismatch')
        raw=bytes.fromhex(r['native_d4_to_f4_hex'])
        if list(struct.unpack_from('<5H',raw))!=row['ability_and_reputation_words']or raw[11:19].hex()!=row['codes_hex']:raise ValueError('Native coaching identity conversion mismatch')
    events=lib.native([],root,'generation_selection',{'FM27_AI_TACTICS_SECTION':str(folder/'tactics_man.bin')})
    ends=[r for r in events if r.get('event')=='ai_section_complete'];bounds=[r for r in events if r.get('event')=='ai_table_boundary']
    raw=(folder/'tactics_man.bin').read_bytes()
    if len(ends)!=1 or len(bounds)!=1 or ends[0]['offset']!=len(raw)or ends[0]['remaining']:raise ValueError('Current AI section not fully read')
    current=read_table(raw,bounds[0]['offset'])
    if current['end']!=bounds[0]['end']or current['count']!=bounds[0]['count']:raise ValueError('Current AI table boundary mismatch')
    current['source_sha256']=d['source_sha256']
    current['records']=[r for r in current['records']if r['team_id']in {t['team_id']for t in table['records']}]
    teams=bind(d,table,current)
    for t in teams:
        t['native_coach']=next(r for r in staff if r['selector']==t['coach']['person_selector'])
        t['context']=next(c for c in context['teams']if c['team_id']==t['team']['team_id'])
    value={'binding':binding,'teams':teams,'league':d['league'],'context_policy':PROFILE,
           'source_date':d['date'],'fixture_replay':False}
    lib.write(cache,value);return value


def opponents(lib,key,club):
    catalog=ensure(lib,key)
    if not any(t['club']['uid']==club and t['coach']['is_human_manager']for t in catalog['teams']):raise ValueError('请选择存档中执教的球队')
    return [{'key':'generated:'+str(t['team']['team_id']),'fixture_key':'generated:'+str(t['team']['team_id']),
        'club_uid':t['club']['uid'],'name':t['club']['short_name'],'side':1,'available':True,
        'source_kind':'original_ai_generation','member':'source_coach_and_current_selection',
        'source':'存档教练与真实阵容；原版引擎按本场生成战术；统一新对战环境',
        'date':catalog['source_date'],'context_policy':PROFILE,'direct_fixture':False,
        'match_roster_count':min(23,len(t['roster'])),'cache_roster_count':len(t['roster']),
        'excluded_substitute_uids':[r.get('source_uid')for r in t['excluded_stale_bench']]}
        for t in catalog['teams']if t['club']['uid']!=club and not t['coach']['is_human_manager']]


def team(lib,key,candidate):
    if not re.fullmatch(r'generated:\d{1,7}',candidate):raise ValueError('无效电脑球队标识')
    ident=int(candidate.split(':')[1]);catalog=ensure(lib,key)
    t=next((t for t in catalog['teams']if t['team']['team_id']==ident and not t['coach']['is_human_manager']),None)
    if t is None:raise ValueError('电脑球队不属于此存档联赛')
    result=copy.deepcopy(lib.app.DEFAULT['teams'][1]);roster=t['roster'][:23]
    for i,r in enumerate(roster):
        values,p=lib.player_values(r['player']);result['players'][i].update(name=r['player']['name'],source_uid=r['player']['unique_id'],attributes=values,native_profile=p)
    for p in result['players'][len(roster):]:p.pop('source_uid',None);p['name']='未入比赛名单'
    result.update(name=t['club']['short_name'],tactic_name='本场原生AI生成',lineup=list(range(11)),roster_size=len(roster),captains=[],takers={k:[]for k in lib.app.TAKER_KEYS})
    return result


def scenario_profile(lib,key,own,opponent,tested_side,teams):
    catalog=ensure(lib,key);payload=bytearray(b'FM27DUL1')
    for side,club in enumerate((own,opponent)if tested_side==0 else(opponent,own)):
        t=next(t for t in catalog['teams']if t['club']['uid']==club)
        coach=t['coach'];native=t['native_coach'];ctx=t['context'];actual=teams[side]
        pool={p['unique_id']for p in [r['player']for r in t['roster']]}
        # A manually chosen human XI may use any current player of the club.
        if coach['is_human_manager']:
            d=read(lib.folder(key)/'generation/generation_inputs.json');pool={p['unique_id']for p in d['players']if p['club_uid']==club}
        uids=[p.get('source_uid')for p in actual['players'][:actual['roster_size']]]
        if not 11<=len(uids)<=23 or any(u not in pool for u in uids)or len(set(uids))!=len(uids):raise ValueError('比赛名单不属于源球队')
        raw=bytes.fromhex(native['profile_hex']);extra=bytes.fromhex(native['native_d4_to_f4_hex']);codes=extra[11:19]
        personality=bytes(coach['personality'][k]for k in ('professionalism','loyalty','sportsmanship','temperament','pressure','ambition','adaptability'))+bytes([coach['age']])
        record=bytearray(struct.pack('<4I',ctx.get('team_native_uid',ctx['club_native_uid']),coach['unique_id'],ctx['reputation'],len(uids))+raw+bytes(codes[i]for i in(0,1,3,2,4,5,7,6))+personality)
        record+=struct.pack('<23I',*(uids+[0]*(23-len(uids))))
        influence=75 if coach['is_human_manager']else 75+struct.unpack_from('<H',extra,6)[0]//10+max(1,min(20,(raw[51]+2)//5))
        traits=native['generation_trait_pairs'];record+=extra[:10]+extra[26:33]+bytes([influence])+struct.pack('<H',len(traits))+bytes(v for pair in traits for v in pair)
        if len(record)>272:raise ValueError('Native trait capacity exceeded')
        record+=bytes(272-len(record));record+=struct.pack('<4I',int(coach['is_human_manager']),ctx['nation_native_uid'],*(c['native_uid']if c['current_club_member']else 0xffffffff for c in ctx['captains']))
        payload+=record
    return {'profile':PROFILE,'payload_hex':payload.hex()}


def preview(lib,key,own,opponent,scenario):
    """A zero-tick native preview against the selected real human team, seed 0."""
    scenario=copy.deepcopy(scenario);result=team(lib,key,opponent['key']);scenario['teams'][1]=result
    scenario['native_generation']=scenario_profile(lib,key,own,opponent['club_uid'],0,scenario['teams'])
    config=lib.app.encode_scenario(scenario,absolute=True);digest=hashlib.sha256(config).hexdigest()
    root=lib.folder(key);folder=root/'generation';bounded_output(folder)
    cache=folder/('preview_'+digest+'.json')
    if cache.exists():return read(cache)
    with tempfile.TemporaryDirectory(prefix='preview_',dir=folder)as temporary:
        cfg=Path(temporary)/'input.bin';cfg.write_bytes(config)
        name='generation_preview_'+digest
        try:
            rows=lib.native(['--fixture',str(lib.app.ROOT/'fm27_native/fixtures/match.pkm'),'--scenario-file',str(cfg),'--seed','0','--inspect-fixture'],root,name)
            if not any(r.get('event')=='native_fixture_inspected'and r.get('simulation_ticks_executed')==0 for r in rows):raise ValueError('预览未通过零tick原生准备核对')
            plans=[r for r in rows if r.get('event')=='source_generation_readback']
            if len(plans)!=2:raise ValueError('预览缺少完整的双方原生战术')
            plan=next(p for p in plans if p['side']==1)
            lib.apply_plan(result,plan)
            indices={p.get('source_uid'):i for i,p in enumerate(result['players'][:result['roster_size']])}
            result['lineup']=[indices[uid]for uid in plan['lineup_source_uids']]
            value={'team':result,'source':{**opponent,'native_preview':True,'preview_seed':0,
                'source':opponent['source']+'；当前主队为主场、预览种子0，正式比赛会按实际对手、主客场和种子重新生成'},
                'native_plan':plan,'zero_simulation_ticks':True,'config_sha256':digest}
            lib.write(cache,value);return value
        finally:
            # Successful preview evidence is compact above. Never accumulate
            # a separate startup trace and config for every board edit.
            for path in root.glob(name+'*.jsonl'):path.unlink()
            previews=sorted(folder.glob('preview_*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
            for old in previews[32:]:old.unlink()
