"""Unit tests for Agent pool pairing across legacy and rotation summaries."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from fm27_agent.mcp import _pool_pairing


def entries():
    return [{'index': 0, 'name': '甲', 'weight': 1, 'probability': 1.0, 'roster': False},
            {'index': 1, 'name': '乙', 'weight': 1, 'probability': 1.0, 'roster': False}]


def pool(mode=None, rounds=None, players=None, draws=None, rows=None):
    value = {'salt': 'job', 'entries': entries() if rows is None else rows,
             'draws': draws if draws is not None else {1: 0, 2: 1}}
    if mode is not None:
        value['mode'] = mode
    if rounds is not None:
        value['rounds'] = rounds
    if players is not None:
        value['players'] = players
    return value


class PoolPairingTests(unittest.TestCase):
    def test_legacy_summary_defaults_match_random_uniform_pool(self):
        comparable, reason, info = _pool_pairing(pool(), pool('random', 1, 'uniform'), [1, 2])
        self.assertTrue(comparable)
        self.assertIsNone(reason)
        self.assertEqual(info['draw_mismatches'], 0)

    def test_unknown_and_pool_are_not_comparable(self):
        comparable, reason, _ = _pool_pairing(None, pool('random', 1, 'uniform'), [1])
        self.assertFalse(comparable)
        self.assertIn('客队战术池', reason)

    def test_mode_and_rounds_must_match(self):
        for candidate in [pool('rotation', 1, 'uniform'), pool('random', 2, 'uniform'),
                          pool('random', 1, 'real')]:
            comparable, reason, _ = _pool_pairing(pool('random', 1, 'uniform'), candidate, [1, 2])
            self.assertFalse(comparable)
            self.assertIn('模式不同', reason)

    def test_rotation_pairing_accepts_identical_round_robin(self):
        rotation = pool('rotation', 2, 'uniform', draws={1: 0, 2: 1, 3: 0, 4: 1})
        comparable, reason, info = _pool_pairing(rotation, rotation, [1, 2, 3, 4])
        self.assertTrue(comparable)
        self.assertIsNone(reason)
        self.assertEqual(info['draw_mismatches'], 0)

    def test_rotation_pairing_rejects_different_assignment(self):
        baseline = pool('rotation', 1, 'uniform', draws={1: 0, 2: 1})
        candidate = pool('rotation', 1, 'uniform', draws={1: 1, 2: 0})
        comparable, reason, info = _pool_pairing(baseline, candidate, [1, 2])
        self.assertFalse(comparable)
        self.assertIn('分配', reason)
        self.assertEqual(info['draw_mismatches'], 2)

    def test_entry_flags_take_part_in_pairing(self):
        baseline = pool('random', 1, 'uniform')
        candidate = pool('random', 1, 'uniform')
        candidate['entries'] = [dict(row) for row in baseline['entries']]
        candidate['entries'][0]['roster'] = True
        comparable, reason, _ = _pool_pairing(baseline, candidate, [1, 2])
        self.assertFalse(comparable)
        self.assertIn('条目', reason)


class _FakeClient:
    def __init__(self, recorded):
        self.recorded = recorded

    def job_export(self, job_id):
        return {'provenance': {'pool': self.recorded}}


class _BrokenExportClient:
    def job_export(self, job_id):
        from fm27_agent.client import AgentError
        raise AgentError('http_error', '导出失败')


class PoolDrawSourceTests(unittest.TestCase):
    def test_job_export_supplies_mode_and_roster_to_pairing(self):
        from fm27_agent.mcp import McpServer

        entries = [{'index': 0, 'name': '甲', 'weight': 1, 'probability': 1.0, 'roster': True},
                   {'index': 1, 'name': '乙', 'weight': 1, 'probability': 1.0, 'roster': True}]
        job = {'id': 'job1', 'tactic_pool': {'enabled': True, 'salt': 'job1', 'entries': entries}}
        server = McpServer(base_url='http://127.0.0.1:1', token='t')
        recorded = {'salt': 'job1', 'mode': 'rotation', 'rounds': 2, 'players': 'real',
                    'entries': entries, 'draws': {'1': 0, '2': 1, '3': 0, '4': 1}}
        value = server._pool_draws(_FakeClient(recorded), job)
        self.assertEqual((value['mode'], value['rounds'], value['players']), ('rotation', 2, 'real'))
        self.assertEqual(value['entries'][0][3], True)
        self.assertEqual(value['draws'], {1: 0, 2: 1, 3: 0, 4: 1})
        uniform = dict(recorded, players='uniform')
        self.assertFalse(_pool_pairing(value, server._pool_draws(_FakeClient(uniform), job), [1])[0])

    def test_export_failure_falls_back_to_job_summary(self):
        from fm27_agent.mcp import McpServer

        entries = [{'index': 0, 'name': '甲', 'weight': 1, 'probability': 1.0, 'roster': True}]
        job = {'id': 'job1', 'tactic_pool': {'enabled': True, 'salt': 'job1',
                                             'mode': 'rotation', 'rounds': 2,
                                             'players': 'real', 'entries': entries}}
        server = McpServer(base_url='http://127.0.0.1:1', token='t')
        value = server._pool_draws(_BrokenExportClient(), job)
        self.assertEqual((value['mode'], value['rounds'], value['players']),
                         ('rotation', 2, 'real'))
        self.assertEqual(value['draws'], {})
        self.assertEqual(value['entries'][0][3], True)

    def test_summary_fallback_keeps_legacy_random_defaults(self):
        from fm27_agent.mcp import McpServer

        entries = [{'index': 0, 'name': '甲', 'weight': 1, 'probability': 1.0}]
        job = {'id': 'job1', 'tactic_pool': {'enabled': True, 'salt': 'job1', 'entries': entries}}
        server = McpServer(base_url='http://127.0.0.1:1', token='t')
        value = server._pool_draws(_FakeClient({'draws': {'1': 0}, 'entries': entries}), job)
        self.assertEqual((value['mode'], value['rounds'], value['players']), ('random', 1, 'uniform'))
        self.assertFalse(value['entries'][0][3])


if __name__ == '__main__':
    unittest.main()
