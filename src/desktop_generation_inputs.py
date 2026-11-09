"""Read-only career inputs for native AI generation; never admits a partial plan."""
from pathlib import Path
import hashlib,json,struct

PROFILE='source-career-generation-inputs-v1'

def export(source,folder,include_manager_section=False):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    import fmsave.readers.staff as reader
    from fmsave import _version
    from fmsave._container import read_section
    from desktop_save_worker import plain
    from desktop_save_players import selected_players
    from desktop_opponent_scope import identify
    _version.FM27_FRAME_DECOMPRESSED_CAP=768*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=1536*1024**2
    from desktop_storage import bounded_output
    source=Path(source);folder=Path(folder);bounded_output(folder);folder.mkdir(parents=True,exist_ok=True)
    before=source.stat()
    with source.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    profiles={};by_uid={};person_by_uid={};headers={};original_read=reader._read_ability_block;original_person=reader._PersonObject
    def capture(db,header,layout):
        result=original_read(db,header,layout)
        if result[0]is not None and all(result[1:]):
            base=header+layout.ability_base_offset+layout.entry_bytes*db[header+layout.entry_count_offset]
            start=base+layout.preferences_offset;end=base+layout.block_40_offset+layout.block_40_count
            assert end-start==52 and layout.preference_count==26 and layout.block_40_count==26
            profiles[header]={'header_offset':header,'ability_offset':base,'profile_offset':start,
                'raw_52_bytes_hex':db[start:end].hex(),'formation_codes_hex':db[base+layout.codes_offset:base+layout.codes_offset+layout.code_count].hex(),
                'raw_r4':db[base+layout.r4_offset],'native_marshalling_verified':False}
        return result
    def person(*a,**kw):
        obj=original_person(*a,**kw)
        person_by_uid[obj.uid]=struct.unpack_from('<I',db,obj.header)[0]+1
        headers[obj.uid]=obj.header
        if obj.header in profiles:by_uid[obj.uid]=profiles[obj.header]
        return obj
    reader._read_ability_block=capture;reader._PersonObject=person
    try:
        with fmsave.open(source)as save:
            # Keep a single loan across dependent readers to avoid repeated decompression.
            with save._context.section('game_db')as db:
                managed=[plain(v)for v in save.managed_clubs()]
                clubs=[plain(v)for v in save.clubs()];fixtures=[plain(v)for v in save.fixtures()]
                assert len(managed)==1,'Explicit managed-club selection required for multiple managers.'
                club=managed[0]['club_uid']
                scope=identify({'fixtures':fixtures,'date':str(save.info.game_date)},club)
                assert scope['league']is not None and not scope['ambiguous_leagues'],'League scope ambiguous.'
                wanted=set(scope['league']['club_uids'])
                players,identities,counts,first_counts,native=selected_players(save,wanted)
                staff=[plain(s)for s in save.staff()if s.club_uid in wanted]
                for row in staff:
                    row['generation_profile']=by_uid.get(row['uid'])
                    row['person_selector']=person_by_uid[row['uid']]
                    row['header']=headers.get(row['uid'])
                records=save._context.player_records()
                selectors={str(i+1):native[uid]for i,uid in zip(records.pindexes,records.uids)if native.get(uid)is not None}
                job_error=None
                try:jobs=[plain(j)for j in save.job_vacancies()if j.club_uid in wanted]
                except (AttributeError,ValueError,RuntimeError)as error:jobs=[];job_error=str(error)
                nations={str(n.nation_id):n.database_id for n in save.nations()}
                sections={}
                for name in (('tactics_man','manager_manager')if include_manager_section else('tactics_man',)):
                    if name not in save.info.section_schemas:continue
                    raw=read_section(save._container_index,name)
                    (folder/(name+'.bin')).write_bytes(raw)
                    sections[name]={'schema':save.info.section_schemas[name],'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                value={'profile':PROFILE,'source':str(source),'source_sha256':digest,'build':save.info.build,
                    'date':str(save.info.game_date),'managed':managed,'league':scope['league'],
                    'clubs':[c for c in clubs if c['uid']in wanted],
                    'players':[plain(p)for p in players],'staff':staff,'player_selectors':selectors,
                    'fixtures':[f for f in fixtures if f.get('home_club_uid')in wanted and f.get('away_club_uid')in wanted],
                    'job_vacancies':jobs,'job_reader_error':job_error,'sections':sections,'nations':nations,
                    'source_first_team_counts':{str(c):first_counts.get(str(c),0)for c in wanted},
                    'admitted_to_simulator':False,'unresolved':['tactical_responsibility_references','native_marshalling','complete_match_context']}
    finally:reader._read_ability_block=original_read;reader._PersonObject=original_person
    after=source.stat()
    assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),'Source changed during read.'
    (folder/'generation_inputs.json').write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
    return {k:value[k]for k in ('source_sha256','date','build','league','sections','source_first_team_counts','job_reader_error')}|{'players':len(value['players']),'staff':len(staff)}

if __name__=='__main__':
    import sys
    print(json.dumps(export(sys.argv[1],sys.argv[2]),ensure_ascii=False),flush=True)
