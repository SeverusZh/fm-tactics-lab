"""One static game_db read for league coaches only; no match cache or players."""
import hashlib,json,struct,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).with_name('vendor')))

PROFILE = 'static-first-team-coaches-v3'
LEAGUE_PROFILE = 'static-league-coaches-v3'
FRAGMENT_DIRECTORY = 'first_team_staff_fragments'
DIRECTORY_FILE = 'coach_directory.json'
MANAGER_JOB = 16


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def _club_row(value, name):
    getter = value.get if isinstance(value, dict) else lambda key: getattr(value, key, None)
    return getter(name)


def _registry(index, wanted):
    """The league club index's minimal club records for a selection."""
    league_clubs = index.get('league_clubs') if isinstance(index.get('league_clubs'), dict) else {}
    rows = []
    for club_uid in sorted({int(value) for value in wanted}):
        row = league_clubs.get(str(club_uid))
        if not isinstance(row, dict):
            raise ValueError('联赛球队索引缺少所选球队，请重新读取存档')
        team_id = row.get('first_team_id')
        if type(team_id) is not int:
            raise ValueError('联赛球队一线队索引不完整')
        rows.append({'uid': club_uid, 'name': row.get('name') or str(club_uid),
                     'short_name': row.get('short_name') or row.get('name') or str(club_uid),
                     'nation_id': row.get('nation_id'),
                     'teams': [{'team_id': team_id, 'slot': 0}]})
    if not rows:
        raise ValueError('联赛没有可读取的球队')
    return rows


def _scan_managers(source, index):
    """Every first-team manager's preference bytes, read once through fmsave."""
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    import fmsave.readers.staff as reader
    from desktop_save_worker import plain
    wanted = {int(value) for value in (index.get('league_clubs') or {})}
    people = {m.get('club_uid') for m in index.get('managed') or []}
    profiles = {}
    selectors = {}
    by_uid = {}
    original_read = reader._read_ability_block
    original_person = reader._PersonObject

    def capture(db, header, layout):
        result = original_read(db, header, layout)
        if result[0] is not None and result[1] and result[3]:
            base = header + layout.ability_base_offset + layout.entry_bytes * db[header + layout.entry_count_offset]
            start = base + layout.preferences_offset
            end = base + layout.block_40_offset + layout.block_40_count
            if end - start == 52:
                profiles[header] = {
                    'profile_hex': bytes(db[start:end]).hex(),
                    'codes_hex': bytes(db[base + layout.codes_offset:
                                         base + layout.codes_offset + layout.code_count]).hex(),
                    'ability_and_reputation_words': list(struct.unpack_from('<5H', db, base - 6)),
                    'fragment_start': header + 13,
                    'fragment_end': end + 4096,
                }
        return result

    def person(*args, **kwargs):
        obj = original_person(*args, **kwargs)
        selectors[obj.uid] = struct.unpack_from('<I', db, obj.header)[0] + 1
        if obj.header in profiles:
            by_uid[obj.uid] = profiles[obj.header]
        return obj

    reader._read_ability_block = capture
    reader._PersonObject = person
    try:
        with fmsave.open(source) as save:
            with save._context.section('game_db') as db:
                staff = [s for s in save.staff()]
                by_club = {}
                for row in staff:
                    club_uid = _club_row(row, 'club_uid')
                    if club_uid not in wanted or club_uid in people:
                        continue
                    job = _club_row(row, 'job')
                    if job is None or not hasattr(job, 'raw') or job.raw != MANAGER_JOB:
                        continue
                    if not _club_row(row, 'has_contract') or _club_row(row, 'is_human_manager'):
                        continue
                    team_slot = _club_row(row, 'team_slot')
                    if isinstance(team_slot, int) and team_slot != 0:
                        continue
                    uid = _club_row(row, 'uid')
                    info = by_uid.get(uid)
                    selector = selectors.get(uid)
                    if info is None or selector is None:
                        continue
                    manager = {'club_uid': club_uid, 'person_selector': selector, 'uid': uid,
                               'unique_id': _club_row(row, 'unique_id'), 'name': _club_row(row, 'name'),
                               'team_id': _club_row(row, 'team_id'),
                               'team_slot': _club_row(row, 'team_slot'), **info}
                    rank = lambda value: (0 if value.get('team_slot') == 0 else 1, value['uid'])
                    current = by_club.get(club_uid)
                    if current is None or rank(manager) < rank(current):
                        by_club[club_uid] = manager
                for manager in by_club.values():
                    manager['fragment'] = bytes(db[manager.pop('fragment_start'):
                                                   manager.pop('fragment_end')]).hex()
    finally:
        reader._read_ability_block = original_read
        reader._PersonObject = original_person
    return by_club


def _prepare_league(source, folder, index_path, selection_path):
    started = time.monotonic()
    source = Path(source)
    folder = Path(folder)
    index_path = Path(index_path)
    index = _read(index_path)
    selection = _read(selection_path)
    from desktop_storage import bounded_output
    bounded_output(folder)
    folder.mkdir(parents=True, exist_ok=True)
    root = index_path.parent

    def progress(text):
        (folder / 'progress.json').write_text(json.dumps({'stage': text}, ensure_ascii=False), encoding='utf8')

    progress('核对当前存档，准备读取所选联赛教练')
    before = source.stat()
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != index['source_sha256']:
        raise ValueError('存档已更新，请重新读取存档')
    clubs = _registry(index, [row['uid'] for row in selection['clubs']])
    cache = root / DIRECTORY_FILE
    managers = None
    if cache.exists():
        try:
            value = _read(cache)
        except (OSError, ValueError):
            value = None
        if (isinstance(value, dict) and value.get('profile') == LEAGUE_PROFILE
                and value.get('source_sha256') == digest):
            managers = {int(key): row for key, row in value['managers'].items()}
    if managers is None:
        progress('读取一线队主教练偏好')
        managers = _scan_managers(source, index)
        cache.write_text(json.dumps({'profile': LEAGUE_PROFILE, 'source_sha256': digest,
            'managers': {str(key): row for key, row in managers.items()}}, ensure_ascii=False), encoding='utf8')
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('读取期间存档发生变化')
    fragments = folder / FRAGMENT_DIRECTORY
    fragments.mkdir(exist_ok=True)
    staff = []
    rows = []
    progress('写入联赛教练偏好片段')
    for club in clubs:
        manager = managers.get(club['uid'])
        if manager is None:
            continue
        (fragments / f"{manager['person_selector']}.bin").write_bytes(bytes.fromhex(manager['fragment']))
        rows.append({'person_selector': manager['person_selector'], 'profile_hex': manager['profile_hex'],
                     'codes_hex': manager['codes_hex'],
                     'ability_and_reputation_words': manager['ability_and_reputation_words'],
                     'club_uid': club['uid'], 'uid': manager['uid']})
        staff.append({'person_selector': manager['person_selector'], 'uid': manager['uid'],
                      'unique_id': manager['unique_id'], 'name': manager['name'], 'club_uid': club['uid'],
                      'team_id': manager.get('team_id'), 'team_slot': manager.get('team_slot'),
                      'is_human_manager': False})
    result = {'profile': LEAGUE_PROFILE, 'source_sha256': digest, 'date': index['date'],
              'clubs': clubs, 'staff': staff, 'failures': [], 'no_match_cache_read': True,
              'elapsed_seconds': round(time.monotonic() - started, 3)}
    for name, value in [('source_team_table.json', {'records': [], 'source_sha256': digest}),
                        ('staff_fragments.json', {'source_sha256': digest, 'rows': rows}),
                        ('inputs.json', result)]:
        (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    progress('联赛教练静态读取完成')
    return {'coaches': len(rows), 'failures': [], 'elapsed_seconds': result['elapsed_seconds']}


def _prepare_scope(source, folder, index_path):
    import desktop_save_compat
    desktop_save_compat.install()
    import fmsave
    import fmsave.readers.staff as reader
    from desktop_save_worker import plain
    from desktop_generation_team_table import from_save
    from desktop_opponent_scope import identify
    from desktop_storage import bounded_output
    source = Path(source)
    folder = Path(folder)
    bounded_output(folder)
    folder.mkdir(exist_ok=True)
    index = _read(index_path)
    started = time.monotonic()

    def progress(text):
        (folder / 'progress.json').write_text(json.dumps({'stage': text}, ensure_ascii=False), encoding='utf8')

    progress('核对当前存档，准备读取同联赛教练')
    before = source.stat()
    with source.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != index['source_sha256']:
        raise ValueError('存档已更新，请重新读取存档')
    own = index['managed'][0]['club_uid']
    scope = identify(index, own)
    if scope['league'] is None:
        raise ValueError('当前存档同联赛范围尚未识别')
    wanted = set(scope['league']['club_uids'])
    clubs = [c for c in index['clubs'] if c['uid'] in wanted]
    with fmsave.open(source) as save:
        with save._context.section('game_db') as db:
            progress('读取同联赛球队与现任主教练引用')
            first_team_ids = {t['team_id'] for c in clubs for t in c['teams'] if t['slot'] == 0}
            table = from_save(save, db, first_team_ids)
            records = save._context.player_records()
            layouts = reader.find_staff_layouts(save.info.section_schemas, save.info.build)
            layout = layouts.staff
            decoder = reader.build_person_block_decoder(layouts.person_blocks, save._context.name_pools(),
                save._context.club_index(), save.info.game_date, save.info.file_name)
            staff = []
            rows = []
            failures = []
            fragments = folder / FRAGMENT_DIRECTORY
            fragments.mkdir(exist_ok=True)
            managed = {m['club_uid'] for m in index['managed']}
            for team in table['records']:
                club = next(c for c in clubs if any(t['team_id'] == team['team_id'] for t in c['teams']))
                selector = team['coach_person_reference']
                if club['uid'] in managed or selector == 0xffffffff:
                    continue
                progress('定向读取同联赛教练 ' + str(len(rows) + 1) + ' / ' + str(len(table['records']) - len(managed)))
                header = reader.locate_listed_header(db, selector - 1, records, layout)
                if not isinstance(header, int):
                    failures.append({'selector': selector, 'error': '教练对象头未唯一定位'})
                    continue
                identity = reader._header_values(db, header, reader._header_reader(layout), layout)
                block, slots_ok, _codes_ok, further_ok = reader._read_ability_block(db, header, layout)
                if identity is None or block is None or not (slots_ok and further_ok):
                    failures.append({'selector': selector, 'error': '教练偏好字段未通过结构校验'})
                    continue
                _, ceiling = reader._bracket_window(db, selector - 1, records)
                closing = reader._closing_header(db, selector - 1, header, identity[0],
                                                 ceiling if ceiling < len(db) else None, layout)
                if closing is None:
                    failures.append({'selector': selector, 'error': '教练结尾身份未通过校验'})
                    continue
                lo, hi = reader._person_block_window(db, header, None, closing[0], layout)
                person = decoder.decode(db, lo, hi)
                if person is None:
                    person = decoder.decode(db, header + layout.kind_offset, closing[0])
                base = header + layout.ability_base_offset + layout.entry_bytes * db[header + layout.entry_count_offset]
                start = base + layout.preferences_offset
                end = base + layout.block_40_offset + layout.block_40_count
                if end - start != 52:
                    raise ValueError('教练偏好结构大小变化')
                raw = bytes(db[header + 13:end + 4096])
                (fragments / f'{selector}.bin').write_bytes(raw)
                rows.append({'person_selector': selector, 'profile_hex': bytes(db[start:end]).hex(),
                             'codes_hex': bytes(db[base + layout.codes_offset:
                                                  base + layout.codes_offset + layout.code_count]).hex(),
                             'ability_and_reputation_words': list(struct.unpack_from('<5H', db, base - 6))})
                staff.append({'person_selector': selector, 'uid': identity[0], 'unique_id': closing[1],
                              'name': person[reader._PERSON_NAME] if person else str(closing[1]),
                              'club_uid': club['uid'], 'is_human_manager': False})
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('读取期间存档发生变化')
    table['source_sha256'] = digest
    result = {'profile': PROFILE, 'source_sha256': digest, 'date': index['date'], 'clubs': clubs,
              'staff': staff, 'failures': failures, 'elapsed_seconds': round(time.monotonic() - started, 3),
              'no_match_cache_read': True}
    for name, value in [('source_team_table.json', table),
                        ('staff_fragments.json', {'source_sha256': digest, 'rows': rows}),
                        ('inputs.json', result)]:
        (folder / name).write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
    progress('教练静态读取完成，核对原版读回与原装预设')
    return {'coaches': len(rows), 'failures': failures, 'elapsed_seconds': result['elapsed_seconds']}


def prepare(source, folder, index_path, selection_path=None):
    if selection_path is not None:
        return _prepare_league(source, folder, index_path, selection_path)
    return _prepare_scope(source, folder, index_path)


if __name__ == '__main__':
    print(json.dumps(prepare(*sys.argv[1:]), ensure_ascii=False), flush=True)
