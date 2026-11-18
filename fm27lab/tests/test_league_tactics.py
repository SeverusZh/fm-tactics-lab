"""联赛对手战术服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.coach_presets import (
    PresetCatalog,
    PresetTemplate,
    StaffPreference,
)
from fm27lab.adapters.engine_native.tactic_file import TacticCell, TacticFileError, TacticPlan
from fm27lab.adapters.save_fmsave.league import Club, Coach, League, LeagueCatalog
from fm27lab.application.league_tactics import (
    ENGINE_MISMATCH,
    NO_COACH,
    LeagueTacticsService,
)
from fm27lab.config import Settings

PHASES = tuple(
    tuple(TacticCell(position=index, role_flags=1, pi_flags=0, target_player=255, target_position=0) for index in range(11))
    for _ in range(2)
)
PLAN = TacticPlan(name="预设", mentality=4, team_bits=0, mapping=tuple(range(11)), phases=PHASES)
POSITIONS = tuple(range(11))
OTHER = tuple(reversed(POSITIONS))


class FakeSaves:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self, save_id: str):
        return {"id": save_id, "source_path": str(self.path)}


def club(uid: int, name: str) -> Club:
    return Club(uid=uid, unique_id=uid, name=name, short_name=name, nation_id=1, first_team_id=uid)


def catalog_two() -> LeagueCatalog:
    first = League("7:257:2029", 7, 11, 257, 2029, (1, 2, 3), 12, "2029-08-01", "2030-05-01")
    second = League("8:258:2029", 8, 12, 258, 2029, (1, 4, 5), 12, "2029-08-01", "2030-05-01")
    return LeagueCatalog(
        leagues=(first, second),
        clubs={
            1: club(1, "本队"),
            2: club(2, "阿森纳"),
            3: club(3, "利物浦"),
            4: club(4, "切尔西"),
            5: club(5, "热刺"),
        },
        managed=(1,),
        current=first,
        ambiguous=(),
        played=frozenset(),
        save_date="2029-12-01",
    )


def catalog() -> LeagueCatalog:
    league = League("7:257:2029", 7, 11, 257, 2029, (1, 2, 3), 12, "2029-08-01", "2030-05-01")
    return LeagueCatalog(
        leagues=(league,),
        clubs={1: club(1, "本队"), 2: club(2, "阿森纳"), 3: club(3, "利物浦")},
        managed=(1,),
        current=league,
        ambiguous=(),
        played=frozenset({2}),
        save_date="2029-12-01",
    )


def coach(uid: int, name: str) -> Coach:
    return Coach(
        club_uid=uid,
        uid=uid * 10,
        unique_id=uid * 100,
        name=name,
        team_id=uid,
        team_slot=0,
        selector=uid * 1000,
        profile_hex="00" * 52,
        codes_hex="0a14000000000000",
        fragment=b"x" * 4096,
    )


def presets() -> PresetCatalog:
    first = PresetTemplate(index=0, style_code=100, name="控球甲", plan=PLAN)
    second = PresetTemplate(index=1, style_code=100, name="控球乙", plan=PLAN)
    return PresetCatalog(
        styles={0: 100},
        formations={10: POSITIONS, 20: OTHER},
        templates=(first, second),
    )


def scenario(*, tactic_name: str) -> dict:
    cells = [
        {
            "position": "DC",
            "role": "CentreBack",
            "duty": "0",
            "instructions": {},
            "target_player": 255,
            "target_position": 0,
        }
        for _ in range(11)
    ]
    return {
        "schema": 4,
        "teams": [
            {
                "tactic_name": tactic_name,
                "mentality": 4,
                "instructions": {},
                "native_extra_team_bits": "0",
                "phases": [cells, cells],
            },
            {"tactic_name": "主队", "mentality": 4, "instructions": {}, "native_extra_team_bits": "0", "phases": [cells, cells]},
        ],
    }


def squad() -> list[dict]:
    players = []
    for index in range(23):
        players.append(
            {
                "source_uid": 1000 + index,
                "name": f"球员{index}",
                "position": "GK" if index == 0 else "DC",
                "ability": 150 - index,
                "attributes": [10] * 69,
            }
        )
    return players


def service(
    tmp_path: Path,
    *,
    coaches=None,
    preset_error: Exception | None = None,
    coach_error: Exception | None = None,
    catalog_value: LeagueCatalog | None = None,
    preference_profile: str = "00" * 52,
    preference_codes: str = "0a14000000000000",
) -> tuple[LeagueTacticsService, dict]:
    calls = {"coaches": 0, "presets": 0}
    settings = Settings.create(
        tmp_path.resolve(),
        engine_root=tmp_path.resolve(),
        game_root=tmp_path.resolve(),
    )

    def coach_reader(path: Path, clubs):
        calls["coaches"] += 1
        if coach_error is not None:
            raise coach_error
        return tuple(coaches if coaches is not None else (coach(2, "阿尔特塔"), coach(3, "斯洛特")))

    def preset_exporter(**_kwargs):
        calls["presets"] += 1
        if preset_error is not None:
            raise preset_error
        return presets()

    exporter_calls = []

    class Exporter:
        def export(self, **kwargs):
            exporter_calls.append(kwargs)
            return b"fmf"

    svc = LeagueTacticsService(
        FakeSaves(tmp_path / "save.fm"),
        settings,
        catalog_reader=lambda _path: catalog_value if catalog_value is not None else catalog(),
        coach_reader=coach_reader,
        preset_exporter=preset_exporter,
        staff_decoder=lambda fragments, **_kwargs: {
            selector: StaffPreference(
                selector=selector,
                style=0,
                primary=10,
                secondary=20,
                profile_hex=preference_profile,
                codes_hex=preference_codes,
            )
            for selector in fragments
        },
        assets_loader=lambda _root: object(),
        builder=lambda _assets, plan, tactic_name: scenario(tactic_name=tactic_name),
        squads_reader=lambda _path, clubs: {uid: squad() for uid in clubs},
        exporter=Exporter(),
    )
    (tmp_path / "save.fm").write_bytes(b"save")
    return svc, calls


def test_rows_build_two_preset_variants_per_opponent(tmp_path: Path):
    svc, calls = service(tmp_path)
    rows = svc.rows("save-1", "7:257:2029")
    assert len(rows) == 4
    assert [row["index"] for row in rows] == [10000, 10001, 10002, 10003]
    assert all(row["available"] for row in rows)
    assert all(row["source"] == "coach_preset" for row in rows)
    first = next(row for row in rows if row["club_uid"] == 2)
    assert first["coach_name"] == "阿尔特塔"
    assert first["importable"] is True
    assert calls == {"coaches": 1, "presets": 1}
    svc.rows("save-1", "7:257:2029")
    assert calls == {"coaches": 1, "presets": 1}


def test_pool_entry_includes_roster_and_tactic(tmp_path: Path):
    svc, _calls = service(tmp_path)
    rows = svc.rows("save-1", "7:257:2029")
    index = next(row["index"] for row in rows if row["club_uid"] == 2)
    entry = svc.pool_entry("save-1", index)
    assert entry["name"].startswith("阿森纳")
    assert entry["tactic"]["phases"][0][0]["position"] == "DC"
    assert entry["roster"]["club_uid"] == 2
    assert entry["roster"]["source"] == "coach_preset"
    assert entry["roster"]["roster_size"] == 23
    assert entry["roster"]["lineup"] == list(range(11))


def test_export_fmf_uses_preset_scenario(tmp_path: Path):
    svc, _calls = service(tmp_path)
    rows = svc.rows("save-1", "7:257:2029")
    index = next(row["index"] for row in rows if row["club_uid"] == 2)
    title, payload = svc.export_fmf("save-1", index)
    assert title.startswith("阿森纳")
    assert payload == b"fmf"


def test_missing_coach_is_reported_without_blocking_others(tmp_path: Path):
    svc, _calls = service(tmp_path, coaches=(coach(2, "阿尔特塔"),))
    rows = svc.rows("save-1", "7:257:2029")
    assert len(rows) == 3
    missing = [row for row in rows if row["club_uid"] == 3]
    assert missing[0]["available"] is False
    assert missing[0]["reason"] == NO_COACH
    assert svc.failures("save-1", "7:257:2029")[0]["club_uid"] == 3


def test_engine_mismatch_marks_every_opponent_unavailable(tmp_path: Path):
    svc, _calls = service(tmp_path, preset_error=TacticFileError("引擎与当前游戏版本不一致"))
    rows = svc.rows("save-1", "7:257:2029")
    assert len(rows) == 2
    assert all(row["available"] is False for row in rows)
    assert all(row["reason"] == ENGINE_MISMATCH for row in rows)


def test_materialize_requires_a_loaded_league_list(tmp_path: Path):
    svc, _calls = service(tmp_path)
    with pytest.raises(ValueError, match="刷新联赛战术列表"):
        svc.materialize("save-1", 10000)


def test_listing_keeps_league_indices_distinct_across_leagues(tmp_path: Path):
    svc, _calls = service(
        tmp_path,
        coaches=(coach(2, "阿尔特塔"), coach(3, "斯洛特"), coach(4, "波切蒂诺"), coach(5, "弗兰克")),
        catalog_value=catalog_two(),
    )
    first = svc.rows("save-1", "7:257:2029")
    second = svc.rows("save-1", "8:258:2029")
    again = svc.rows("save-1", "7:257:2029")
    assert [row["index"] for row in first] == [10000, 10001, 10002, 10003]
    assert [row["index"] for row in second] == [11000, 11001, 11002, 11003]
    assert [row["index"] for row in again] == [10000, 10001, 10002, 10003]
    assert svc.materialize("save-1", 10000).club_uid == 3
    assert svc.materialize("save-1", 11000).club_uid == 4
    assert again[0]["league_key"] == "7:257:2029"
    assert second[0]["league_key"] == "8:258:2029"


def test_catalog_reports_current_opponent_count(tmp_path: Path):
    svc, _calls = service(tmp_path)
    assert svc.catalog("save-1")["current"]["opponent_count"] == 2


def test_coach_read_failure_becomes_unavailable_rows(tmp_path: Path):
    svc, _calls = service(tmp_path, coach_error=ValueError("教练布局不支持"))
    rows = svc.rows("save-1", "7:257:2029")
    assert len(rows) == 2
    assert all(row["available"] is False for row in rows)
    assert all("教练偏好读取失败" in (row["reason"] or "") for row in rows)


def test_roster_keeps_reserve_goalkeeper_out_of_lineup():
    from fm27lab.application.league_tactics import _roster_from

    players = []
    for index in range(23):
        players.append(
            {
                "source_uid": 1000 + index,
                "name": f"球员{index}",
                "position": "GK" if index < 2 else "DC",
                "ability": 150 - index,
                "attributes": [10] * 69,
            }
        )
    roster = _roster_from(players, 2, "阿森纳", "阿尔特塔")
    assert roster is not None
    assert roster["lineup"] == list(range(11))
    lineup_uids = {roster["players"][index]["source_uid"] for index in roster["lineup"]}
    assert 1001 not in lineup_uids
    assert roster["players"][22]["source_uid"] == 1001


def test_save_change_rebuilds_variants_and_invalidates_old_indices(tmp_path: Path):
    svc, calls = service(tmp_path)
    svc.rows("save-1", "7:257:2029")
    assert calls["coaches"] == 1
    (tmp_path / "save.fm").write_bytes(b"save-changed")
    svc.rows("save-1", "7:257:2029")
    assert calls["coaches"] == 2
    assert len(svc._variants) == 1
    assert svc.materialize("save-1", 10000).available is True


def test_pool_entries_from_two_leagues_both_keep_rosters(tmp_path: Path):
    svc, _calls = service(
        tmp_path,
        coaches=(coach(2, "阿尔特塔"), coach(3, "斯洛特"), coach(4, "波切蒂诺"), coach(5, "弗兰克")),
        catalog_value=catalog_two(),
    )
    first = svc.rows("save-1", "7:257:2029")
    first_index = next(row["index"] for row in first if row["club_uid"] == 2)
    assert svc.pool_entry("save-1", first_index)["roster"] is not None
    second = svc.rows("save-1", "8:258:2029")
    second_index = next(row["index"] for row in second if row["club_uid"] == 4)
    assert svc.pool_entry("save-1", second_index)["roster"] is not None


def test_materialize_rejects_stale_variants_after_save_change(tmp_path: Path):
    from fm27lab.application.league_tactics import LEAGUE_LIST_REQUIRED

    svc, _calls = service(tmp_path)
    svc.rows("save-1", "7:257:2029")
    (tmp_path / "save.fm").write_bytes(b"changed-after-listing")
    with pytest.raises(ValueError, match=LEAGUE_LIST_REQUIRED):
        svc.materialize("save-1", 10000)


def test_profile_or_codes_mismatch_marks_opponents_unavailable(tmp_path: Path):
    from fm27lab.application.league_tactics import PREFERENCE_MISMATCH

    svc, _calls = service(tmp_path, preference_codes="ffffffffffffffff")
    rows = svc.rows("save-1", "7:257:2029")
    assert len(rows) == 2
    assert all(row["available"] is False for row in rows)
    assert all(row["reason"] == PREFERENCE_MISMATCH for row in rows)
