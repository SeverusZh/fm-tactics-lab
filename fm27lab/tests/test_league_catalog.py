"""联赛目录、当前联赛与教练读取测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm27lab.adapters.save_fmsave.league import (
    League,
    read_coaches,
    read_league_catalog,
)

REAL_SAVE = Path("dist/verify/fm27-save.fm")


def fixture(home: int, away: int, day: int, played: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        home_team_slot=0,
        away_team_slot=0,
        home_club_uid=home,
        away_club_uid=away,
        competition_id=7,
        stage_id=257,
        season_start_year=2029,
        date=date(2029, 8, day),
        played=played,
    )


def double_round_robin(clubs: list[int], start_day: int = 1) -> list[SimpleNamespace]:
    rows = []
    day = start_day
    for home in clubs:
        for away in clubs:
            if home == away:
                continue
            rows.append(fixture(home, away, day))
            day += 1
    return rows


def test_current_league_prefers_active_schedule():
    from fm27lab.adapters.save_fmsave.league import _current

    active = League("7:257:2029", 7, 11, 257, 2029, (1, 2, 3), 30, "2029-08-01", "2030-05-01")
    past = League("8:258:2028", 8, 12, 258, 2028, (1, 2, 3, 4), 30, "2028-08-01", "2029-05-01")
    current, ambiguous = _current([past, active], (1,), "2029-12-01")
    assert current is active
    assert ambiguous == []


def test_current_league_reports_ambiguity():
    from fm27lab.adapters.save_fmsave.league import _current

    first = League("7:257:2029", 7, 11, 257, 2029, (1, 2, 3), 30, "2029-08-01", "2030-05-01")
    second = League("9:259:2029", 9, 13, 259, 2029, (1, 2, 4), 30, "2029-08-01", "2030-05-01")
    current, ambiguous = _current([first, second], (1,), "2029-12-01")
    assert current is None
    assert ambiguous == [first, second]


def test_played_opponents_only_counts_managed_fixtures():
    from fm27lab.adapters.save_fmsave.league import _played

    fixtures = [fixture(1, 2, 1, played=True), fixture(3, 4, 2, played=True)]
    assert _played(fixtures, {1}) == {2}


def test_read_league_catalog_rejects_missing_file(tmp_path: Path):
    with pytest.raises(ValueError, match="FM 存档"):
        read_league_catalog(tmp_path / "missing.fm")


@pytest.mark.skipif(not REAL_SAVE.is_file(), reason="需要真实存档样本")
def test_read_league_catalog_on_real_save():
    catalog = read_league_catalog(REAL_SAVE)
    assert catalog.managed == (741,)
    assert catalog.current is not None
    assert len(catalog.opponents) == 19
    assert catalog.current.key in {league.key for league in catalog.leagues}


@pytest.mark.skipif(not REAL_SAVE.is_file(), reason="需要真实存档样本")
def test_read_coaches_on_real_save():
    catalog = read_league_catalog(REAL_SAVE)
    coaches = read_coaches(REAL_SAVE, catalog.opponents)
    assert len(coaches) >= 17
    assert all(coach.selector > 0 for coach in coaches)
    assert all(len(coach.fragment) >= 4096 for coach in coaches)
    assert all(type(coach.primary) is int for coach in coaches)
