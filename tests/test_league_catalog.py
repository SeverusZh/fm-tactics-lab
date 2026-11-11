import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import desktop_save_worker


def fixture(home,away,competition=1,stage=10,season=2026,date='2026-08-01',home_slot=0,away_slot=0):
    return {'competition_id':competition,'stage_id':stage,'season_start_year':season,
            'home_club_uid':home,'away_club_uid':away,'date':date,
            'home_team_slot':home_slot,'away_team_slot':away_slot}


def full_round_robin(uids,cycles=1,date='2026-08-01',**options):
    return [fixture(home,away,date=date,**options)for _ in range(cycles)for home in uids for away in uids if home!=away]


def single_direction(uids,date='2026-08-01',**options):
    return [fixture(uids[i],uids[j],date=date,**options)for i in range(len(uids))for j in range(i+1,len(uids))]


def registry(uids):
    return [{'uid':uid,'unique_id':1000+uid,'name':f'Club {uid}','short_name':f'C{uid}','nation_id':7,
             'teams':[{'team_id':uid*10,'slot':0},{'team_id':uid*10+1,'slot':1}]}for uid in uids]


class LeagueCatalogTests(unittest.TestCase):
    def test_complete_double_round_robin_is_included(self):
        uids=list(range(1,9))
        result=desktop_save_worker.league_catalog(full_round_robin(uids),registry(uids))
        self.assertEqual(len(result['leagues']),1)
        self.assertEqual(result['leagues'][0],{'key':'1:10:2026','competition_id':1,'stage_id':10,'season':2026,
            'club_uids':uids,'fixture_count':56,'first_date':'2026-08-01','last_date':'2026-08-01','complete':True})

    def test_triple_round_robin_is_included(self):
        uids=list(range(1,7))
        ordered=[(home,away)for home in uids for away in uids if home!=away]
        rows=full_round_robin(uids)+[fixture(home,away,date='2026-09-01')for home,away in ordered[::2]]
        self.assertEqual(len(rows),45)
        result=desktop_save_worker.league_catalog(rows,registry(uids))
        self.assertEqual([entry['fixture_count']for entry in result['leagues']],[45])

    def test_split_league_with_extra_group_rounds_is_included(self):
        uids=list(range(1,13))
        rows=(full_round_robin(uids)+full_round_robin(list(range(1,7)),date='2027-03-01')
              +full_round_robin(list(range(7,13)),date='2027-03-01'))
        result=desktop_save_worker.league_catalog(rows,registry(uids))
        self.assertEqual([(entry['key'],entry['fixture_count'])for entry in result['leagues']],[('1:10:2026',192)])
        self.assertEqual(result['leagues'][0]['club_uids'],uids)

    def test_cup_group_without_every_ordered_pair_is_excluded(self):
        uids=list(range(1,9))
        result=desktop_save_worker.league_catalog(single_direction(uids),registry(uids))
        self.assertEqual(result['leagues'],[])
        self.assertEqual(result['league_clubs'],{})

    def test_member_bounds_are_inclusive(self):
        cases=[(5,[]),(6,['1:10:2026']),(60,['1:10:2026']),(61,[])]
        for size,expected in cases:
            with self.subTest(size=size):
                uids=list(range(1,size+1))
                result=desktop_save_worker.league_catalog(full_round_robin(uids),registry(uids))
                self.assertEqual([entry['key']for entry in result['leagues']],expected)

    def test_fixture_count_upper_bound_is_inclusive(self):
        uids=list(range(1,7))
        base=full_round_robin(uids)
        inside=base+[fixture(1,2,date='2026-09-01')]*30
        outside=base+[fixture(1,2,date='2026-09-01')]*31
        self.assertEqual([entry['fixture_count']for entry in desktop_save_worker.league_catalog(inside,registry(uids))['leagues']],[60])
        self.assertEqual(desktop_save_worker.league_catalog(outside,registry(uids))['leagues'],[])

    def test_only_first_teams_are_counted(self):
        uids=list(range(1,7))
        rows=full_round_robin(uids)+full_round_robin(uids,home_slot=1)+full_round_robin(uids,away_slot=1)
        result=desktop_save_worker.league_catalog(rows,registry(uids))
        self.assertEqual([entry['fixture_count']for entry in result['leagues']],[30])

    def test_one_entry_per_competition_prefers_active_then_upcoming(self):
        uids=list(range(1,7))
        finished=[fixture(home,away,season=2026,date='2026-09-01')for home in uids for away in uids if home!=away]
        upcoming=[fixture(home,away,season=2027,date='2027-09-01')for home in uids for away in uids if home!=away]
        active=[fixture(home,away,season=2028,date='2028-09-01')for home in uids for away in uids if home!=away]
        result=desktop_save_worker.league_catalog(finished+upcoming,registry(uids),(),'2027-07-08')
        self.assertEqual([entry['season']for entry in result['leagues']],[2027])
        result=desktop_save_worker.league_catalog(finished+upcoming,registry(uids),(),'2026-09-01')
        self.assertEqual([entry['season']for entry in result['leagues']],[2026])
        active=[fixture(home,away,season=2028,date='2028-09-01')for home in uids for away in uids if home!=away]
        result=desktop_save_worker.league_catalog(upcoming+active,registry(uids),(),'2028-09-01')
        self.assertEqual([entry['season']for entry in result['leagues']],[2028])

    def test_most_recent_finished_season_is_used_without_one_upcoming(self):
        uids=list(range(1,7))
        older=[fixture(home,away,season=2025,date='2025-09-01')for home in uids for away in uids if home!=away]
        recent=[fixture(home,away,season=2026,date='2026-09-01')for home in uids for away in uids if home!=away]
        result=desktop_save_worker.league_catalog(older+recent,registry(uids),(),'2027-07-08')
        self.assertEqual([entry['season']for entry in result['leagues']],[2026])

    def test_league_clubs_and_competition_database_ids(self):
        uids=list(range(1,7))
        competitions=[{'id':1,'database_id':1100},{'id':2,'database_id':None}]
        rows=full_round_robin(uids)+full_round_robin(list(range(11,17)),competition=2)
        result=desktop_save_worker.league_catalog(rows,registry(uids+list(range(11,17))),competitions)
        self.assertEqual(result['competitions'],{'1':1100,'2':None})
        self.assertEqual(set(result['league_clubs']),{str(uid)for uid in uids+list(range(11,17))})
        self.assertEqual(result['league_clubs']['3'],{'name':'Club 3','short_name':'C3','nation_id':7,
            'first_team_id':30,'club_unique_id':1003})

    def test_entries_are_sorted_by_key(self):
        uids=list(range(1,7))
        rows=full_round_robin(uids,competition=10)+full_round_robin(uids,competition=2)
        result=desktop_save_worker.league_catalog(rows,registry(uids))
        self.assertEqual([entry['key']for entry in result['leagues']],['10:10:2026','2:10:2026'])

    def test_fixtures_without_competition_or_stage_are_ignored(self):
        uids=list(range(1,7))
        result=desktop_save_worker.league_catalog(full_round_robin(uids,competition=None),registry(uids))
        self.assertEqual(result['leagues'],[])
        result=desktop_save_worker.league_catalog(full_round_robin(uids,stage=None),registry(uids))
        self.assertEqual(result['leagues'],[])

    def test_fixtures_and_clubs_read_through_attributes(self):
        uids=list(range(1,7))
        rows=[SimpleNamespace(**row)for row in full_round_robin(uids)]
        clubs=[SimpleNamespace(**club)for club in registry(uids)]
        result=desktop_save_worker.league_catalog(rows,clubs)
        self.assertEqual([entry['fixture_count']for entry in result['leagues']],[30])
        self.assertEqual(result['league_clubs']['1']['first_team_id'],10)

    def test_empty_calendar_returns_empty_catalog(self):
        self.assertEqual(desktop_save_worker.league_catalog([],[]),
            {'leagues':[],'league_clubs':{},'competitions':{}})


if __name__=='__main__':
    unittest.main()
