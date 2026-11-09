import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import desktop_opponent_scope as scope


def fixture(home,away,date,competition=8,stage=231,season=2026,played=False):
    return {'competition_id':competition,'stage_id':stage,'season_start_year':season,'round':None,
        'home_club_uid':home,'away_club_uid':away,'home_team_slot':0,'away_team_slot':0,
        'date':date,'played':played}


def round_robin(members,competition=8,stage=231,season=2026):
    rows=[]
    for home in members:
        for away in members:
            if home==away:continue
            rows.append(fixture(home,away,'2026-08-%02d'%(1+len(rows)%27),competition,stage,season))
    rows[-1]['date']='2027-05-01'
    return rows


class OpponentScopeTests(unittest.TestCase):
    def test_detects_complete_league_after_last_fixture(self):
        data={'fixtures':round_robin([1,2,3,4]),'date':'2027-05-29'}
        report=scope.identify(data,1)
        self.assertIsNotNone(report['league'])
        self.assertEqual(report['same_league'],{2,3,4})

    def test_detects_complete_league_inside_season(self):
        data={'fixtures':round_robin([1,2,3,4]),'date':'2026-12-01'}
        self.assertEqual(scope.identify(data,1)['same_league'],{2,3,4})

    def test_preseason_prefers_upcoming_members_over_last_season(self):
        old=round_robin([1,2,3,4],stage=231,season=2025)
        for row in old:row['date']='2026-05-01'
        new=round_robin([1,5,6,7],stage=232)
        report=scope.identify({'fixtures':old+new,'date':'2026-07-01'},1)
        self.assertEqual(report['same_league'],{5,6,7})

    def test_distant_old_schedule_is_not_current(self):
        rows=round_robin([1,2,3,4],season=2020)
        for row in rows:row['date']='2020-05-01'
        self.assertIsNone(scope.identify({'fixtures':rows,'date':'2027-07-01'},1)['league'])

    def test_distant_future_schedule_is_not_current(self):
        rows=round_robin([1,2,3,4])
        self.assertIsNone(scope.identify({'fixtures':rows,'date':'2025-01-01'},1)['league'])

    def test_ambiguous_complete_tables_remain_unresolved(self):
        rows=round_robin([1,2,3,4],competition=8,stage=231)+round_robin([1,5,6,7],competition=9,stage=232)
        report=scope.identify({'fixtures':rows,'date':'2027-05-29'},1)
        self.assertIsNone(report['league'])
        self.assertEqual(len(report['ambiguous_leagues']),2)

    def test_incomplete_calendar_is_not_a_league(self):
        rows=[item for item in round_robin([1,2,3,4]) if not(item['home_club_uid']==1 and item['away_club_uid']==2)]
        self.assertIsNone(scope.identify({'fixtures':rows,'date':'2026-12-01'},1)['league'])


if __name__=='__main__':
    unittest.main()
