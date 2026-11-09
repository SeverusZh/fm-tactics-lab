"""One static game_db read for league coaches only; no match cache or players."""
import hashlib,json,struct,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).with_name('vendor')))

PROFILE = 'static-first-team-coaches-v3'
FRAGMENT_DIRECTORY = 'first_team_staff_fragments'

def prepare(source,folder,index_path):
    import desktop_save_compat;desktop_save_compat.install()
    import fmsave
    import fmsave.readers.staff as reader
    from desktop_save_worker import plain
    from desktop_generation_team_table import from_save
    from desktop_opponent_scope import identify
    from desktop_storage import bounded_output
    source=Path(source);folder=Path(folder);bounded_output(folder);folder.mkdir(exist_ok=True)
    index=json.loads(Path(index_path).read_text(encoding='utf8'));started=time.monotonic()
    def progress(text):
        (folder/'progress.json').write_text(json.dumps({'stage':text},ensure_ascii=False),encoding='utf8')
    progress('核对当前存档，准备读取同联赛教练')
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=index['source_sha256']:raise ValueError('存档已更新，请重新读取存档')
    own=index['managed'][0]['club_uid'];scope=identify(index,own)
    if scope['league']is None:raise ValueError('当前存档同联赛范围尚未识别')
    wanted=set(scope['league']['club_uids']);clubs=[c for c in index['clubs']if c['uid']in wanted]
    with fmsave.open(source)as save:
        with save._context.section('game_db')as db:
            progress('读取同联赛球队与现任主教练引用')
            first_team_ids={t['team_id']for c in clubs for t in c['teams']if t['slot']==0}
            table=from_save(save,db,first_team_ids)
            records=save._context.player_records();layouts=reader.find_staff_layouts(save.info.section_schemas,save.info.build)
            layout=layouts.staff
            decoder=reader.build_person_block_decoder(layouts.person_blocks,save._context.name_pools(),save._context.club_index(),save.info.game_date,save.info.file_name)
            staff=[];rows=[];failures=[];fragments=folder/FRAGMENT_DIRECTORY;fragments.mkdir(exist_ok=True)
            managed={m['club_uid']for m in index['managed']}
            for team in table['records']:
                club=next(c for c in clubs if any(t['team_id']==team['team_id']for t in c['teams']))
                selector=team['coach_person_reference']
                if club['uid']in managed or selector==0xffffffff:continue
                progress('定向读取同联赛教练 '+str(len(rows)+1)+' / '+str(len(table['records'])-len(managed)))
                header=reader.locate_listed_header(db,selector-1,records,layout)
                if not isinstance(header,int):
                    failures.append({'selector':selector,'error':'教练对象头未唯一定位'});continue
                identity=reader._header_values(db,header,reader._header_reader(layout),layout)
                block,slots_ok,_codes_ok,further_ok=reader._read_ability_block(db,header,layout)
                if identity is None or block is None or not(slots_ok and further_ok):
                    failures.append({'selector':selector,'error':'教练偏好字段未通过结构校验'});continue
                _,ceiling=reader._bracket_window(db,selector-1,records)
                closing=reader._closing_header(db,selector-1,header,identity[0],ceiling if ceiling<len(db)else None,layout)
                if closing is None:
                    failures.append({'selector':selector,'error':'教练结尾身份未通过校验'});continue
                lo,hi=reader._person_block_window(db,header,None,closing[0],layout)
                person=decoder.decode(db,lo,hi)
                if person is None:person=decoder.decode(db,header+layout.kind_offset,closing[0])
                base=header+layout.ability_base_offset+layout.entry_bytes*db[header+layout.entry_count_offset]
                start=base+layout.preferences_offset;end=base+layout.block_40_offset+layout.block_40_count
                if end-start!=52:raise ValueError('教练偏好结构大小变化')
                raw=bytes(db[header+13:end+4096]);(fragments/f'{selector}.bin').write_bytes(raw)
                rows.append({'person_selector':selector,'profile_hex':bytes(db[start:end]).hex(),
                    'codes_hex':bytes(db[base+layout.codes_offset:base+layout.codes_offset+layout.code_count]).hex(),
                    'ability_and_reputation_words':list(struct.unpack_from('<5H',db,base-6))})
                staff.append({'person_selector':selector,'uid':identity[0],'unique_id':closing[1],
                    'name':person[reader._PERSON_NAME]if person else str(closing[1]),
                    'club_uid':club['uid'],'is_human_manager':False})
    after=source.stat()
    if(before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('读取期间存档发生变化')
    table['source_sha256']=digest
    result={'profile':PROFILE,'source_sha256':digest,'date':index['date'],'clubs':clubs,'staff':staff,'failures':failures,
        'elapsed_seconds':round(time.monotonic()-started,3),'no_match_cache_read':True}
    for name,value in [('source_team_table.json',table),('staff_fragments.json',{'source_sha256':digest,'rows':rows}),('inputs.json',result)]:
        (folder/name).write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    progress('教练静态读取完成，核对原版读回与原装预设')
    return {'coaches':len(rows),'failures':failures,'elapsed_seconds':result['elapsed_seconds']}

if __name__=='__main__':print(json.dumps(prepare(*sys.argv[1:]),ensure_ascii=False),flush=True)
