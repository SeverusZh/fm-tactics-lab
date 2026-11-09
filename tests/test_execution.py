import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from desktop_execution import verify_execution_player, verify_execution_probe

POLICY = {'understanding': 70, 'buy_in': 65, 'opposition': 55}


def player(index=0, raw=75, suitability=80, ability=60, overall=66):
    record = bytearray(34)
    record[28:33] = bytes([raw, suitability, overall, 65, 55])
    return dict(slot=index, input_roster_slot=index, input_ca=150,
                record_hex=record.hex(), raw_ability_component=raw,
                role_suitability_component=suitability, ability_contribution=ability,
                overall=overall, buy_in=65, next_match_information=55)


class ExecutionTests(unittest.TestCase):
    def test_role_suitability_changes_automatic_ability_contribution(self):
        self.assertTrue(verify_execution_player(player(), POLICY))
        # Same CA-derived ability, different native two-phase role suitability.
        self.assertTrue(verify_execution_player(player(suitability=40, ability=30, overall=63), POLICY))
        self.assertFalse(verify_execution_player(player(suitability=40), POLICY))

    def test_rejects_stale_policy_and_inconsistent_receipt(self):
        p = player()
        for key in ['ability_contribution', 'overall', 'raw_ability_component', 'role_suitability_component']:
            bad = dict(p); bad[key] += 1
            self.assertFalse(verify_execution_player(bad, POLICY), key)
        self.assertFalse(verify_execution_player(p, {**POLICY, 'understanding': 0}))
        self.assertFalse(verify_execution_player({**p, 'record_hex': '00'}, POLICY))

    def test_probe_checks_actual_lineup_ca_and_roster_identity(self):
        team = {'players': [{'native_profile': {'current_ability': 150}} for _ in range(12)],
                'roster_size': 12, 'lineup': list(range(11))}
        row = dict(side=1, policy=POLICY, build_calls=22, sample_calls=100,
                   players=[player(i) for i in range(11)])
        self.assertTrue(verify_execution_probe(row, POLICY, team, 1))
        for key, value in [('input_ca', 149), ('input_roster_slot', 12), ('input_roster_slot', 1)]:
            bad = copy.deepcopy(row); bad['players'][0][key] = value
            self.assertFalse(verify_execution_probe(bad, POLICY, team, 1))
        bad = copy.deepcopy(row); bad['players'][0].pop('input_roster_slot')
        self.assertFalse(verify_execution_probe(bad, POLICY, team, 1))
        bad = copy.deepcopy(row); bad['sample_calls'] = 0
        self.assertFalse(verify_execution_probe(bad, POLICY, team, 1))
