"""Check native tactical-execution receipts against the actual match inputs."""
import struct


def verify_execution_player(player, policy):
    try:
        record = bytes.fromhex(player['record_hex'])
        if len(record) != 34:
            return False
        if isinstance(policy, int):
            return record[:33] == bytes([policy]) * 33
        raw, suitability = record[28:30]
        if (raw > 100 or suitability > 100
                or player['raw_ability_component'] != raw
                or player['role_suitability_component'] != suitability):
            return False
        ability = policy.get('ability')
        if ability is None:
            # Preserve the original builder's single-precision operation order.
            def f32(value):
                return struct.unpack('<f', struct.pack('<f', value))[0]
            factor = f32(suitability * 2 / 100)
            scaled = f32(f32(raw * 4 * factor) * 100)
            ability = int(f32(f32(scaled / 800) + 0.5))
        overall = (50 * policy['understanding'] + 25 * policy['buy_in']
                   + 15 * policy['opposition'] + 10 * ability + 50) // 100
        return (player['ability_contribution'] == ability
                and player['overall'] == overall
                and player['buy_in'] == policy['buy_in']
                and player['next_match_information'] == policy['opposition']
                and record[30:33] == bytes([overall, policy['buy_in'], policy['opposition']]))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def verify_execution_probe(row, policy, team, side):
    if (row.get('side') != side or row.get('policy') != policy
            or row.get('build_calls', 0) <= 0 or row.get('sample_calls', 0) <= 0
            or not row.get('players')):
        return False
    seen = set()
    players = team['players']
    for player in row['players']:
        if not verify_execution_player(player, policy):
            return False
        index = player.get('input_roster_slot')
        if index is None:
            # Unused substitutes may never enter the original builder.
            if player.get('slot', 0) < 11:
                return False
            continue
        if type(index) is not int or not 0 <= index < team.get('roster_size', len(players)) or index in seen:
            return False
        seen.add(index)
        ca = player.get('input_ca')
        if type(ca) is not int or not 0 <= ca <= 200:
            return False
        expected = players[index].get('native_profile', {}).get('current_ability')
        if expected is not None and expected != ca:
            return False
    return set(team['lineup']).issubset(seen)


def execution_receipts(rows, scenario):
    if 'experimental_execution' not in scenario:
        return None
    versions = [r for r in rows if r.get('event') == 'experimental_engine_version']
    probes = sorted((r for r in rows if r.get('event') == 'native_execution_probe'
                     and r.get('stage') == 'finished'), key=lambda r: r['side'])
    if len(versions) != 1 or versions[0]['after'] != 0x1b000000 or len(probes) != 2:
        raise ValueError('缺少原生实验执行力回执')
    for side, row in enumerate(probes):
        if not verify_execution_probe(row, scenario['experimental_execution'][side],
                                      scenario['teams'][side], side):
            raise ValueError('实验执行力、球员身份或能力贡献未通过原生采样与回读核对')
    return probes
