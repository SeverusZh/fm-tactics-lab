"""Save import, squad reading and draft roster synchronization service."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from fm27lab.application.drafts import DraftService
from fm27lab.application.saves import SavesService
from fm27lab.application.source_paths import clean_path_text
from fm27lab.domain.roster import (
    MATCH_ROSTER_SIZE,
    STARTERS,
    apply_roster_selection,
    apply_saved_roster,
    normalize_roster,
)

SAVE_MISSING_ERROR = "存档文件不存在"
SAVE_UNREADABLE_ERROR = "存档无法读取"
SAVE_DUPLICATE_ERROR = "存档内容重复"
SNAPSHOT_KEY = "roster_snapshot"
SUMMARY_KEYS = ("id", "name", "source", "created_at", "updated_at")
SIDES: dict[str, int] = {"home": 0, "away": 1}
SCOPES: tuple[str, ...] = ("starters", "bench", "both")
ROSTER_ERRORS: dict[str, str] = {
    "roster_empty": "存档球队没有可读取的球员",
    "roster_missing_goalkeeper": "存档球队缺少门将",
    "roster_missing_source_uid": "存档球员缺少标识",
    "roster_invalid_source_uid": "存档球员标识无效",
    "roster_duplicate_source_uid": "存档球员标识重复",
}
ReaderFactory = Callable[[Path], Any]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ValueError(f"{SAVE_UNREADABLE_ERROR}：{error}") from error
    return digest.hexdigest()


def _changed(before: list[Mapping[str, Any]], after: list[Mapping[str, Any]]) -> int:
    return sum(
        1 for old, new in zip(before, after, strict=True) if old.get("source_uid") != new.get("source_uid")
    )


def _uid_indices(
    selection: Mapping[str, Any] | None,
    key: str,
    index_by_uid: Mapping[Any, int],
) -> list[int]:
    values = selection.get(key) if isinstance(selection, Mapping) else None
    if not isinstance(values, list):
        return []
    result: list[int] = []
    for uid in values:
        if type(uid) not in (int, str):
            continue
        index = index_by_uid.get(uid)
        if index is not None and index not in result:
            result.append(index)
    return result


class SaveImportService:
    def __init__(self, saves: SavesService, drafts: DraftService, reader_factory: ReaderFactory):
        self.saves = saves
        self.drafts = drafts
        self.reader_factory = reader_factory

    def import_save(self, source_path: str, replace: bool = False) -> dict[str, Any]:
        path = self._source_path(source_path)
        source_sha256 = _sha256(path)
        existing = self._find_by_sha(source_sha256)
        if existing is not None and not replace:
            raise ValueError(SAVE_DUPLICATE_ERROR)
        try:
            reader = self.reader_factory(path)
            info = reader.read_info()
            managed_clubs = reader.read_managed_clubs()
            identities = reader.read_clubs()
            payloads = self._club_payloads(reader, managed_clubs, identities)
        except RuntimeError as error:
            raise ValueError(f"{SAVE_UNREADABLE_ERROR}：{error}") from error
        metadata = {
            "game": info.get("game"),
            "build": info.get("build"),
            "game_date": info.get("game_date"),
            "managed_club_uids": list(payloads),
        }
        record = self._store(existing, path, source_sha256, metadata, payloads)
        return {
            "save_id": record["id"],
            "status": record["status"],
            "managed_clubs": [self._managed_summary(payload) for payload in payloads.values()],
            "clubs": len(payloads),
        }

    def get_squad(self, save_id: str, club_uid: int) -> dict[str, Any] | None:
        self._validate_club_uid(club_uid)
        if self.saves.get(save_id) is None:
            return None
        for row in self.saves.clubs(save_id):
            if row["club_uid"] != club_uid:
                continue
            payload = row["payload"]
            return {
                "save_id": save_id,
                "club_uid": club_uid,
                "club_name": payload.get("club_name") or payload.get("name"),
                "players": list(payload.get("players") or []),
                "selection": payload.get("selection"),
            }
        return None

    def apply_roster(
        self,
        draft_id: str,
        save_id: str,
        club_uid: int,
        side: str,
        scope: str,
    ) -> dict[str, Any] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        squad = self.get_squad(save_id, club_uid)
        if squad is None:
            return None
        side_index = self._side(side)
        scope_name = self._scope(scope)
        saved = self._saved_roster(squad)
        team = self._team(draft["scenario"], side_index)
        current = list(team["players"])
        if scope_name == "both":
            roster = {
                "players": saved["players"],
                "lineup": list(range(STARTERS)),
                "roster_size": MATCH_ROSTER_SIZE,
            }
            updated_team = apply_saved_roster(team, roster)
        elif scope_name == "starters":
            updated_team = apply_roster_selection(
                team,
                starters=saved["players"][:STARTERS],
                substitutes=current[STARTERS:MATCH_ROSTER_SIZE],
            )
        else:
            updated_team = apply_roster_selection(
                team,
                starters=current[:STARTERS],
                substitutes=saved["players"][STARTERS:],
            )
        updated_players = updated_team["players"]
        applied = {
            "starters": _changed(current[:STARTERS], updated_players[:STARTERS]),
            "substitutes": _changed(
                current[STARTERS:MATCH_ROSTER_SIZE],
                updated_players[STARTERS:MATCH_ROSTER_SIZE],
            ),
        }
        scenario = copy.deepcopy(draft["scenario"])
        scenario["teams"][side_index] = updated_team
        source = dict(draft["source"])
        source[SNAPSHOT_KEY] = {
            "side": side,
            "save_id": save_id,
            "club_uid": club_uid,
            "scenario_before": copy.deepcopy(draft["scenario"]),
        }
        updated = self.drafts.update(draft_id, scenario=scenario, source=source)
        if updated is None:
            return None
        return {"draft": self._summary(updated), "applied": applied}

    def undo_roster(self, draft_id: str) -> dict[str, Any] | None:
        draft = self.drafts.get(draft_id)
        if draft is None:
            return None
        source = dict(draft["source"])
        snapshot = source.get(SNAPSHOT_KEY)
        if not isinstance(snapshot, Mapping):
            raise ValueError("没有可撤销的阵容同步")
        scenario_before = snapshot.get("scenario_before")
        if not isinstance(scenario_before, Mapping):
            raise ValueError("阵容同步快照无效")
        source.pop(SNAPSHOT_KEY)
        updated = self.drafts.update(draft_id, scenario=scenario_before, source=source)
        if updated is None:
            return None
        return {"draft": self._summary(updated)}

    @staticmethod
    def _source_path(source_path: Any) -> Path:
        text = clean_path_text(source_path)
        if text is None:
            raise ValueError(SAVE_MISSING_ERROR)
        path = Path(text)
        if not path.is_file():
            raise ValueError(SAVE_MISSING_ERROR)
        return path

    def _find_by_sha(self, source_sha256: str) -> dict[str, Any] | None:
        offset = 0
        while True:
            page = self.saves.list(limit=256, offset=offset)
            for item in page["items"]:
                if item["source_sha256"] == source_sha256:
                    return item
            if page["next_offset"] is None:
                return None
            offset = page["next_offset"]

    @staticmethod
    def _club_payloads(
        reader: Any,
        managed_clubs: list[dict[str, Any]],
        identities: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]]:
        index: dict[int, dict[str, Any]] = {}
        for identity in identities:
            uid = identity.get("uid")
            if type(uid) is int:
                index.setdefault(uid, identity)
        payloads: dict[int, dict[str, Any]] = {}
        for entry in managed_clubs:
            club_uid = entry.get("club_uid")
            if type(club_uid) is not int or club_uid <= 0:
                raise ValueError("存档俱乐部标识无效")
            if club_uid in payloads:
                continue
            identity = index.get(club_uid, {})
            payloads[club_uid] = {
                "club_uid": club_uid,
                "club_name": entry.get("club_name"),
                "club_short_name": entry.get("club_short_name"),
                "manager_name": entry.get("manager_name"),
                "manager_staff_uid": entry.get("manager_staff_uid"),
                "name": identity.get("name"),
                "short_name": identity.get("short_name"),
                "nation_id": identity.get("nation_id"),
                "players": list(reader.read_squad(club_uid)),
                "selection": reader.read_selection(club_uid),
            }
        return payloads

    def _store(
        self,
        existing: Mapping[str, Any] | None,
        path: Path,
        source_sha256: str,
        metadata: Mapping[str, Any],
        payloads: Mapping[int, Mapping[str, Any]],
    ) -> dict[str, Any]:
        repository = self.saves.repository
        with repository.database.transaction() as connection:
            if existing is None:
                record = repository.add(
                    {
                        "source_path": str(path),
                        "source_sha256": source_sha256,
                        "status": "ready",
                        "metadata": metadata,
                    },
                    connection=connection,
                )
                leagues: dict[str, Mapping[str, Any]] = {}
            else:
                leagues = {
                    row["league_key"]: row["payload"]
                    for row in repository.leagues(existing["id"], connection=connection)
                }
                record = repository.update(
                    existing["id"],
                    {"status": "ready", "metadata": metadata},
                    connection=connection,
                )
                if record is None:
                    raise ValueError("存档不存在")
            repository.replace_children(record["id"], leagues, payloads, connection=connection)
        return record

    @staticmethod
    def _managed_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "club_uid": payload["club_uid"],
            "club_name": payload.get("club_name"),
            "players": len(payload["players"]),
        }

    @staticmethod
    def _validate_club_uid(club_uid: Any) -> int:
        if type(club_uid) is not int or club_uid <= 0:
            raise ValueError("俱乐部标识无效")
        return club_uid

    @staticmethod
    def _saved_roster(squad: Mapping[str, Any]) -> dict[str, Any]:
        players = list(squad.get("players") or [])
        index_by_uid: dict[Any, int] = {}
        for index, player in enumerate(players):
            uid = player.get("source_uid") if isinstance(player, Mapping) else None
            if type(uid) in (int, str):
                index_by_uid.setdefault(uid, index)
        selection = squad.get("selection")
        try:
            result = normalize_roster(
                players,
                lineup=_uid_indices(selection, "lineup", index_by_uid),
                substitutes=_uid_indices(selection, "substitutes", index_by_uid),
            )
        except ValueError as error:
            raise ValueError(ROSTER_ERRORS.get(str(error), "存档名单无效")) from error
        if result.generated:
            raise ValueError("存档球队不足 23 名真实球员")
        return {"players": [dict(player) for player in result.players], "lineup": list(result.lineup)}

    @staticmethod
    def _team(scenario: Mapping[str, Any], side_index: int) -> dict[str, Any]:
        teams = scenario.get("teams") if isinstance(scenario, Mapping) else None
        if (
            not isinstance(teams, list)
            or len(teams) != 2
            or any(not isinstance(team, Mapping) for team in teams)
        ):
            raise ValueError("草稿场景无效")
        team = teams[side_index]
        players = team.get("players")
        if (
            not isinstance(players, list)
            or len(players) != MATCH_ROSTER_SIZE
            or any(not isinstance(player, Mapping) for player in players)
        ):
            raise ValueError("草稿球队名单必须为 23 人")
        return dict(team)

    @staticmethod
    def _side(side: Any) -> int:
        if not isinstance(side, str) or side not in SIDES:
            raise ValueError("side 必须是 home 或 away")
        return SIDES[side]

    @staticmethod
    def _scope(scope: Any) -> str:
        if not isinstance(scope, str) or scope not in SCOPES:
            raise ValueError("scope 必须是 starters、bench 或 both")
        return scope

    @staticmethod
    def _summary(draft: Mapping[str, Any]) -> dict[str, Any]:
        return {key: draft[key] for key in SUMMARY_KEYS}
