"""Save-side fragments for real AI generation; no career TEAM table involved."""
import hashlib
import json
import sys
from pathlib import Path


def _human(folder):
    try:
        import desktop_generation_human
        return desktop_generation_human.export(folder)
    except Exception as error:
        return {'error':str(error)}


def prepare(source,folder):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    from fmsave import _version
    from desktop_storage import bounded_output
    _version.FM27_FRAME_DECOMPRESSED_CAP=768*1024**2
    _version.FM27_TOTAL_DECOMPRESSED_CAP=1536*1024**2
    source=Path(source);folder=Path(folder);bounded_output(folder);folder.mkdir(parents=True,exist_ok=True)
    inputs=json.loads((folder/'generation_inputs.json').read_text(encoding='utf8'))
    if inputs['source_sha256']!=hashlib.sha256(Path(inputs['source']).read_bytes()).hexdigest():
        raise ValueError('来源存档已改变，请重新读取')
    target=folder/'staff_fragments';target.mkdir(exist_ok=True)
    rows=[]
    import desktop_generation_human

    def preset_fragment(selector,digest):
        root=folder.parent/'league_presets'
        if not root.is_dir():return None
        for metadata in root.glob('*/static_coaches/staff_fragments.json'):
            try:value=json.loads(metadata.read_text(encoding='utf8'))
            except (OSError,ValueError):continue
            if value.get('source_sha256')!=digest:continue
            row=next((item for item in value.get('rows')or [] if item.get('person_selector')==selector),None)
            if row is None:continue
            raw=metadata.parent/'first_team_staff_fragments'/f'{selector}.bin'
            if not raw.is_file():continue
            return {'raw':raw.read_bytes(),'profile_hex':row['profile_hex'],'codes_hex':row['codes_hex']}
        return None

    league_clubs={club['uid']for club in inputs.get('clubs')or []}
    def wanted(staff):
        if staff.get('club_uid')not in league_clubs or staff.get('is_human_manager'):return False
        return (staff.get('job')or {}).get('raw')==16 and staff.get('has_contract')is True
    with fmsave.open(source)as save:
        with save._context.section('game_db')as db:
            for staff in inputs['staff']:
                if not wanted(staff):continue
                selector=staff.get('person_selector')
                if type(selector)is not int:continue
                try:
                    profile=staff.get('generation_profile')
                    if profile:
                        header=profile['header_offset'];profile_offset=profile['profile_offset']
                        start=header+13;end=profile_offset+52+4096
                        if not (start<profile_offset<end<=len(db)):raise ValueError('教练档案边界无效')
                        raw=bytes(db[start:end]);profile_hex=profile['raw_52_bytes_hex'];codes=profile['formation_codes_hex']
                    else:
                        cached=preset_fragment(selector,inputs['source_sha256'])
                        if cached is not None:
                            raw=cached['raw'];profile_hex=cached['profile_hex'];codes=cached['codes_hex']
                        else:
                            header=staff.get('header');uid=staff.get('unique_id')
                            if type(header)is not int or type(uid)is not int:raise ValueError('教练档案位置未知')
                            located=desktop_generation_human.locate(db,header,selector,uid)
                            raw=bytes(db[located['body_offset']:located['closing_person_offset']])
                            profile_hex=located['raw_52_bytes_hex'];codes=located['formation_codes_hex']
                    (target/f'{selector}.bin').write_bytes(raw)
                    rows.append({'person_selector':selector,'human':False,'uid':staff.get('uid'),
                        'profile_hex':profile_hex,'codes_hex':codes,'raw_sha256':hashlib.sha256(raw).hexdigest()})
                except Exception as error:
                    print('skip staff',selector,error,file=sys.stderr,flush=True)
    human=_human(folder)
    human_row=None
    if 'error' not in human:
        selector=human['selector'];profile=human['profile']
        source_path=folder/'human_staff_fragments'/f'{selector}.bin'
        raw=source_path.read_bytes();(target/f'{selector}.bin').write_bytes(raw)
        human_row={'person_selector':selector,'human':True,'uid':human['native_uid'],
            'profile_hex':profile['raw_52_bytes_hex'],'codes_hex':profile['formation_codes_hex'],
            'raw_sha256':hashlib.sha256(raw).hexdigest()}
        rows.append(human_row)
    value={'source_sha256':inputs['source_sha256'],'rows':rows,'human_ready':human_row is not None,
           'human_error':human.get('error')}
    (folder/'staff_fragments.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    return {'source_sha256':value['source_sha256'],'fragments':len(rows),'human_ready':value['human_ready']}


if __name__=='__main__':
    print(json.dumps(prepare(sys.argv[1],sys.argv[2]),ensure_ascii=False),flush=True)
