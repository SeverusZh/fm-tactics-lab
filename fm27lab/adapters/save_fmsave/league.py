"""联赛目录、当前联赛与一线队主教练偏好读取。

只接受完整双循环且主客各一场的联赛阶段；单循环、小组赛与跨阶段赛制不进入目录。
"""

from __future__ import annotations

import struct
import threading
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fm27lab.adapters.save_fmsave.reader import (
    SAVE_CHANGED_ERROR,
    SAVE_INVALID_ERROR,
    _load_fmsave,
    _reader_error,
)

LEAGUE_MIN_MEMBERS = 6
LEAGUE_MAX_MEMBERS = 60
PRESEASON_WINDOW = timedelta(days=90)
MANAGER_JOB = 16
PROFILE_BYTES = 52
FRAGMENT_BYTES = 4096
MAX_FIXTURES = 200_000
COACH_LOCK = threading.Lock()

__all__ = [
    "Club",
    "Coach",
    "League",
    "LeagueCatalog",
    "read_coaches",
    "read_league_catalog",
]


@dataclass(frozen=True, slots=True)
class Club:
    uid: int
    unique_id: int | None
    name: str
    short_name: str | None
    nation_id: int | None
    first_team_id: int | None


@dataclass(frozen=True, slots=True)
class League:
    key: str
    competition_id: int
    database_id: int | None
    stage_id: int
    season: int | None
    club_uids: tuple[int, ...]
    fixture_count: int
    first_date: str | None
    last_date: str | None

    def summary(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "competition_id": self.competition_id,
            "database_id": self.database_id,
            "stage_id": self.stage_id,
            "season": self.season,
            "club_count": len(self.club_uids),
            "fixture_count": self.fixture_count,
            "first_date": self.first_date,
            "last_date": self.last_date,
        }


@dataclass(frozen=True, slots=True)
class LeagueCatalog:
    leagues: tuple[League, ...]
    clubs: Mapping[int, Club]
    managed: tuple[int, ...]
    current: League | None
    ambiguous: tuple[League, ...]
    played: frozenset[int]
    save_date: str

    @property
    def opponents(self) -> tuple[int, ...]:
        if self.current is None:
            return ()
        return tuple(uid for uid in self.current.club_uids if uid not in self.managed)


@dataclass(frozen=True, slots=True)
class Coach:
    club_uid: int
    uid: int
    unique_id: int | None
    name: str
    team_id: int | None
    team_slot: int | None
    selector: int
    profile_hex: str
    codes_hex: str
    fragment: bytes

    @property
    def primary(self) -> int | None:
        return int(self.codes_hex[0:2], 16) if len(self.codes_hex) >= 2 else None

    @property
    def secondary(self) -> int | None:
        return int(self.codes_hex[2:4], 16) if len(self.codes_hex) >= 4 else None


def _value(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)[:10]


def _signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError as error:
        raise ValueError(f"{SAVE_INVALID_ERROR}：{error}") from error
    return (stat.st_size, stat.st_mtime_ns)


def read_league_catalog(path: Path) -> LeagueCatalog:
    """读取存档赛程，确定完整联赛、当前赛季与对手范围。"""
    target = Path(path)
    fmsave = _load_fmsave()
    before = _signature(target)
    try:
        with fmsave.open(target) as save:
            info = save.info
            save_date = _date_text(info.game_date) or ""
            managed = tuple(dict.fromkeys(int(row.club_uid) for row in save.managed_clubs()))
            clubs = {
                int(club.uid): Club(
                    uid=int(club.uid),
                    unique_id=_integer(club, "unique_id"),
                    name=str(_value(club, "name") or club.uid),
                    short_name=_text(_value(club, "short_name")),
                    nation_id=_integer(club, "nation_id"),
                    first_team_id=_first_team_id(club),
                )
                for club in save.clubs()
            }
            competitions = {int(row.id): _integer(row, "database_id") for row in save.competitions()}
            fixtures = tuple(save.fixtures())
    except ValueError:
        raise
    except Exception as error:
        raise _reader_error(fmsave, error) from error
    if _signature(target) != before:
        raise ValueError(SAVE_CHANGED_ERROR)
    if len(fixtures) > MAX_FIXTURES:
        raise ValueError("存档赛程超出当前读取上限")
    leagues = _leagues(fixtures, competitions, save_date)
    current, ambiguous = _current(leagues, managed, save_date)
    played = _played(fixtures, set(managed))
    return LeagueCatalog(
        leagues=tuple(leagues),
        clubs=clubs,
        managed=managed,
        current=current,
        ambiguous=tuple(ambiguous),
        played=frozenset(played),
        save_date=save_date,
    )


def _integer(row: Any, name: str) -> int | None:
    value = _value(row, name)
    return value if type(value) is int else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _first_team_id(club: Any) -> int | None:
    teams = _value(club, "teams") or ()
    for team in teams:
        if _value(team, "slot") == 0:
            identifier = _value(team, "team_id")
            if type(identifier) is int:
                return identifier
    return None


def _leagues(
    fixtures: Iterable[Any],
    competitions: Mapping[int, int | None],
    save_date: str,
) -> list[League]:
    groups: dict[tuple[int, int, int | None], list[Any]] = defaultdict(list)
    for fixture in fixtures:
        if _value(fixture, "home_team_slot") != 0 or _value(fixture, "away_team_slot") != 0:
            continue
        home = _value(fixture, "home_club_uid")
        away = _value(fixture, "away_club_uid")
        competition = _value(fixture, "competition_id")
        stage = _value(fixture, "stage_id")
        if type(home) is not int or type(away) is not int or home == away:
            continue
        if type(competition) is not int or type(stage) is not int:
            continue
        groups[(competition, stage, _value(fixture, "season_start_year"))].append(fixture)
    candidates: dict[int, list[League]] = defaultdict(list)
    for (competition, stage, season), rows in groups.items():
        members = {_value(row, "home_club_uid") for row in rows} | {
            _value(row, "away_club_uid") for row in rows
        }
        count = len(members)
        if not LEAGUE_MIN_MEMBERS <= count <= LEAGUE_MAX_MEMBERS:
            continue
        if len(rows) > count * (count - 1) * 2:
            continue
        pairs = {(_value(row, "home_club_uid"), _value(row, "away_club_uid")) for row in rows}
        if len(pairs) != count * (count - 1):
            continue
        dates = sorted(
            text for row in rows if (text := _date_text(_value(row, "date"))) is not None
        )
        candidates[competition].append(
            League(
                key=f"{competition}:{stage}:{season}",
                competition_id=competition,
                database_id=competitions.get(competition),
                stage_id=stage,
                season=season if type(season) is int else None,
                club_uids=tuple(sorted(members)),
                fixture_count=len(rows),
                first_date=dates[0] if dates else None,
                last_date=dates[-1] if dates else None,
            )
        )
    chosen = [
        min(entries, key=lambda league: _priority(league, save_date))
        for entries in candidates.values()
    ]
    return sorted(chosen, key=lambda league: league.key)


def _priority(league: League, save_date: str) -> tuple[int, int, int, int, str]:
    first, last = league.first_date or "", league.last_date or ""
    active = bool(save_date and first and last and first <= save_date <= last)
    upcoming = bool(save_date and first and first > save_date)
    if active:
        window, recency = 0, 0
    elif upcoming:
        window, recency = 1, int(first.replace("-", "") or 0)
    else:
        window, recency = 2, -int(last.replace("-", "") or 0)
    return (window, recency, -league.fixture_count, -len(league.club_uids), league.key)


def _current(
    leagues: Iterable[League],
    managed: tuple[int, ...],
    save_date: str,
) -> tuple[League | None, list[League]]:
    if not managed or not save_date:
        return None, []
    today = date.fromisoformat(save_date)
    candidates: list[League] = []
    for league in leagues:
        if not any(uid in league.club_uids for uid in managed):
            continue
        if league.first_date is None or league.last_date is None:
            continue
        first, last = date.fromisoformat(league.first_date), date.fromisoformat(league.last_date)
        if first <= today <= last:
            candidates.append(league)
        elif timedelta(0) < first - today <= PRESEASON_WINDOW:
            candidates.append(league)
        elif timedelta(0) < today - last <= PRESEASON_WINDOW:
            candidates.append(league)
    candidates.sort(key=lambda item: _priority(item, save_date))
    if len(candidates) == 1:
        return candidates[0], []
    return None, candidates


def _played(fixtures: Iterable[Any], managed: set[int]) -> set[int]:
    opponents: set[int] = set()
    for fixture in fixtures:
        if _value(fixture, "home_team_slot") != 0 or _value(fixture, "away_team_slot") != 0:
            continue
        home, away = _value(fixture, "home_club_uid"), _value(fixture, "away_club_uid")
        if type(home) is not int or type(away) is not int or home == away:
            continue
        if _value(fixture, "played") and (home in managed or away in managed):
            opponents.add(away if home in managed else home)
    return opponents


def read_coaches(path: Path, club_uids: Iterable[int]) -> tuple[Coach, ...]:
    """读取所选俱乐部的一线队主教练与偏好片段；片段只用于原生读回核对。"""
    wanted = {int(uid) for uid in club_uids}
    if not wanted:
        return ()
    target = Path(path)
    fmsave = _load_fmsave()
    before = _signature(target)
    with COACH_LOCK:
        try:
            save = fmsave.open(target)
        except ValueError:
            raise
        except Exception as error:
            raise _reader_error(fmsave, error) from error
        try:
            with save:
                result = _coaches(save, wanted)
        except ValueError:
            raise
        except Exception as error:
            raise _reader_error(fmsave, error) from error
    if _signature(target) != before:
        raise ValueError(SAVE_CHANGED_ERROR)
    return result


def _coaches(save: Any, wanted: set[int]) -> tuple[Coach, ...]:
    import fmsave.readers.staff as reader

    captured: dict[int, dict[str, Any]] = {}
    selectors: dict[int, int] = {}
    by_uid: dict[int, dict[str, Any]] = {}
    original_ability = reader._read_ability_block
    original_person = reader._PersonObject
    state = threading.local()
    db: Any = b""

    def capture(database: Any, header: int, layout: Any) -> Any:
        result = original_ability(database, header, layout)
        if not getattr(state, "active", False):
            return result
        if result[0] is not None and result[1] and result[3]:
            base = (
                header
                + layout.ability_base_offset
                + layout.entry_bytes * database[header + layout.entry_count_offset]
            )
            start = base + layout.preferences_offset
            end = base + layout.block_40_offset + layout.block_40_count
            if end - start == PROFILE_BYTES:
                captured[header] = {
                    "profile_hex": bytes(database[start:end]).hex(),
                    "codes_hex": bytes(
                        database[
                            base + layout.codes_offset : base + layout.codes_offset + layout.code_count
                        ]
                    ).hex(),
                    "fragment": bytes(database[header + 13 : end + FRAGMENT_BYTES]),
                }
        return result

    def person(*args: Any, **kwargs: Any) -> Any:
        obj = original_person(*args, **kwargs)
        if not getattr(state, "active", False):
            return obj
        selectors[obj.uid] = struct.unpack_from("<I", db, obj.header)[0] + 1
        if obj.header in captured:
            by_uid[obj.uid] = captured[obj.header]
        return obj

    reader._read_ability_block = capture
    reader._PersonObject = person
    try:
        with save._context.section("game_db") as database:
            db = database
            state.active = True
            try:
                staff = list(save.staff())
            finally:
                state.active = False
    finally:
        reader._read_ability_block = original_ability
        reader._PersonObject = original_person
    chosen: dict[int, Coach] = {}
    for row in staff:
        club_uid = _integer(row, "club_uid")
        if club_uid not in wanted or _value(row, "is_human_manager"):
            continue
        job = _value(row, "job")
        if job is None or getattr(job, "raw", None) != MANAGER_JOB:
            continue
        if not _value(row, "has_contract"):
            continue
        if isinstance(_value(row, "team_slot"), int) and _value(row, "team_slot") != 0:
            continue
        uid = _integer(row, "uid")
        info = by_uid.get(uid) if uid is not None else None
        selector = selectors.get(uid) if uid is not None else None
        if info is None or selector is None:
            continue
        coach = Coach(
            club_uid=club_uid,
            uid=uid,
            unique_id=_integer(row, "unique_id"),
            name=str(_value(row, "name") or uid),
            team_id=_integer(row, "team_id"),
            team_slot=_integer(row, "team_slot"),
            selector=selector,
            profile_hex=str(info["profile_hex"]),
            codes_hex=str(info["codes_hex"]),
            fragment=bytes(info["fragment"]),
        )
        current = chosen.get(club_uid)
        if current is None or _coach_rank(coach) < _coach_rank(current):
            chosen[club_uid] = coach
    return tuple(chosen[uid] for uid in sorted(chosen))


def _coach_rank(coach: Coach) -> tuple[int, int]:
    return (0 if coach.team_slot == 0 else 1, coach.uid)
