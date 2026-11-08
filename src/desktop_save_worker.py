"""Read-only save decoding in a separate, bounded-lifetime Python process."""
from pathlib import Path
import dataclasses
import hashlib
import json
import struct
import sys
import time
from collections import defaultdict
sys.path.insert(0, str(Path(__file__).with_name('vendor')))


def plain(value):
    if dataclasses.is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if hasattr(value, 'items'):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def write(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    for attempt in range(21):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt==20: raise
            time.sleep(.025)


def extract_match_inputs(save,folder):
    from fmsave._container import match_file_entries,read_directory_entry
    caches=[];seen=set();warnings=[]
    body=bytes.fromhex('1b0000004c00000275261f00')
    for entry in match_file_entries(save._container_index):
        raw=read_directory_entry(save._container_index,entry)
        if raw.startswith(bytes.fromhex('03016d70612e0100')):offset=9
        elif raw.startswith(bytes.fromhex('03016d73742e00')):
            offset=raw.find(body,7)
            if offset>=0 and raw.find(body,offset+1)>=0:continue
        else:continue
        if offset<0 or raw[offset:offset+len(body)]!=body:
            warnings.append('跳过未知版本比赛缓存：'+entry.name+entry.extension);continue
        payload=bytes.fromhex('03016d6b702e0000')+raw[offset:]
        digest=hashlib.sha256(payload).hexdigest()
        if digest in seen:continue
        seen.add(digest);path=folder/(digest+'.pkm');path.write_bytes(payload)
        caches.append({'key':digest,'path':path.name,'member':entry.name+entry.extension})
    return caches,warnings


def fixture_anchor(row):
    if not row.get('played') or row.get('home_goals') is None or row.get('away_goals') is None:return None
    if row.get('match_record_id') is None:return None
    return tuple(row.get(k) for k in ('match_record_id','stage_id','home_team_id','away_team_id','date','home_goals','away_goals'))


def read_recovery_source(source,folder,request):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    wanted=json.loads(request.read_text(encoding='utf8'))
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2;_version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    before=source.stat()
    with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with fmsave.open(source) as save:
        if save.info.game!=wanted['game']:raise ValueError('来源不是同一代 Football Manager 存档')
        people={(m.manager_staff_uid,m.manager_name) for m in save.managed_clubs()}
        if not people.intersection(tuple(p) for p in wanted['human_identity']):raise ValueError('其他生涯的经理身份，不合并来源')
        anchors={fixture_anchor(plain(f)) for f in save.fixtures()};anchors.discard(None)
        common=len(anchors.intersection(tuple(a) for a in wanted['anchors']))
        if common<3:raise ValueError('不足3条独立比赛记录锚点，无法确认生涯连续性')
        caches,warnings=extract_match_inputs(save,folder)
        clubs=[{**{k:getattr(c,k) for k in ('uid','unique_id','name','short_name')},'teams':plain(c.teams)} for c in save.clubs()]
        result={'profile':'same-career-match-source-v1','primary_sha256':wanted['source_sha256'],'source':str(source),'source_sha256':digest,
            'date':str(save.info.game_date),'build':save.info.build,'human_identity':list(people),'matching_fixture_anchors':common,'clubs':clubs,'caches':caches,'warnings':warnings}
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('读取期间来源存档发生变化')
    write(folder/'source.json',result)


def read_ai_source(source,folder):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from fmsave._container import read_section
    from desktop_save_players import selected_players
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2;_version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    before=source.stat()
    with source.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=json.loads((folder/'dataset.json').read_text(encoding='utf8'))['source_sha256']:raise ValueError('存档已更新，请重新导入')
    with fmsave.open(source) as save:
        if save.info.section_schemas.get('tactics_man')!=26:raise ValueError('电脑战术表版本尚未支持')
        section=read_section(save._container_index,'tactics_man')
        if len(section)>32*1024**2:raise ValueError('电脑战术表超出读取上限')
        _,_,_,_,native=selected_players(save,set());records=save._context.player_records()
        selectors={str(i+1):native[uid] for i,uid in zip(records.pindexes,records.uids) if native.get(uid)is not None}
        managers=[plain(s) for s in save.staff() if s.job is not None and s.job.raw==16 and s.has_contract]
        result={'profile':'ai-state-source-v1','source_sha256':digest,'build':save.info.build,'schema':26,'section_sha256':hashlib.sha256(section).hexdigest(),'managers':managers}
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('读取期间存档发生变化')
    (folder/'ai_tactics_section.bin').write_bytes(section);write(folder/'ai_player_selectors.json',selectors)
    result['selectors_sha256']=hashlib.sha256((folder/'ai_player_selectors.json').read_bytes()).hexdigest()
    write(folder/'ai_source.json',result)


def main(source, folder):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from fmsave._container import match_file_entries, read_directory_entry, read_section
    from fmsave.readers.tactics import find_tactics_layout, _read_tactic_record, _read_slot_block, _read_text
    _version.FM27_FRAME_DECOMPRESSED_CAP = 384 * 1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP = 768 * 1024**2
    before = source.stat()
    def progress(stage):
        write(folder/'progress.json', {'status': 'reading', 'stage': stage})
    progress('读取存档目录与经理关联')
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    with fmsave.open(source) as save:
        info = save.info
        managed = [plain(v) for v in save.managed_clubs()]
        clubs = [{**{k:getattr(v,k) for k in ['uid','unique_id','name','short_name','nation_id']},'teams':plain(v.teams)} for v in save.clubs()]
        progress('读取人类经理球队属性与球员身份索引')
        from desktop_save_players import selected_players
        from fmsave.table import Table
        from fmsave.models.players import Player
        player_fields=['uid','unique_id','name','club_uid','team_id','team_slot','team_club_uid','positions','raw_attributes','raw_left_foot','raw_right_foot',
                       'height_cm','age','ability','personality','trait_bits','reputation']
        wanted={m['club_uid']for m in managed}
        decoded,uid_clubs,counts,first_counts,local_to_native=selected_players(save,wanted,roster_only=True)
        # The tactic reader only resolves the managed clubs' stored selections.
        # Its original tactic/selection checks still run; no global full-player
        # table or successful global player-pass check is fabricated.
        save._context.cached('table:players',lambda:Table(decoded,Player))
        squads=defaultdict(list)
        for v in decoded:squads[v.club_uid].append({k:plain(getattr(v,k))for k in player_fields})
        roster_dir=folder/'rosters';roster_dir.mkdir(exist_ok=True)
        for club,rows in squads.items():write(roster_dir/(str(club)+'.json'),rows)
        write(folder/'player_index.json',uid_clubs)
        del decoded,squads
        warnings = []
        try:
            progress('识别当前同联赛与本队赛事，不读取历史比赛缓存')
            calendar=save.fixtures()
            groups={(v.competition_id,v.stage_id,v.season_start_year)for v in calendar if v.home_club_uid in wanted or v.away_club_uid in wanted}
            fixtures=[plain(v)for v in calendar if(v.competition_id,v.stage_id,v.season_start_year)in groups and v.home_team_slot==0 and v.away_team_slot==0]
        except Exception as error:
            fixtures = []
            warnings.append('赛程读取失败：'+str(error))
        try:
            tactics = [plain(v) for v in save.tactics()]
            selections = [plain(v) for v in save.selections()]
            for selection in selections:
                selection['source_uid']=local_to_native.get(selection['player_uid'])
        except Exception as error:
            tactics, selections = [], []
            warnings.append('当前战术／首发读取失败：'+str(error))
        progress('提取存储战术原始数据')
        section = read_section(save._container_index, 'tactics_man')
        layout = find_tactics_layout(info.section_schemas.get('tactics_man'), info.build)
        signatures = set([layout.user_signature, layout.alternate_signature, layout.preset_signature])
        offsets = sorted({i for sig in signatures for i in find_all(section, sig)})
        raw_plans = []
        for number, start in enumerate(offsets):
            end = offsets[number+1] if number+1 < len(offsets) else len(section)
            try:
                rec = _read_tactic_record(section, start, end, layout, source.name)
                if not rec.walk_complete or not rec.oop_index_permutation:
                    continue
                # Walk the same bounded fields to find the exact end; no bytes
                # from the following tactic or team are passed to the native reader.
                cursor = start + len(layout.user_signature)
                _, cursor = _read_text(section, cursor, end, layout, source.name, 'name')
                cursor += layout.name_zero_bytes + layout.team_instruction_bytes
                _, cursor = _read_text(section, cursor, end, layout, source.name, 'style')
                cursor += layout.style_code_bytes
                for _ in range(11):
                    ip = _read_slot_block(section, cursor, end, layout, with_index_byte=False)
                    op = _read_slot_block(section, ip.end, end, layout, with_index_byte=True)
                    cursor = op.end
                path = folder/f'tactic_{number}.bin'
                # The slot walk is not the end of the plan. Retain its bounded
                # tail (lineup/metadata); the native reader determines the exact
                # consumed prefix and that prefix is verified again separately.
                path.write_bytes(section[start:end])
                raw_plans.append({'name': rec.name, 'path': path.name, 'slots': plain(rec.slots)})
            except Exception:
                continue
        for t in tactics:
            matches = [p for p in raw_plans if p['name'] == t['name'] and p['slots'] == t['slots']]
            if matches:
                t['raw_plan'] = matches[0]['path']
        # Same-league coach presets do not consume historical match recordings.
        caches=[]
        from desktop_opponent_scope import identify
        retained_clubs=set(wanted)
        for owner in wanted:
            retained_clubs.update(identify({'fixtures':fixtures,'date':str(info.game_date)},owner)['same_league'])
        clubs=[club for club in clubs if club['uid']in retained_clubs]
        retained_keys={str(c) for c in retained_clubs}
        counts={k:v for k,v in counts.items()if k in retained_keys}
        first_counts={k:v for k,v in first_counts.items()if k in retained_keys}
        result = {'schema':4, 'player_loading':'managed-first-selective-v2','opponent_loading':'same-league-coach-only-v2', 'reader_compatibility_profile':desktop_save_compat.PROFILE,
                  'source':str(source), 'source_sha256':digest,
                  'date':str(info.game_date), 'build':info.build,
                  'managed':managed, 'clubs':clubs, 'player_counts':counts,'first_team_counts':first_counts,
                  'fixtures':fixtures, 'tactics':tactics, 'selections':selections,
                  'caches':caches, 'warnings':warnings}
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('解析期间存档发生变化，请等待游戏保存完成后重试')
    write(folder/'dataset.json', result)
    write(folder/'progress.json', {'status':'complete','stage':'存档数据读取完成'})


def find_all(data, pattern):
    start = 0
    while True:
        start = data.find(pattern, start)
        if start < 0:
            return
        yield start
        start += len(pattern)


def club_registry(source, folder):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with fmsave.open(source)as save:
        clubs=[{**{k:getattr(c,k)for k in ['uid','unique_id','name','short_name']},'teams':plain(c.teams)}for c in save.clubs()]
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('存档在读取期间发生变化')
    write(folder/'club_registry.json',{'source_sha256':digest,'clubs':clubs})


def read_compact_index(source, folder):
    """Explicit diagnostic export; never adds these partial rows to opponents."""
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from fmsave._container import read_section
    from desktop_save_compact import find_table
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    with fmsave.open(source)as save:
        managed={m.club_uid for m in save.managed_clubs()}
        clubs=save.clubs()
        owners=[t.team_id for c in clubs if c.uid in managed for t in c.teams]
        section=read_section(save._container_index,'tactics_man')
        table=find_table(section,owners)
        registry={t.team_id:{'club_uid':c.uid,'club_unique_id':c.unique_id,'team_slot':t.slot,
                            'name':c.short_name or c.name}for c in clubs for t in c.teams}
        for row in table['records']:
            row['club']=registry.get(row['team_id'])
            row['opponent']=registry.get(row['opponent_team_id'])
        result={**table,'source_sha256':digest,'source':str(source),'build':save.info.build,
                'date':str(save.info.game_date),'section_sha256':hashlib.sha256(section).hexdigest(),
                'reader_compatibility_profile':desktop_save_compat.PROFILE,
                'notice':'诊断索引，尚缺完整指令和双阶段球员映射，不可作为完整对战方案。'}
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('读取期间存档发生变化')
    write(folder/'compact_team_index.json',result)


def read_saved_tactics_source(source, folder):
    """Export the owned section and its independent person-reference index."""
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from fmsave._container import read_section
    from desktop_save_players import selected_players
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=json.loads((folder/'dataset.json').read_text(encoding='utf8'))['source_sha256']:
        raise ValueError('存档已更新，请重新导入后读取保存方案')
    with fmsave.open(source)as save:
        if save.info.section_schemas.get('play_fixture_manager')!=7:
            raise ValueError('此版本的存储比赛记录布局尚未支持')
        section=read_section(save._container_index,'play_fixture_manager')
        if len(section)>16*1024**2:raise ValueError('存储比赛记录超出当前读取上限')
        _,_,_,_,local_to_native=selected_players(save,set())
        records=save._context.player_records()
        selectors={str(pindex+1):local_to_native[uid]for pindex,uid in zip(records.pindexes,records.uids)
                   if local_to_native.get(uid)is not None}
        result={'profile':'saved-fixture-section-v1','source_sha256':digest,
                'section_sha256':hashlib.sha256(section).hexdigest(),'build':save.info.build,
                'section_schema':7,'selector_count':len(selectors)}
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('读取期间存档发生变化')
    # Commit the receipt last: an interrupted export is never considered reusable.
    (folder/'saved_fixture_section.bin').write_bytes(section)
    write(folder/'saved_player_selectors.json',selectors)
    result['selectors_sha256']=hashlib.sha256((folder/'saved_player_selectors.json').read_bytes()).hexdigest()
    write(folder/'saved_fixture_source.json',result)


def read_rosters(source, folder, request):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from desktop_save_players import selected_players
    _version.FM27_FRAME_DECOMPRESSED_CAP=384*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=768*1024**2
    wanted=json.loads(request.read_text(encoding='utf8'))
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=wanted['source_sha256']:raise ValueError('存档已更新，请重新读取存档后加载对手')
    fields=['uid','unique_id','name','club_uid','team_id','team_slot','team_club_uid','positions','raw_attributes','raw_left_foot','raw_right_foot','height_cm','age','ability','personality','trait_bits','reputation']
    with fmsave.open(source)as save:players,*_=selected_players(save,set(wanted['clubs']),roster_only=True)
    after=source.stat()
    if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('读取期间存档发生变化')
    squads=defaultdict(list)
    for v in players:squads[v.club_uid].append({k:plain(getattr(v,k))for k in fields})
    for club in wanted['clubs']:write(folder/'rosters'/(str(club)+'.json'),squads[club])
    write(request.with_suffix('.done.json'),{'clubs':wanted['clubs'],'players':len(players),'source_sha256':digest})


if __name__ == '__main__':
    folder = Path(sys.argv[2])
    try:
        if len(sys.argv)>4 and sys.argv[3]=='--rosters':read_rosters(Path(sys.argv[1]),folder,Path(sys.argv[4]))
        elif len(sys.argv)>3 and sys.argv[3]=='--club-index':club_registry(Path(sys.argv[1]),folder)
        elif len(sys.argv)>3 and sys.argv[3]=='--compact-index':read_compact_index(Path(sys.argv[1]),folder)
        elif len(sys.argv)>3 and sys.argv[3]=='--saved-tactics':read_saved_tactics_source(Path(sys.argv[1]),folder)
        elif len(sys.argv)>3 and sys.argv[3]=='--ai-tactics':read_ai_source(Path(sys.argv[1]),folder)
        elif len(sys.argv)>4 and sys.argv[3]=='--recovery-source':read_recovery_source(Path(sys.argv[1]),folder,Path(sys.argv[4]))
        else:main(Path(sys.argv[1]), folder)
    except Exception as error:
        if len(sys.argv)>3 and sys.argv[3]in ('--club-index','--rosters','--compact-index','--saved-tactics','--ai-tactics','--recovery-source'):write(folder/'selective_reader_error.json',{'error':str(error)})
        else:write(folder/'progress.json', {'status':'error', 'stage':str(error)})
        raise
