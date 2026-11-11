"""Competition and nation display names from the FM27 installation's language database."""
from pathlib import Path
import hashlib
import json
import os
import struct
import time

BLOCK_MAGIC = b'\x03\x01tad.'
FRAME_MAGIC = b'\x28\xb5\x2f\xfd'
MAX_TEXT_BYTES = 4096
MIN_OVERLAP_RATIO = 0.5
CACHE_DIRECTORY = 'game_db_names'
CACHE_PROFILE = 'game-db-names-v2'
CHECKPOINTS = {'en': (2 * 1024 ** 2, 16 * 1024 ** 2, 64 * 1024 ** 2, 160 * 1024 ** 2),
                'zh': (160 * 1024 ** 2, 64 * 1024 ** 2, 16 * 1024 ** 2, 2 * 1024 ** 2)}
# Each language stores the same fields with its own terminator convention:
# English ends names with 0xff and the code field with none, Chinese ends names
# with 0x00 (and its competition code also ends with 0x00).
TABLE_SHAPES = {
    'en': {'nations': (0xff, 0xff, None, 0x00), 'competitions': (0xff, 0xff, 0x00)},
    'zh': {'nations': (0x00, 0x00, None, 0x00), 'competitions': (0x00, 0x00, 0x00)},
}
COUNT_RANGES = {'nations': (100, 5000), 'competitions': (500, 60000)}


class _Incomplete(ValueError):
    pass


def _unavailable(detail):
    return {'competitions': {}, 'nations': {}, 'source': 'unavailable', 'detail': detail, 'language': None}


def _zstd():
    try:
        from backports import zstd
        return zstd
    except (ImportError, RuntimeError):
        pass
    try:
        from fmsave._container import zstd
        return zstd
    except ImportError:
        from compression import zstd
        return zstd


def _ids(values):
    return {value for value in values or () if type(value) is int}


def _u32(stream, offset):
    if offset + 4 > len(stream):
        raise _Incomplete('名称表在长度字段前被截断')
    return struct.unpack_from('<I', stream, offset)[0]


def _records(stream, start, end, shape, count, allow_partial=False):
    """Parse a name table's records; a partial parse is only valid when allowed."""
    records = []
    offset = start + 12
    for _ in range(count):
        try:
            record_id = _u32(stream, offset)
            offset += 4
            values = []
            for terminator in shape:
                length = _u32(stream, offset)
                offset += 4
                if length > MAX_TEXT_BYTES or offset + length > end:
                    raise _Incomplete('名称表字段超出所在块')
                try:
                    text = stream[offset:offset + length].decode('utf8')
                except UnicodeDecodeError as error:
                    raise ValueError('名称表文本不是 UTF-8') from error
                offset += length
                if terminator is not None:
                    if offset >= end or stream[offset] != terminator:
                        raise ValueError('名称表字段终止标记异常')
                    offset += 1
                values.append(text)
            records.append((record_id, values))
        except (ValueError, _Incomplete):
            if allow_partial and len(records) >= 1000:
                return records, offset
            raise
        if offset >= end:
            break
    return records, offset


def _cjk_ratio(values):
    text = ''.join(values)
    if not text:
        return 0.0
    cjk = sum(1 for character in text if '\u3400' <= character <= '\u9fff')
    return cjk / len(text)


def _language_matches(records, language):
    sample = []
    for _record_id, values in records[:32]:
        sample.extend(values[:2])
    ratio = _cjk_ratio(sample)
    return ratio >= 0.5 if language == 'zh' else ratio <= 0.02


def _overlap(records, requested):
    if not requested:
        return 1.0
    return len({record_id for record_id, _ in records} & requested) / len(requested)


def _display(values,language):
    """English keeps the full name; Chinese uses the shorter in-game name."""
    order=(1,0)if language=='zh'else(0,1)
    for index in order:
        if index<len(values)and values[index].strip():
            return values[index]
    return values[0]if values else ''


def _classify(stream, start, end, competition_ids, nation_ids):
    """Every name table shape that parses inside one block, with its overlap."""
    count = _u32(stream, start + 8)
    results = []
    for language, shapes in TABLE_SHAPES.items():
        for kind, shape in shapes.items():
            low, high = COUNT_RANGES[kind]
            if not low <= count <= high:
                continue
            try:
                head, _ = _records(stream, start, end, shape, min(count, 32))
            except (ValueError, _Incomplete):
                continue
            if not _language_matches(head, language):
                continue
            partial = language == 'zh' and kind == 'competitions'
            try:
                records, offset = _records(stream, start, end, shape, count, allow_partial=partial)
            except (ValueError, _Incomplete):
                continue
            complete = offset == end
            if not complete and not (partial and len(records) >= 1000):
                continue
            requested = nation_ids if kind == 'nations' else competition_ids
            overlap = _overlap(records, requested)
            if overlap < MIN_OVERLAP_RATIO:
                continue
            results.append({'language': language, 'kind': kind, 'records': records,
                            'complete': complete, 'overlap': overlap})
    return results


def _blocks(stream):
    positions = []
    offset = 0
    while True:
        found = stream.find(BLOCK_MAGIC, offset)
        if found < 0:
            break
        positions.append(found)
        offset = found + 1
    blocks = [(position, positions[index + 1]) for index, position in enumerate(positions[:-1])]
    if positions:
        blocks.append((positions[-1], len(stream)))
    return blocks


def _select(candidates):
    best = {}
    for candidate in candidates:
        key = (candidate['kind'], candidate['language'])
        score = (candidate['complete'], candidate['overlap'], len(candidate['records']))
        previous = best.get(key)
        if previous is None or score > previous[0]:
            best[key] = (score, candidate)
    return {key: value[1] for key, value in best.items()}


def _maps(chosen, competition_ids, nation_ids):
    rows = {}
    for (kind, language), candidate in chosen.items():
        rows.setdefault(kind, {}).update({record_id: _display(values, language)
            for record_id, values in candidate['records']})
    competitions = {key: value for key, value in rows.get('competitions', {}).items() if key in competition_ids}
    nations = {key: value for key, value in rows.get('nations', {}).items() if key in nation_ids}
    return competitions, nations


def _scan(stream, competition_ids, nation_ids, language):
    chosen = {}
    for start, end in _blocks(stream):
        for candidate in _classify(stream, start, end, competition_ids, nation_ids):
            key = (candidate['kind'], candidate['language'])
            score = (candidate['complete'], candidate['overlap'], len(candidate['records']))
            if key not in chosen or score > chosen[key][0]:
                chosen[key] = (score, candidate)
        have_en = ('nations', 'en') in chosen and ('competitions', 'en') in chosen
        have_target = language == 'en' or (('nations', language) in chosen and ('competitions', language) in chosen)
        if have_en and have_target:
            break
    return {key: value[1] for key, value in chosen.items()}


def parse_name_tables(stream, competition_ids, nation_ids, language='en'):
    """Read nation and competition names from a decompressed language database.

    Raises:
        ValueError: The stream holds no table whose ids overlap the save's
            database ids.
    """
    competition_ids = _ids(competition_ids)
    nation_ids = _ids(nation_ids)
    if not competition_ids and not nation_ids:
        return {'competitions': {}, 'nations': {}, 'language': language, 'detail': '未请求名称'}
    chosen = _scan(stream, competition_ids, nation_ids, language)
    if not chosen:
        raise ValueError('名称表与存档 database_id 无重叠')
    fallback_competitions, fallback_nations = _maps(
        {key: value for key, value in chosen.items() if key[1] == 'en'}, competition_ids, nation_ids)
    target_competitions, target_nations = _maps(
        {key: value for key, value in chosen.items() if key[1] == language}, competition_ids, nation_ids)
    competitions = {**fallback_competitions, **target_competitions}
    nations = {**fallback_nations, **target_nations}
    used = language if target_competitions or target_nations else 'en'
    required = set(competition_ids) if competition_ids else set(nation_ids)
    covered = set(competitions) if competition_ids else set(nations)
    if not covered:
        raise ValueError('名称表未覆盖存档 database_id')
    return {'competitions': competitions, 'nations': nations, 'language': used,
            'detail': f'覆盖 {len(covered)}/{len(required)} 项'}


def _decompress_frames(raw, limit):
    zstd = _zstd()
    view = memoryview(raw)
    chunks = []
    total = 0
    offset = 0
    while total < limit:
        offset = raw.find(FRAME_MAGIC, offset)
        if offset < 0:
            break
        try:
            size = zstd.get_frame_size(view[offset:])
            if size <= 0 or offset + size > len(raw):
                raise ValueError('invalid frame size')
            data = zstd.ZstdDecompressor().decompress(view[offset:offset + size], max_length=limit - total)
        except Exception:
            offset += 1
            continue
        chunks.append(data)
        total += len(data)
        offset += size
    return b''.join(chunks)


def _lang_db_path(game_root):
    if not game_root:
        return None
    database = Path(game_root) / 'shared/data/database/db'
    try:
        folders = list(database.iterdir())
    except OSError:
        return None
    candidates = []
    for folder in folders:
        try:
            version = int(folder.name)
        except ValueError:
            continue
        path = folder / (folder.name + '_fm') / 'lang_db.dat'
        if path.is_file():
            candidates.append((version, path))
    return max(candidates)[1] if candidates else None


def _file_digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _cache_key(digest, competition_ids, nation_ids, language):
    selection = json.dumps([language, sorted(competition_ids), sorted(nation_ids)], separators=(',', ':'))
    return f"{digest[:16]}-{hashlib.sha256(selection.encode('utf8')).hexdigest()[:16]}.json"


def _cache_directory(cache_root):
    root = cache_root if cache_root is not None else os.environ.get('FM27_DESKTOP_DATA')
    return Path(root) / CACHE_DIRECTORY if root else None


def _int_map(value):
    if not isinstance(value, dict):
        return None
    result = {}
    for key, name in value.items():
        if not isinstance(name, str):
            return None
        try:
            result[int(key)] = name
        except (TypeError, ValueError):
            return None
    return result


def _read_cache(path, language):
    try:
        value = json.loads(path.read_text(encoding='utf8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get('profile') != CACHE_PROFILE or value.get('source') != 'game_db':
        return None
    if value.get('requested_language') != language:
        return None
    competitions = _int_map(value.get('competitions'))
    nations = _int_map(value.get('nations'))
    if competitions is None or nations is None:
        return None
    return {'competitions': competitions, 'nations': nations, 'source': 'game_db',
            'detail': str(value.get('detail') or ''), 'language': value.get('language')}


def _write_cache(path, value, language):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'profile': CACHE_PROFILE, 'requested_language': language, **value}, ensure_ascii=False), encoding='utf8')
    for attempt in range(21):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 20:
                raise
            time.sleep(.025)


def _finish(path, value, cache, language):
    value['source'] = 'game_db'
    value['detail'] = f'FM27 {path.parent.parent.name}/lang_db.dat · {value.get("detail") or ""}'
    if cache is not None:
        try:
            _write_cache(cache, value, language)
        except OSError:
            pass
    return value


def resolve(game_root, competition_database_ids, nation_database_ids, cache_root=None, language='en'):
    """Return the names of the requested database ids, or empty maps when unavailable.

    cache_root is the desktop data root (FM27_DESKTOP_DATA by default); results are
    cached per language and requested id set. Missing entries fall back to English.
    """
    competition_ids = _ids(competition_database_ids)
    nation_ids = _ids(nation_database_ids)
    language = 'zh' if str(language).lower().startswith('zh') else 'en'
    try:
        path = _lang_db_path(game_root)
        if path is None:
            return _unavailable('未找到 FM27 游戏安装数据库 lang_db.dat')
        digest = _file_digest(path)
        directory = _cache_directory(cache_root)
        cache = directory / _cache_key(digest, competition_ids, nation_ids, language) if directory else None
        if cache is not None:
            cached = _read_cache(cache, language)
            if cached is not None:
                return cached
        raw = path.read_bytes()
        fallback = None
        for limit in CHECKPOINTS[language]:
            stream = _decompress_frames(raw, limit)
            try:
                value = parse_name_tables(stream, competition_ids, nation_ids, language)
            except ValueError:
                continue
            if value['language'] == language:
                return _finish(path, value, cache, language)
            fallback = fallback or value
        if fallback is not None:
            return _finish(path, fallback, cache, language)
        return _unavailable('名称表未在解压上限内定位')
    except Exception as error:
        return _unavailable(str(error) or error.__class__.__name__)
