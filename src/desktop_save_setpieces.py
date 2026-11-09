"""Read the counted FM27 set-piece records belonging to a saved team."""
from bisect import bisect_right
from struct import Struct

from fmsave.readers import tactics


# Within each side the save groups routines by the serialized routine class.
ROUTINE_GROUPS = ((0, 1, 4), (2, 3), (6, 9, 8), (5, 7))
U32 = Struct('<I')


def read_routine(section, start, end, kind, layout):
    cursor = start
    limit = min(end, start + layout.routine_record_max_bytes)

    def take(size):
        nonlocal cursor
        if cursor + size > limit:
            raise ValueError('定位球套路记录超出边界')
        data = section[cursor:cursor + size]
        cursor += size
        return data

    swing = take(1)[0] if kind in (5, 7) else 255
    strategy = take(1)[0] if kind in (2, 3, 5, 6, 7, 8) else 255
    groups = []
    for group in range(8):
        group_id, count = take(2)
        if group_id != group or count > 10:
            raise ValueError('存档定位球的任务组不受支持')
        groups.append(list(take(count)))
    priority = list(take(take(1)[0]))
    backups = [[0] * len(group) for group in groups]
    seen = set()
    for _ in range(take(1)[0]):
        group, slot, value = take(3)
        if group >= len(backups) or slot >= len(backups[group]) or (group, slot) in seen:
            raise ValueError('存档定位球的备用任务索引无效')
        seen.add((group, slot))
        backups[group][slot] = value
    length, = U32.unpack(take(4))
    if not layout.routine_name_length_range[0] <= length <= layout.routine_name_length_range[1]:
        raise ValueError('存档定位球的套路名称超长')
    name = take(length).decode('utf8')
    tail = take(1 + layout.routine_code_bytes)
    frequency = tail[0]
    if (any(ch < ' ' for ch in name) or frequency > 2
            or not tactics._routine_tail_pattern(layout).fullmatch(tail)):
        raise ValueError('存档定位球的套路名称、频率或结尾无效')
    flags = take(1)[0]
    return {'name': name, 'frequency': frequency, 'strategy': strategy, 'swing': swing,
            'groups': groups, 'priority': priority, 'backups': backups, 'opaque_flags': flags}, cursor


def read_team_routines(section, team_id, layout, file_name, starts):
    start = tactics._block_starts(section, [team_id], layout).get(team_id)
    if start is None:
        return {}
    following = bisect_right(starts, start)
    end = starts[following] if following < len(starts) else len(section)
    selection = tactics._read_selection_part(section, start, end, layout, file_name)
    names, complete, area = tactics._read_routines(section, selection.end, end, layout)
    if not complete:
        raise ValueError('未找到完整的存档定位球区')
    if tuple(map(len, ROUTINE_GROUPS)) != layout.routine_group_sizes:
        raise ValueError('不支持此定位球分组格式')
    next_plan, _ = tactics._next_signature(section, area + layout.routine_area_header_bytes, end, layout)
    if next_plan is not None:
        end = next_plan
    cursor = area + layout.routine_area_header_bytes
    checked_names = []
    saved = {}
    for kinds in ROUTINE_GROUPS:
        defaults = {}
        for kind in kinds:
            default, cursor = read_routine(section, cursor, end, kind, layout)
            defaults[kind] = default
            checked_names.append(default['name'] or None)
        for kind in kinds:
            if cursor + U32.size > end:
                raise ValueError('存档定位球的套路数量超出边界')
            count, = U32.unpack_from(section, cursor)
            cursor += U32.size
            if not layout.routine_group_count_range[0] <= count <= layout.routine_group_count_range[1]:
                raise ValueError('存档定位球的套路数量无效')
            variants = []
            for _ in range(count):
                routine, cursor = read_routine(section, cursor, end, kind, layout)
                variants.append(routine)
                checked_names.append(routine['name'] or None)
            default = defaults[kind]
            # Empty names and default copies are present even in saves whose
            # managers never edited their set pieces. Keep every saved variant
            # of a category once the category contains a custom routine.
            if any(row['name'] or any(row[k] != default[k] for k in default if k not in ('name', 'opaque_flags'))
                   for row in variants) or len(variants) > 1:
                saved[str(kind)] = variants
            elif default['name']:
                saved[str(kind)] = [default]
    if tuple(checked_names) != names:
        raise ValueError('存档定位球的套路记录未通过边界核对')
    return saved
