"""Save reader port and fmsave adapter tests."""

from __future__ import annotations

import sys
import tomllib
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import fmsave
import pytest

from fm27lab.adapters.save_fmsave.reader import FmsaveReader
from fm27lab.ports.save_reader import SaveReader

POSITION_FIELDS = (
    "gk",
    "sw",
    "dl",
    "dc",
    "dr",
    "dm",
    "ml",
    "mc",
    "mr",
    "aml",
    "amc",
    "amr",
    "stc",
    "wbl",
    "wbr",
)
POSITION_NAMES = (
    "GK",
    "SW",
    "DL",
    "DC",
    "DR",
    "DM",
    "ML",
    "MC",
    "MR",
    "AML",
    "AMC",
    "AMR",
    "ST",
    "WBL",
    "WBR",
)
RAW_ATTRIBUTE_FIELDS = (
    "crossing",
    "dribbling",
    "finishing",
    "heading",
    "long_shots",
    "marking",
    "off_the_ball",
    "passing",
    "penalty_taking",
    "tackling",
    "vision",
    "handling",
    "aerial_reach",
    "command_of_area",
    "communication",
    "kicking",
    "throwing",
    "anticipation",
    "decisions",
    "one_on_ones",
    "positioning",
    "reflexes",
    "first_touch",
    "technique",
    "flair",
    "corners",
    "teamwork",
    "work_rate",
    "long_throws",
    "eccentricity",
    "rushing_out",
    "punching",
    "acceleration",
    "free_kick_taking",
    "strength",
    "stamina",
    "pace",
    "jumping_reach",
    "leadership",
    "dirtiness",
    "balance",
    "bravery",
    "consistency",
    "aggression",
    "agility",
    "important_matches",
    "injury_proneness",
    "versatility",
    "natural_fitness",
    "determination",
    "composure",
    "concentration",
)
PERSONALITY_KEYS = (
    "professionalism",
    "loyalty",
    "sportsmanship",
    "temperament",
    "pressure",
    "ambition",
    "adaptability",
)
ATTRIBUTE_COUNT = 69
LEFT_FOOT_ATTRIBUTE_INDEX = 39
RIGHT_FOOT_ATTRIBUTE_INDEX = 40
SAVE_DEPENDENCY_ERROR = "未安装存档读取依赖 fmsave"
SAVE_INVALID_ERROR = "不是有效的 FM 存档"
SAVE_UNSUPPORTED_ERROR = "存档来自暂不支持的游戏版本"
SAVE_CHANGED_ERROR = "读取期间存档发生变化"
PLAYER_ATTRIBUTES_ERROR = "球员属性不完整"
_DEFAULT = object()


def position_values(primary: str = "mc") -> dict[str, int]:
    values = {field: 1 for field in POSITION_FIELDS}
    values[primary] = 20
    return values


def raw_attribute_values() -> dict[str, int]:
    return {field: index + 1 for index, field in enumerate(RAW_ATTRIBUTE_FIELDS)}


def make_personality(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "professionalism": 15,
        "loyalty": 12,
        "sportsmanship": 14,
        "temperament": 8,
        "pressure": 11,
        "ambition": 17,
        "adaptability": 13,
        "controversy": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_player(
    uid: int,
    *,
    unique_id: Any = _DEFAULT,
    name: str | None = None,
    club_uid: int = 1,
    **overrides: Any,
) -> SimpleNamespace:
    values: dict[str, Any] = {
        "uid": uid,
        "unique_id": uid + 100 if unique_id is _DEFAULT else unique_id,
        "name": f"球员{uid}" if name is None else name,
        "club_uid": club_uid,
        "positions": SimpleNamespace(**position_values()),
        "raw_attributes": SimpleNamespace(**raw_attribute_values()),
        "personality": None,
        "left_foot": 12,
        "right_foot": 9,
        "raw_left_foot": 95,
        "raw_right_foot": 60,
        "ability": SimpleNamespace(current=150, potential=180),
        "age": 24,
        "height_cm": 182,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_info(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "game": "FM27",
        "build": "27.0.1+2494687",
        "db_version": "27.0",
        "game_date": date(2026, 7, 1),
        "save_name": "测试存档",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeSave:
    def __init__(
        self,
        *,
        players: Any = (),
        managed_clubs: Any = (),
        clubs: Any = (),
        selections: Any = (),
        info: SimpleNamespace | None = None,
        read_error: Exception | None = None,
    ) -> None:
        self.info = make_info() if info is None else info
        self._players = list(players)
        self._managed_clubs = list(managed_clubs)
        self._clubs = list(clubs)
        self._selections = list(selections)
        self._read_error = read_error
        self.exited = 0

    def __enter__(self) -> FakeSave:
        return self

    def __exit__(self, *exception: Any) -> bool:
        self.exited += 1
        return False

    def _guard(self) -> None:
        if self._read_error is not None:
            raise self._read_error

    def players(self) -> list[Any]:
        self._guard()
        return list(self._players)

    def managed_clubs(self) -> list[Any]:
        self._guard()
        return list(self._managed_clubs)

    def clubs(self) -> list[Any]:
        self._guard()
        return list(self._clubs)

    def selections(self) -> list[Any]:
        self._guard()
        return list(self._selections)


def save_file(tmp_path: Path) -> Path:
    path = tmp_path / "career.fm"
    path.write_bytes(b"FM27 save placeholder")
    return path


def install_save(monkeypatch: pytest.MonkeyPatch, save: FakeSave, calls: list[Path] | None = None) -> None:
    def fake_open(path: Path) -> FakeSave:
        if calls is not None:
            calls.append(path)
        return save

    monkeypatch.setattr(fmsave, "open", fake_open)


def install_open_error(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def fake_open(path: Path) -> FakeSave:
        raise error

    monkeypatch.setattr(fmsave, "open", fake_open)


def selection_row(
    club_uid: int,
    player_uid: int,
    *,
    substitute: Any = _DEFAULT,
    slot: int = 0,
    team_id: int = 100,
    team_slot: int = 0,
    **overrides: Any,
) -> SimpleNamespace:
    values: dict[str, Any] = {
        "club_uid": club_uid,
        "club_name": None,
        "team_id": team_id,
        "team_slot": team_slot,
        "slot": slot,
        "player_uid": player_uid,
        "player_name": None,
    }
    if substitute is not _DEFAULT:
        values["substitute"] = substitute
    values.update(overrides)
    return SimpleNamespace(**values)


def selection_players() -> list[SimpleNamespace]:
    return [
        make_player(1, unique_id=101, club_uid=7),
        make_player(2, unique_id=102, club_uid=7),
        make_player(3, unique_id=103, club_uid=7),
    ]


def selection_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    save: FakeSave,
    club_uid: int = 7,
) -> dict[str, Any] | None:
    install_save(monkeypatch, save)
    return FmsaveReader(save_file(tmp_path)).read_selection(club_uid)


def test_reader_satisfies_save_reader_port(tmp_path: Path):
    assert isinstance(FmsaveReader(save_file(tmp_path)), SaveReader)


def test_read_info_maps_save_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave())
    info = FmsaveReader(save_file(tmp_path)).read_info()
    assert info == {
        "game": "FM27",
        "build": "27.0.1+2494687",
        "db_version": "27.0",
        "game_date": "2026-07-01",
        "save_name": "测试存档",
    }


def test_read_info_without_game_date(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave(info=make_info(game_date=None)))
    assert FmsaveReader(save_file(tmp_path)).read_info()["game_date"] is None


def test_read_managed_clubs_maps_and_sorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    managed = [
        SimpleNamespace(
            club_uid=20,
            club_name="乙队",
            club_short_name="乙",
            manager_name="经理乙",
            manager_staff_uid=902,
        ),
        SimpleNamespace(
            club_uid=10,
            club_name="甲队",
            club_short_name="甲",
            manager_name=None,
            manager_staff_uid=None,
        ),
    ]
    install_save(monkeypatch, FakeSave(managed_clubs=managed))
    assert FmsaveReader(save_file(tmp_path)).read_managed_clubs() == [
        {
            "club_uid": 10,
            "club_name": "甲队",
            "club_short_name": "甲",
            "manager_name": None,
            "manager_staff_uid": None,
        },
        {
            "club_uid": 20,
            "club_name": "乙队",
            "club_short_name": "乙",
            "manager_name": "经理乙",
            "manager_staff_uid": 902,
        },
    ]


def test_read_clubs_maps_and_sorts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clubs = [
        SimpleNamespace(uid=30, unique_id=None, name="丙", short_name="丙队", nation_id=3),
        SimpleNamespace(uid=10, unique_id=1000, name="甲", short_name="甲队", nation_id=1),
    ]
    install_save(monkeypatch, FakeSave(clubs=clubs))
    assert FmsaveReader(save_file(tmp_path)).read_clubs() == [
        {"uid": 10, "unique_id": 1000, "name": "甲", "short_name": "甲队", "nation_id": 1},
        {"uid": 30, "unique_id": None, "name": "丙", "short_name": "丙队", "nation_id": 3},
    ]


def test_read_squad_filters_by_club(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    players = [
        make_player(11, unique_id=110, name="甲", club_uid=7),
        make_player(12, unique_id=120, name="乙", club_uid=8),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    reader = FmsaveReader(save_file(tmp_path))
    assert [entry["source_uid"] for entry in reader.read_squad(7)] == [110]
    assert [entry["source_uid"] for entry in reader.read_squad(8)] == [120]
    assert reader.read_squad(9) == []


def test_read_squad_sorts_by_source_uid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    players = [
        make_player(1, unique_id=300, club_uid=7),
        make_player(2, unique_id=100, club_uid=7),
        make_player(3, unique_id=200, club_uid=7),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert [entry["source_uid"] for entry in squad] == [100, 200, 300]


def test_read_squad_falls_back_to_uid_without_unique_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave(players=[make_player(42, unique_id=None, club_uid=7)]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert squad[0]["source_uid"] == 42


def test_read_squad_maps_sixty_nine_attributes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw = raw_attribute_values()
    install_save(monkeypatch, FakeSave(players=[make_player(5, unique_id=505, club_uid=7)]))
    attributes = FmsaveReader(save_file(tmp_path)).read_squad(7)[0]["attributes"]
    expected = [position_values()[field] for field in POSITION_FIELDS]
    expected += [raw[field] for field in RAW_ATTRIBUTE_FIELDS[:24]]
    expected += [95, 60]
    expected += [raw[field] for field in RAW_ATTRIBUTE_FIELDS[24:]]
    assert len(attributes) == ATTRIBUTE_COUNT
    assert attributes == expected
    assert attributes[:15] == [position_values()[field] for field in POSITION_FIELDS]
    assert attributes[LEFT_FOOT_ATTRIBUTE_INDEX] == 95
    assert attributes[RIGHT_FOOT_ATTRIBUTE_INDEX] == 60
    assert attributes[15] == raw["crossing"]
    assert attributes[68] == raw["concentration"]


def test_read_squad_maps_player_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    player = make_player(
        5,
        unique_id=505,
        name="张三",
        club_uid=7,
        left_foot=17,
        right_foot=6,
        age=23,
        height_cm=181,
        ability=SimpleNamespace(current=157, potential=190),
    )
    install_save(monkeypatch, FakeSave(players=[player]))
    entry = FmsaveReader(save_file(tmp_path)).read_squad(7)[0]
    assert entry["source_uid"] == 505
    assert entry["name"] == "张三"
    assert entry["left_foot"] == 17
    assert entry["right_foot"] == 6
    assert entry["ability"] == 157
    assert entry["age"] == 23
    assert entry["height_cm"] == 181


@pytest.mark.parametrize(("primary", "name"), zip(POSITION_FIELDS, POSITION_NAMES, strict=True))
def test_read_squad_maps_primary_position_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, primary: str, name: str
):
    player = make_player(5, unique_id=505, club_uid=7, positions=SimpleNamespace(**position_values(primary)))
    install_save(monkeypatch, FakeSave(players=[player]))
    assert FmsaveReader(save_file(tmp_path)).read_squad(7)[0]["position"] == name


def test_read_squad_maps_seven_personality_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    player = make_player(5, unique_id=505, club_uid=7, personality=make_personality())
    install_save(monkeypatch, FakeSave(players=[player]))
    personality = FmsaveReader(save_file(tmp_path)).read_squad(7)[0]["personality"]
    assert personality == {
        "professionalism": 15,
        "loyalty": 12,
        "sportsmanship": 14,
        "temperament": 8,
        "pressure": 11,
        "ambition": 17,
        "adaptability": 13,
    }
    assert set(personality) == set(PERSONALITY_KEYS)


def test_read_squad_omits_missing_personality(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave(players=[make_player(5, unique_id=505, club_uid=7)]))
    assert "personality" not in FmsaveReader(save_file(tmp_path)).read_squad(7)[0]


def test_read_squad_omits_unreadable_personality_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    personality = SimpleNamespace(
        professionalism=12,
        loyalty=None,
        sportsmanship=14,
        controversy=4,
    )
    player = make_player(5, unique_id=505, club_uid=7, personality=personality)
    install_save(monkeypatch, FakeSave(players=[player]))
    assert FmsaveReader(save_file(tmp_path)).read_squad(7)[0]["personality"] == {
        "professionalism": 12,
        "sportsmanship": 14,
    }


def test_read_squad_rejects_incomplete_position_ratings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    positions = position_values()
    del positions["wbr"]
    player = make_player(5, unique_id=505, club_uid=7, positions=SimpleNamespace(**positions))
    install_save(monkeypatch, FakeSave(players=[player]))
    with pytest.raises(ValueError, match=PLAYER_ATTRIBUTES_ERROR):
        FmsaveReader(save_file(tmp_path)).read_squad(7)


def test_read_squad_rejects_incomplete_raw_attributes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    raw = raw_attribute_values()
    del raw["concentration"]
    player = make_player(5, unique_id=505, club_uid=7, raw_attributes=SimpleNamespace(**raw))
    install_save(monkeypatch, FakeSave(players=[player]))
    with pytest.raises(ValueError, match=PLAYER_ATTRIBUTES_ERROR):
        FmsaveReader(save_file(tmp_path)).read_squad(7)


def test_reader_opens_path_and_closes_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = save_file(tmp_path)
    save = FakeSave()
    calls: list[Path] = []
    install_save(monkeypatch, save, calls)
    FmsaveReader(path).read_info()
    assert calls == [path]
    assert save.exited == 1


def test_missing_fmsave_dependency_reports_chinese_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "fmsave", None)
    with pytest.raises(RuntimeError, match=SAVE_DEPENDENCY_ERROR):
        FmsaveReader(save_file(tmp_path)).read_info()


def test_pinned_fmsave_supports_fm27_unverified_builds():
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    dependencies = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["dependencies"]
    assert "fmsave==0.12.4" in dependencies


def test_unsupported_game_reports_build_and_update_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    error = fmsave.UnsupportedGameError(
        "FM27: SaveSummaryLayout in 'save_game_summary' has no supported layout for build 27.0.2+9999999, schema 32."
    )
    install_open_error(monkeypatch, error)
    with pytest.raises(ValueError) as caught:
        FmsaveReader(save_file(tmp_path)).read_info()
    assert str(caught.value) == "存档来自暂不支持的游戏版本（27.0.2+9999999），请更新应用后再试"


def test_unsupported_game_without_build_reports_update_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_open_error(monkeypatch, fmsave.UnsupportedGameError("不支持的 FM 版本"))
    with pytest.raises(ValueError) as caught:
        FmsaveReader(save_file(tmp_path)).read_info()
    assert str(caught.value) == "存档来自暂不支持的游戏版本，请更新应用后再试"


def test_read_failure_maps_unsupported_game(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    error = fmsave.UnsupportedGameError("no supported layout for build 27.0.2+9999999")
    install_save(monkeypatch, FakeSave(read_error=error))
    with pytest.raises(ValueError) as caught:
        FmsaveReader(save_file(tmp_path)).read_clubs()
    assert str(caught.value) == "存档来自暂不支持的游戏版本（27.0.2+9999999），请更新应用后再试"


def test_read_failure_maps_save_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave(read_error=fmsave.SaveChangedError("读取期间存档发生变化")))
    with pytest.raises(ValueError) as caught:
        FmsaveReader(save_file(tmp_path)).read_clubs()
    assert str(caught.value) == SAVE_CHANGED_ERROR


@pytest.mark.parametrize(
    "error",
    [
        fmsave.NotAFmSaveError("不是 FM 存档"),
        fmsave.CorruptSaveError("存档损坏"),
        OSError("无法读取文件"),
        ValueError("无效路径"),
    ],
)
def test_invalid_save_reports_chinese_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
):
    install_open_error(monkeypatch, error)
    with pytest.raises(ValueError, match=SAVE_INVALID_ERROR):
        FmsaveReader(save_file(tmp_path)).read_info()


def test_read_failure_reports_chinese_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    install_save(monkeypatch, FakeSave(read_error=RuntimeError("读取失败")))
    with pytest.raises(ValueError, match=SAVE_INVALID_ERROR):
        FmsaveReader(save_file(tmp_path)).read_clubs()


def test_reader_rejects_source_changed_during_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = save_file(tmp_path)
    install_save(monkeypatch, FakeSave())
    signatures = iter([(23, 1000), (24, 1000)])
    original_stat = Path.stat

    def fake_stat(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self != path:
            return original_stat(self, *args, **kwargs)
        size, mtime = next(signatures)
        return SimpleNamespace(st_size=size, st_mtime_ns=mtime)

    monkeypatch.setattr(Path, "stat", fake_stat)
    with pytest.raises(ValueError, match=SAVE_CHANGED_ERROR):
        FmsaveReader(path).read_info()


def test_read_selection_maps_lineup_and_substitutes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [
        selection_row(7, 2, substitute=False, slot=1),
        selection_row(7, 1, substitute=False, slot=0),
        selection_row(7, 3, substitute=True, slot=1),
        selection_row(7, 2, substitute=True, slot=0),
    ]
    save = FakeSave(players=selection_players(), selections=rows)
    assert selection_of(tmp_path, monkeypatch, save) == {
        "club_uid": 7,
        "team_id": 100,
        "team_slot": 0,
        "lineup": [101, 102],
        "substitutes": [102, 103],
    }


def test_read_selection_prefers_first_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [
        selection_row(7, 3, substitute=False, slot=0, team_id=200, team_slot=1),
        selection_row(7, 1, substitute=False, slot=0, team_id=100, team_slot=0),
    ]
    save = FakeSave(players=selection_players(), selections=rows)
    result = selection_of(tmp_path, monkeypatch, save)
    assert result is not None
    assert result["team_id"] == 100
    assert result["lineup"] == [101]


def test_read_selection_tolerates_starter_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [
        selection_row(7, 1, starter=True, slot=0),
        selection_row(7, 2, starter=False, slot=0),
        selection_row(7, 3, starter=False, slot=1),
    ]
    save = FakeSave(players=selection_players(), selections=rows)
    result = selection_of(tmp_path, monkeypatch, save)
    assert result is not None
    assert result["lineup"] == [101]
    assert result["substitutes"] == [102, 103]


@pytest.mark.parametrize("field", ["lineup", "starters", "starter"])
def test_read_selection_supports_structured_lineup_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
):
    entry = SimpleNamespace(club_uid=7, team_id=100, team_slot=0, substitutes=[3])
    setattr(entry, field, [1, 2])
    save = FakeSave(players=selection_players(), selections=[entry])
    assert selection_of(tmp_path, monkeypatch, save) == {
        "club_uid": 7,
        "team_id": 100,
        "team_slot": 0,
        "lineup": [101, 102],
        "substitutes": [103],
    }


def test_read_selection_returns_none_without_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    save = FakeSave(players=selection_players())
    assert selection_of(tmp_path, monkeypatch, save) is None


def test_read_selection_returns_none_for_other_club(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rows = [selection_row(8, 1, substitute=False, slot=0)]
    save = FakeSave(players=selection_players(), selections=rows)
    assert selection_of(tmp_path, monkeypatch, save) is None


@pytest.mark.parametrize(
    "entries",
    [
        [SimpleNamespace(club_uid=7, team_id=100, team_slot=0)],
        [selection_row(7, 999, substitute=False, slot=0)],
    ],
)
def test_read_selection_returns_none_when_unparseable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: list[SimpleNamespace]
):
    save = FakeSave(players=selection_players(), selections=entries)
    assert selection_of(tmp_path, monkeypatch, save) is None


def test_read_squad_omits_empty_personality(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    player = make_player(5, unique_id=505, club_uid=7, personality=SimpleNamespace(controversy=4))
    install_save(monkeypatch, FakeSave(players=[player]))
    assert "personality" not in FmsaveReader(save_file(tmp_path)).read_squad(7)[0]


def test_read_squad_ignores_other_clubs_before_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    broken = make_player(9, club_uid=8, positions=SimpleNamespace())
    target = make_player(5, unique_id=505, club_uid=7)
    install_save(monkeypatch, FakeSave(players=[broken, target]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert [entry["source_uid"] for entry in squad] == [505]

def test_read_squad_disambiguates_unique_id_matching_another_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = [
        make_player(10, unique_id=20, name="甲", club_uid=7),
        make_player(20, unique_id=None, name="乙", club_uid=7),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert [(entry["name"], entry["source_uid"]) for entry in squad] == [("甲", 10), ("乙", 20)]


def test_read_squad_disambiguates_repeated_unique_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = [
        make_player(10, unique_id=99, name="甲", club_uid=7),
        make_player(20, unique_id=99, name="乙", club_uid=7),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert [(entry["name"], entry["source_uid"]) for entry in squad] == [("甲", 10), ("乙", 20)]


def test_read_squad_moves_colliding_player_past_taken_uids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = [
        make_player(10, unique_id=20, name="甲", club_uid=7),
        make_player(20, unique_id=None, name="乙", club_uid=7),
        make_player(50, unique_id=10, name="丙", club_uid=7),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert {entry["name"]: entry["source_uid"] for entry in squad} == {"甲": 51, "乙": 20, "丙": 10}


def test_read_selection_uses_disambiguated_source_uids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = [
        make_player(10, unique_id=20, name="甲", club_uid=7),
        make_player(20, unique_id=None, name="乙", club_uid=7),
    ]
    rows = [
        selection_row(7, 10, substitute=False, slot=0),
        selection_row(7, 20, substitute=True, slot=0),
    ]
    save = FakeSave(players=players, selections=rows)
    assert selection_of(tmp_path, monkeypatch, save) == {
        "club_uid": 7,
        "team_id": 100,
        "team_slot": 0,
        "lineup": [10],
        "substitutes": [20],
    }


def test_read_squad_derives_display_foot_from_raw_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    player = make_player(5, unique_id=505, club_uid=7, left_foot=None, right_foot=None)
    install_save(monkeypatch, FakeSave(players=[player]))
    entry = FmsaveReader(save_file(tmp_path)).read_squad(7)[0]
    assert entry["left_foot"] == 19
    assert entry["right_foot"] == 12


def test_read_squad_replaces_missing_name_with_uid_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player = make_player(10, unique_id=None, club_uid=7)
    player.name = None
    install_save(monkeypatch, FakeSave(players=[player]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert squad[0]["name"] == "未知球员 10"


def test_read_squad_replaces_blank_name_with_uid_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player = make_player(10, unique_id=None, name="   ", club_uid=7)
    install_save(monkeypatch, FakeSave(players=[player]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert squad[0]["name"] == "未知球员 10"


def test_read_squad_keeps_readable_name_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player = make_player(10, unique_id=None, name=" 张三 ", club_uid=7)
    install_save(monkeypatch, FakeSave(players=[player]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert squad[0]["name"] == " 张三 "


def test_read_squad_uses_global_ids_when_clubs_collide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    players = [
        make_player(10, unique_id=20, name="甲", club_uid=7),
        make_player(20, unique_id=None, name="乙", club_uid=8),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    reader = FmsaveReader(save_file(tmp_path))
    assert [entry["source_uid"] for entry in reader.read_squad(7)] == [10]
    assert [entry["source_uid"] for entry in reader.read_squad(8)] == [20]



def test_read_squad_labels_placeholder_with_resolved_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unnamed = make_player(10, unique_id=20, club_uid=7)
    unnamed.name = None
    players = [
        unnamed,
        make_player(20, unique_id=None, name="乙", club_uid=7),
        make_player(50, unique_id=10, name="丙", club_uid=7),
    ]
    install_save(monkeypatch, FakeSave(players=players))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert {entry["source_uid"]: entry["name"] for entry in squad} == {
        10: "丙",
        20: "乙",
        51: "未知球员 51",
    }


def test_read_squad_uses_unique_id_when_uid_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    player = make_player(10, unique_id=30, name="甲", club_uid=7)
    player.uid = None
    install_save(monkeypatch, FakeSave(players=[player]))
    squad = FmsaveReader(save_file(tmp_path)).read_squad(7)
    assert [entry["source_uid"] for entry in squad] == [30]
