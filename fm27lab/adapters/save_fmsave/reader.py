"""fmsave-backed save reader adapter.

The fmsave dependency is imported lazily so the sidecar still starts when the
save reader dependency is absent; only reading a save then fails.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

SAVE_DEPENDENCY_ERROR = "未安装存档读取依赖 fmsave"
SAVE_INVALID_ERROR = "不是有效的 FM 存档"
SAVE_CHANGED_ERROR = "读取期间存档发生变化"
PLAYER_ATTRIBUTES_ERROR = "球员属性不完整"

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
FOOT_ATTRIBUTE_OFFSET = 24
LEFT_FOOT_ATTRIBUTE_INDEX = 15 + FOOT_ATTRIBUTE_OFFSET
RIGHT_FOOT_ATTRIBUTE_INDEX = 15 + FOOT_ATTRIBUTE_OFFSET + 1
_MISSING = object()


def _load_fmsave() -> Any:
    try:
        import fmsave
    except ImportError as error:
        raise RuntimeError(SAVE_DEPENDENCY_ERROR) from error
    return fmsave


def _field(source: Any, name: str) -> Any:
    if source is _MISSING:
        return _MISSING
    if isinstance(source, Mapping):
        return source.get(name, _MISSING)
    return getattr(source, name, _MISSING)


def _text(source: Any, name: str) -> str | None:
    value = _field(source, name)
    return value if isinstance(value, str) else None


def _integer(source: Any, name: str) -> int | None:
    value = _field(source, name)
    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)
    return None


def _attribute_values(player: Any) -> list[int]:
    """Map a player record onto the 69 native attributes.

    The game stores a 54-value raw block: 24 attributes, left foot, right foot,
    then the remaining 28 attributes. fmsave exposes the feet as raw_left_foot
    and raw_right_foot instead of raw_attributes fields, so catalog indices 39
    and 40 come from those two values.
    """
    positions = _field(player, "positions")
    raw = _field(player, "raw_attributes")
    values = [_integer(positions, name) for name in POSITION_FIELDS]
    values += [_integer(raw, name) for name in RAW_ATTRIBUTE_FIELDS[:FOOT_ATTRIBUTE_OFFSET]]
    values += [_integer(player, "raw_left_foot"), _integer(player, "raw_right_foot")]
    values += [_integer(raw, name) for name in RAW_ATTRIBUTE_FIELDS[FOOT_ATTRIBUTE_OFFSET:]]
    if len(values) != ATTRIBUTE_COUNT or any(value is None for value in values):
        raise ValueError(PLAYER_ATTRIBUTES_ERROR)
    return [int(value) for value in values]


def _display_foot(player: Any, name: str, raw: int) -> int:
    value = _integer(player, name)
    return value if value is not None else max(1, (raw + 2) // 5)


def _personality(player: Any) -> dict[str, int] | None:
    source = _field(player, "personality")
    if source is _MISSING or source is None:
        return None
    present = {name: value for name in PERSONALITY_KEYS if (value := _integer(source, name)) is not None}
    return present or None


def _position_name(attributes: Sequence[int]) -> str:
    index = max(range(len(POSITION_FIELDS)), key=lambda position: (attributes[position], -position))
    return POSITION_NAMES[index]


def _current_ability(player: Any) -> int | None:
    ability = _field(player, "ability")
    return None if ability is _MISSING or ability is None else _integer(ability, "current")


def _player_entry(player: Any) -> dict[str, Any]:
    attributes = _attribute_values(player)
    unique_id = _integer(player, "unique_id")
    source_uid = unique_id if unique_id is not None else _integer(player, "uid")
    if source_uid is None:
        raise ValueError(SAVE_INVALID_ERROR)
    entry: dict[str, Any] = {
        "source_uid": source_uid,
        "name": _text(player, "name") or "",
        "attributes": attributes,
        "left_foot": _display_foot(player, "left_foot", attributes[LEFT_FOOT_ATTRIBUTE_INDEX]),
        "right_foot": _display_foot(player, "right_foot", attributes[RIGHT_FOOT_ATTRIBUTE_INDEX]),
        "position": _position_name(attributes),
        "ability": _current_ability(player),
        "age": _integer(player, "age"),
        "height_cm": _integer(player, "height_cm"),
    }
    personality = _personality(player)
    if personality is not None:
        entry["personality"] = personality
    return entry


def _save_info(save: Any) -> dict[str, Any]:
    info = _field(save, "info")
    game_date = _field(info, "game_date")
    return {
        "game": _text(info, "game"),
        "build": _text(info, "build"),
        "db_version": _text(info, "db_version"),
        "game_date": game_date.isoformat() if isinstance(game_date, date) else None,
        "save_name": _text(info, "save_name"),
    }


def _managed_club(entry: Any) -> dict[str, Any]:
    return {
        "club_uid": _integer(entry, "club_uid"),
        "club_name": _text(entry, "club_name"),
        "club_short_name": _text(entry, "club_short_name"),
        "manager_name": _text(entry, "manager_name"),
        "manager_staff_uid": _integer(entry, "manager_staff_uid"),
    }


def _managed_clubs(save: Any) -> list[dict[str, Any]]:
    return sorted(
        (_managed_club(entry) for entry in save.managed_clubs()),
        key=lambda item: item["club_uid"],
    )


def _club(entry: Any) -> dict[str, Any]:
    return {
        "uid": _integer(entry, "uid"),
        "unique_id": _integer(entry, "unique_id"),
        "name": _text(entry, "name"),
        "short_name": _text(entry, "short_name"),
        "nation_id": _integer(entry, "nation_id"),
    }


def _clubs(save: Any) -> list[dict[str, Any]]:
    return sorted((_club(entry) for entry in save.clubs()), key=lambda item: item["uid"])


def _squad(save: Any, club_uid: int) -> list[dict[str, Any]]:
    players = [_player_entry(player) for player in save.players() if _integer(player, "club_uid") == club_uid]
    return sorted(players, key=lambda entry: entry["source_uid"])


def _player_index(save: Any) -> dict[int, int]:
    index: dict[int, int] = {}
    for player in save.players():
        uid = _integer(player, "uid")
        if uid is None:
            continue
        unique_id = _integer(player, "unique_id")
        index[uid] = uid if unique_id is None else unique_id
    return index


def _starter_flag(entry: Any) -> bool | None:
    substitute = _field(entry, "substitute")
    if isinstance(substitute, bool):
        return not substitute
    starter = _field(entry, "starter")
    if isinstance(starter, bool):
        return starter
    return None


def _current_team(entries: Sequence[Any]) -> list[Any]:
    groups: dict[int | None, list[Any]] = {}
    for entry in entries:
        groups.setdefault(_integer(entry, "team_slot"), []).append(entry)
    if 0 in groups:
        return groups[0]
    return next(iter(groups.values()))


def _slot_order(pick: tuple[int | None, int, int]) -> tuple[int, int, int]:
    slot, order, _ = pick
    return (1, 0, order) if slot is None else (0, slot, order)


def _selection_payload(
    club_uid: int,
    entries: Sequence[Any],
    lineup: Sequence[int],
    substitutes: Sequence[int],
    index: Mapping[int, int],
) -> dict[str, Any] | None:
    first = entries[0]
    payload = {
        "club_uid": club_uid,
        "team_id": _integer(first, "team_id"),
        "team_slot": _integer(first, "team_slot"),
        "lineup": [index[uid] for uid in lineup if uid in index],
        "substitutes": [index[uid] for uid in substitutes if uid in index],
    }
    if not payload["lineup"] and not payload["substitutes"]:
        return None
    return payload


def _row_selection(
    club_uid: int,
    entries: Sequence[Any],
    index: Mapping[int, int],
) -> dict[str, Any] | None:
    starters: list[tuple[int | None, int, int]] = []
    substitutes: list[tuple[int | None, int, int]] = []
    for order, entry in enumerate(entries):
        player_uid = _integer(entry, "player_uid")
        starter = _starter_flag(entry)
        if player_uid is None or starter is None:
            continue
        target = starters if starter else substitutes
        target.append((_integer(entry, "slot"), order, player_uid))
    if not starters and not substitutes:
        return None
    return _selection_payload(
        club_uid,
        entries,
        [uid for _, _, uid in sorted(starters, key=_slot_order)],
        [uid for _, _, uid in sorted(substitutes, key=_slot_order)],
        index,
    )


def _uid_list(entry: Any, names: Sequence[str]) -> list[int] | None:
    for name in names:
        value = _field(entry, name)
        if isinstance(value, (list, tuple)):
            return [int(item) for item in value if isinstance(item, int) and not isinstance(item, bool)]
    return None


def _structured_selection(
    club_uid: int,
    entries: Sequence[Any],
    index: Mapping[int, int],
) -> dict[str, Any] | None:
    for entry in entries:
        lineup = _uid_list(entry, ("lineup", "starters", "starter"))
        substitutes = _uid_list(entry, ("substitutes",))
        if lineup is None and substitutes is None:
            continue
        return _selection_payload(club_uid, [entry], lineup or [], substitutes or [], index)
    return None


def _selection(save: Any, club_uid: int) -> dict[str, Any] | None:
    selections = save.selections()
    entries = list(selections) if selections is not None else []
    matched = [entry for entry in entries if _integer(entry, "club_uid") == club_uid]
    if not matched:
        return None
    current = _current_team(matched)
    index = _player_index(save)
    return _row_selection(club_uid, current, index) or _structured_selection(club_uid, current, index)


class FmsaveReader:
    """Read one save file through fmsave.

    The reader is bound to a path, not to an open handle: every call opens the
    save, reads only the requested table and closes it. The source file signature
    is captured before and after the read so a save written by the game during
    the read is rejected instead of being mixed into one snapshot.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def read_info(self) -> dict[str, Any]:
        return self._with_save(_save_info)

    def read_managed_clubs(self) -> list[dict[str, Any]]:
        return self._with_save(_managed_clubs)

    def read_clubs(self) -> list[dict[str, Any]]:
        return self._with_save(_clubs)

    def read_squad(self, club_uid: int) -> list[dict[str, Any]]:
        return self._with_save(lambda save: _squad(save, club_uid))

    def read_selection(self, club_uid: int) -> dict[str, Any] | None:
        return self._with_save(lambda save: _selection(save, club_uid))

    def _with_save(self, read: Callable[[Any], Any]) -> Any:
        fmsave = _load_fmsave()
        before = self._signature(SAVE_INVALID_ERROR)
        try:
            handle = fmsave.open(self._path)
        except Exception as error:
            raise ValueError(SAVE_INVALID_ERROR) from error
        try:
            with handle as save:
                return self._translate(read, save)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(SAVE_INVALID_ERROR) from error
        finally:
            after = self._signature(SAVE_CHANGED_ERROR)
            if after != before:
                raise ValueError(SAVE_CHANGED_ERROR)

    @staticmethod
    def _translate(read: Callable[[Any], Any], save: Any) -> Any:
        try:
            return read(save)
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(SAVE_INVALID_ERROR) from error

    def _signature(self, message: str) -> tuple[int, int]:
        try:
            status = self._path.stat()
        except OSError as error:
            raise ValueError(message) from error
        return (status.st_size, status.st_mtime_ns)
