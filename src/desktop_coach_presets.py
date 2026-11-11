"""Coach preference -> original installation preset -> static save attributes."""
import collections,copy,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
import desktop_static_plans
from desktop_coach_prepare import FRAGMENT_DIRECTORY, LEAGUE_PROFILE, PROFILE as STAFF_PROFILE
from desktop_storage import bounded_output

PROFILE='coach-preference-original-preset-v8'
STYLE_NAMES={0:'控制球权',1:'高位逼抢',2:'密集短传',3:'纵向短传渗透',4:'边路进攻',
             5:'长传冲吊',6:'流畅反击',7:'直接反击',8:'链式防守',9:'摆大巴'}

def read(path):return json.loads(path.read_text(encoding='utf8'))
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def binding(lib,folder):
    return {'profile':PROFILE,'source_sha256':lib.index_data(folder)['source_sha256'],
            'engine':read(folder/'native_binding.json')}

def assets(lib,folder):
    stamp={'profile':PROFILE,'engine':read(folder/'native_binding.json')}
    cache=lib.root/('coach_preset_assets_'+digest(stamp)[:20]+'.json')
    if cache.exists():
        value=read(cache)
        if value.get('binding')==stamp:return value
    rows=lib.native([],folder,'coach_preset_assets',{'FM27_COACH_PRESET_EXPORT':'1'})
    endings=[r for r in rows if r.get('event')=='coach_preset_export_complete']
    templates=[r for r in rows if r.get('event')=='installed_tactic_preset']
    styles=[r for r in rows if r.get('event')=='coach_preset_style']
    formations=[r for r in rows if r.get('event')=='coach_preset_formation']
    if len(endings)!=1 or not templates or not formations or any(endings[0][k]!=len(v)for k,v in [('templates',templates),('styles',styles),('formations',formations)]):
        raise ValueError('原装预设目录未通过完整读取核对')
    for t in templates:
        if len(t['phases'])!=2 or any(len(p)!=11 for p in t['phases']):raise ValueError('预设双阶段不完整')
        t['name']=bytes.fromhex(t['name_utf8_hex']).decode('utf8')
    value={'binding':stamp,'templates':templates,'styles':styles,'formations':formations}
    lib.write(cache,value);return value

def distance(a,b):
    return sum((collections.Counter(a)-collections.Counter(b)).values())

def formation_name(lib,positions):
    if not positions:return '未设置次偏好'
    names={v['mask']:v['id']for v in lib.app.POSITIONS.values()}
    values=[names.get(p,'?')for p in positions]
    d=sum(p in {'DR','DCR','DCL','DC','DL'}for p in values)
    dm=sum(p.startswith('DM')for p in values);mc=sum(p.startswith('MC')for p in values)
    am=sum(p.startswith('AM')for p in values);st=sum(p.startswith('ST')for p in values)
    if d==4 and dm==2 and am==3 and st==1:return '4-2-3-1（双后腰）'
    if d==4 and dm==1 and mc==2 and am==2 and st==1:return '4-3-3 后腰拉边'
    bands=[d,sum(p.startswith('WB')for p in values),dm,
           sum(p in {'ML','MR'}or p.startswith('MC')for p in values),am,st]
    return '-'.join(str(n)for n in bands if n)

def describe(lib,t):
    match=t['formation_match']
    suffix='双阶段精确匹配'if match['primary_exact']and match['secondary_exact']else'按同风格最接近阵型匹配'
    return f"{STYLE_NAMES.get(t['style_id'],t['preset_name'])} · 主偏好 {formation_name(lib,match['primary_positions'])} / 次偏好 {formation_name(lib,match['secondary_positions'])} · {suffix}"

def _style_candidates(catalog,style,primary):
    styles={r['id']:r['style_code']for r in catalog['styles']}
    formations={r['code']:r['positions']for r in catalog['formations']}
    if style not in styles:raise ValueError('该教练未存储可用的预设风格')
    if primary not in formations:raise ValueError('该教练主偏好阵型尚未映射')
    candidates=[t for t in catalog['templates']if t['style_code']==styles[style]]
    if not candidates:raise ValueError('安装目录中没有该风格的完整预设')
    return candidates,formations

def _rank(candidates,shape,other,phase=0):
    def key(t):
        a=distance(shape,[c['position']for c in t['phases'][phase]])
        b=distance(other,[c['position']for c in t['phases'][1-phase]])if other is not None else 0
        return (a,b,t['index'])
    return min(candidates,key=key),key

def variants(catalog,style,primary,secondary):
    """Up to two presets: the coach's primary and second preferred formation."""
    candidates,formations=_style_candidates(catalog,style,primary)
    primary_positions=formations[primary];secondary_positions=formations.get(secondary)
    first,key=_rank(candidates,primary_positions,secondary_positions);score=key(first)
    match={'primary_code':primary,'secondary_code':secondary,
           'primary_positions':primary_positions,'secondary_positions':secondary_positions,
           'primary_exact':score[0]==0,'secondary_exact':secondary in formations and score[1]==0,
           'position_difference_counts':list(score[:2]),
           'selection_policy':'same_style_then_primary_shape_then_secondary_shape_then_stable_index'}
    result=[{'index':1,'formation_code':primary,'exact':score[0]==0,
             'position_difference':score[0],'preset':first,'match':match}]
    if secondary_positions is None or secondary==primary:return result
    second,second_key=_rank(candidates,secondary_positions,primary_positions)
    if second['index']==first['index']:
        ordered=sorted(candidates,key=lambda t:(distance(secondary_positions,[c['position']for c in t['phases'][0]]),t['index']))
        second=next((t for t in ordered if t['index']!=first['index']),None)
        if second is None:return result
        difference=distance(secondary_positions,[c['position']for c in second['phases'][0]])
    else:
        difference=second_key(second)[0]
    result.append({'index':2,'formation_code':secondary,'exact':difference==0,
                   'position_difference':difference,'preset':second,
                   'match':{**match,'variant':'secondary',
                            'selection_policy':'same_style_then_secondary_shape_then_primary_phase'}})
    return result

def _selection(lib,index,clubs):
    registry=index.get('league_clubs')
    if not isinstance(registry,dict):raise ValueError('此存档缓存缺少联赛球队索引，请重新读取存档')
    rows=[]
    for club_uid in sorted({int(v)for v in clubs}):
        row=registry.get(str(club_uid))
        if not isinstance(row,dict):continue
        team_id=row.get('first_team_id')
        if type(team_id)is not int:continue
        rows.append({'uid':club_uid,'name':row.get('name')or str(club_uid),
                     'short_name':row.get('short_name')or row.get('name')or str(club_uid),
                     'nation_id':row.get('nation_id'),'team_id':team_id})
    if not rows:raise ValueError('联赛没有可读取的球队')
    return rows

def _fresh_prepared(prepared,inputs,stamp,selection_sha,profile):
    required=[inputs,prepared/'source_team_table.json',prepared/'staff_fragments.json',prepared/FRAGMENT_DIRECTORY]
    if not all(p.exists()for p in required):return False
    try:
        data=read(inputs);table=read(prepared/'source_team_table.json')
    except (OSError,ValueError):return False
    if data.get('source_sha256')!=stamp['source_sha256']or data.get('profile')!=profile:return False
    if table.get('source_sha256')!=stamp['source_sha256']:return False
    if selection_sha is not None and data.get('selection_sha256')!=selection_sha:return False
    return True

def ensure(lib,key,clubs=None,slot=None):
    root=lib.folder(key);lib.check_binding(root);stamp=binding(lib,root)
    index=lib.index_data(root)
    folder=root/'coach_presets' if slot is None else root/'league_presets'/slot
    bounded_output(folder);folder.mkdir(parents=True,exist_ok=True)
    cache=folder/'catalog.json'
    selection_sha=None;selection_path=None
    if clubs is not None:
        rows=_selection(lib,index,clubs);selection_sha=digest(rows)
        if cache.exists():
            value=read(cache)
            if value.get('binding')==stamp and value.get('selection_sha256')==selection_sha:return value
        selection_path=folder/'selection.json';lib.write(selection_path,{'clubs':rows})
    elif cache.exists():
        value=read(cache)
        if value.get('binding')==stamp:return value
    prepared=folder/'static_coaches';inputs=prepared/'inputs.json';fragments=prepared/FRAGMENT_DIRECTORY
    if not _fresh_prepared(prepared,inputs,stamp,selection_sha,LEAGUE_PROFILE if clubs is not None else STAFF_PROFILE):
        data=index;source=read(root/'selected_source.json')['path']if(root/'selected_source.json').exists()else data['source']
        prepared.mkdir(exist_ok=True);bounded_output(prepared)
        command=[os.environ.get('FM27_SAVE_PYTHON',sys.executable),str(Path(__file__).with_name('desktop_coach_prepare.py')),source,str(prepared),str(root/'dataset.json')]
        if selection_path is not None:command.append(str(selection_path))
        with(folder/'prepare.log').open('wb')as log:
            result=subprocess.run(command,
                env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'},stdout=log,stderr=log,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise ValueError('教练偏好静态读取失败，见 league_presets 准备日志')
    data=read(inputs);table=read(prepared/'source_team_table.json')
    if data['source_sha256']!=stamp['source_sha256']or table['source_sha256']!=stamp['source_sha256']:raise ValueError('教练与球队引用来自不同存档')
    if selection_sha is not None and data.get('selection_sha256')!=selection_sha:
        data['selection_sha256']=selection_sha;lib.write(inputs,data)
    native=lib.native([],root,'coach_preset_staff_'+digest({'s':selection_sha,'e':stamp})[:12],{'FM27_STAFF_FRAGMENT_DIRECTORY':str(fragments)})
    coaches={r['selector']:r for r in native if r.get('event')=='staff_body_read'and r['accepted']and not r['error']}
    people={s['person_selector']:s for s in data['staff']};expected={s['person_selector']:s for s in read(prepared/'staff_fragments.json')['rows']}
    lib.write(folder/'progress.json',{'stage':'核对教练原版读回并匹配原装预设'})
    catalog=assets(lib,root);teams=[];failures=[]
    managed={m['club_uid']for m in index['managed']}

    def build(club,staff_row,selector,team_id):
        try:
            if staff_row is None or not isinstance(selector,int):raise ValueError('存档中未找到可确认的一线队主教练')
            if staff_row.get('club_uid')!=club['uid']:raise ValueError('主教练球队引用不完整')
            n=coaches.get(selector);e=expected.get(selector)
            if not n or not e or n['profile_hex']!=e['profile_hex']:raise ValueError('教练偏好未通过原版读回')
            raw=bytes.fromhex(n['native_d4_to_f4_hex'])
            if raw[11:19].hex()!=e['codes_hex']:raise ValueError('主次偏好阵型读回不符')
            style,primary,secondary=raw[20],raw[11],raw[12]
            options=variants(catalog,style,primary,secondary)
            rows=[{'index':option['index'],'preset_index':option['preset']['index'],
                   'preset_sha256':digest(option['preset']),'preset_name':option['preset']['name'],
                   'formation':formation_name(lib,[c['position']for c in option['preset']['phases'][0]]),
                   'formation_code':option['formation_code'],'exact':option['exact'],
                   'position_difference':option['position_difference']}for option in options]
            preset=options[0]['preset'];match=options[0]['match']
            test=copy.deepcopy(lib.app.DEFAULT['teams'][1]);lib.apply_plan(test,preset)
            teams.append({'team_id':team_id,'club_uid':club['uid'],'name':club.get('short_name')or club['name'],
                          'coach_uid':staff_row.get('unique_id'),
                          'coach_name':staff_row.get('name')or staff_row.get('full_name')or str(staff_row.get('unique_id')),
                          'coach_selector':selector,'coach_assignment':'first_team_reference',
                          'style_id':style,'style_code':preset['style_code'],'preset_index':preset['index'],
                          'preset_sha256':digest(preset),'preset_name':preset['name'],'formation_match':match,
                          'variants':rows,'roster_size':None})
        except (ValueError,KeyError,StopIteration)as error:
            failures.append({'club_uid':club['uid'],'name':club.get('short_name')or club['name'],'error':str(error)})

    if data.get('profile')==LEAGUE_PROFILE:
        staff_by_club={}
        for row in data.get('staff')or[]:
            current=staff_by_club.get(row.get('club_uid'))
            if current is None or (row.get('team_slot')==0 and current.get('team_slot')!=0):
                staff_by_club[row['club_uid']]=row
        for club in data['clubs']:
            if club['uid']in managed:continue
            staff_row=staff_by_club.get(club['uid'])
            build(club,staff_row,staff_row.get('person_selector')if staff_row else None,
                  staff_row.get('team_id')if staff_row else None)
    else:
        for t in table['records']:
            club=next(c for c in data['clubs']if any(x['team_id']==t['team_id']for x in c['teams']))
            if club['uid']in managed:continue
            selector=t['coach_person_reference'];staff_row=people.get(selector)
            if staff_row and staff_row['is_human_manager']:continue
            build(club,staff_row,selector,t['team_id'])
    value={'binding':stamp,'selection_sha256':selection_sha,'teams':teams,'failures':failures,
           'source_date':data['date'],'preset_assets_binding':catalog['binding']}
    lib.write(cache,value);return value

def opponents(lib,key,own):
    value=ensure(lib,key)
    return [{'key':'coach:'+str(t['team_id']),'fixture_key':'coach:'+str(t['team_id']),'club_uid':t['club_uid'],
             'name':t['name'],'side':1,'available':True,'source_kind':'coach_preference_preset',
             'date':value['source_date'],'member':'original_installation_preset:'+str(t['preset_index']),
             'source':'教练偏好预设 · '+t['coach_name']+' · '+describe(lib,t)+'；非当天实战还原。',
             'cache_roster_count':0,'match_roster_count':0,'roster_pending':True,'excluded_substitute_uids':[],
             'coach':t,'preset_reference_proven':False}
            for t in value['teams']if t['club_uid']!=own]

def preset_by_index(catalog,index):
    preset=next((p for p in catalog['templates']if p['index']==index),None)
    if preset is None:raise ValueError('原装预设目录中不存在该战术')
    return preset

def _preset(lib,key,candidate):
    if not re.fullmatch(r'coach:\d{1,7}',candidate):raise ValueError('无效教练预设标识')
    value=ensure(lib,key);ident=int(candidate.split(':')[1]);t=next((t for t in value['teams']if t['team_id']==ident),None)
    if t is None:raise ValueError('教练预设不属于当前存档')
    catalog=assets(lib,lib.folder(key));preset=preset_by_index(catalog,t['preset_index'])
    if digest(preset)!=t['preset_sha256']:raise ValueError('原装预设内容已改变，请重新读取')
    return preset,t

def _preset_team(lib,preset,name,tactic_name):
    result=copy.deepcopy(lib.app.DEFAULT['teams'][1]);lib.apply_plan(result,preset)
    result.update(name=name,tactic_name=tactic_name)
    neutral=lib.app.unpack_oi(0x80000)
    result['opposition']={'players':[copy.deepcopy(neutral)for _ in result['opposition']['players']],
                          'positions':{p:copy.deepcopy(neutral)for p in result['opposition']['positions']}}
    return result

def preset_by_index_team(lib,key,preset_index,club_name,expected_sha256=None):
    catalog=assets(lib,lib.folder(key));preset=preset_by_index(catalog,preset_index)
    if expected_sha256 is not None and digest(preset)!=expected_sha256:
        raise ValueError('原装预设内容已改变，请重新读取存档')
    return _preset_team(lib,preset,club_name,'教练偏好预设 · '+preset['name'])

def team(lib,key,candidate):
    preset,t=_preset(lib,key,candidate)
    result=_preset_team(lib,preset,t['name'],'教练偏好预设 · '+preset['name'])
    desktop_static_plans.roster(lib,key,t['club_uid'],result)
    return result

def report(lib,key,own):
    import desktop_opponent_scope
    root=lib.folder(key);data=lib.index_data(root);scope=desktop_opponent_scope.identify(data,own)
    scope['played']&=scope['same_league']
    value=ensure(lib,key);rows=[o for o in opponents(lib,key,own)if o['club_uid']in scope['same_league']];available={r['club_uid']for r in rows}
    names={c['uid']:c.get('short_name')or c['name']for c in data['clubs']}
    errors={f['club_uid']:f['error']for f in value['failures']}
    result={'recovery_profile':lib.OPPONENT_PROFILE,'binding':value['binding'],'context_policy':PROFILE,
            'opponents':rows,'failures':value['failures'],'unrecovered_clubs':[{'club_uid':c,'name':names.get(c,str(c)),'reason':errors.get(c,'教练偏好预设尚不可用')}for c in sorted(scope['same_league']-available)],
            'played_opponent_clubs':len(scope['played']),'checked':len(rows),'total_cached':0,'native_executed':0,
            'snapshot_cache_hits':0,'source_policy':'coach_preference_preset','elapsed_seconds':0}
    desktop_opponent_scope.annotate(result,data,own,scope);lib.write(root/f'opponents_{own}.json',result);return result
