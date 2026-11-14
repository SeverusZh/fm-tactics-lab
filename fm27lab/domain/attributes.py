"""Attribute grouping, bulk profile edits and undo snapshots for players."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from .roster import POSITION_INDEX, canonical_position

ATTRIBUTE_COUNT = 69
POSITION_ATTRIBUTE_COUNT = 15

TECHNICAL = frozenset({15, 16, 17, 18, 19, 20, 22, 23, 24, 37, 38, 42, 45, 50})
MENTAL = frozenset({21, 25, 32, 33, 35, 41, 43, 44, 55, 58, 60, 66, 67, 68})
PHYSICAL = frozenset({49, 51, 52, 53, 54, 57, 61, 65})
GOALKEEPING = frozenset({26, 27, 28, 29, 30, 31, 34, 36, 46, 47, 48})
POSITION = frozenset(range(POSITION_ATTRIBUTE_COUNT))
HIDDEN = (
    frozenset(range(POSITION_ATTRIBUTE_COUNT, ATTRIBUTE_COUNT)) - TECHNICAL - MENTAL - PHYSICAL - GOALKEEPING
)

VISIBLE_GROUPS = ("technical", "mental", "physical", "goalkeeping")
GROUP_ORDER = ("technical", "mental", "physical", "goalkeeping", "hidden", "position")
PERSONALITY_KEYS = (
    "professionalism",
    "loyalty",
    "sportsmanship",
    "temperament",
    "pressure",
    "ambition",
    "adaptability",
)

_GROUP_INDICES: dict[str, frozenset[int]] = {
    "technical": TECHNICAL,
    "mental": MENTAL,
    "physical": PHYSICAL,
    "goalkeeping": GOALKEEPING,
    "hidden": HIDDEN,
    "position": POSITION,
}
_GROUP_BY_INDEX = {index: group for group in GROUP_ORDER for index in _GROUP_INDICES[group]}


@dataclass
class _PlayerState:
    player: MutableMapping[str, Any]
    uid: int | str | None
    attributes: list[int]
    profile: MutableMapping[str, Any] | None


def _index(value: Any) -> int:
    if type(value) is not int or not 0 <= value < ATTRIBUTE_COUNT:
        raise ValueError("属性索引必须是 0–68 的整数")
    return value


def attribute_group(index: int) -> str:
    """Return the group name that owns one of the 69 attribute indices."""
    return _GROUP_BY_INDEX[_index(index)]


def group_indices(group: str) -> frozenset[int]:
    """Return the immutable index set of one attribute group."""
    if not isinstance(group, str) or group not in _GROUP_INDICES:
        raise ValueError("未知属性分组")
    return _GROUP_INDICES[group]


def _boolean(value: Any, message: str) -> bool:
    if type(value) is not bool:
        raise ValueError(message)
    return value


def _valid_uid(uid: Any) -> bool:
    if type(uid) is int:
        return True
    if not isinstance(uid, str) or not uid or uid != uid.strip():
        return False
    return not any(ord(char) < 32 for char in uid)


def _player_uid(player: MutableMapping[str, Any], label: str) -> int | str:
    uid = player.get("source_uid")
    if not _valid_uid(uid):
        raise ValueError(label + "缺少有效的 source_uid")
    return uid


def _player_attributes(player: MutableMapping[str, Any], label: str) -> list[int]:
    attributes = player.get("attributes")
    if not isinstance(attributes, list) or len(attributes) != ATTRIBUTE_COUNT:
        raise ValueError(label + "属性必须为 69 项")
    if any(type(value) is not int for value in attributes):
        raise ValueError(label + "属性必须为整数")
    if any(not 0 <= value <= 20 for value in attributes[:POSITION_ATTRIBUTE_COUNT]):
        raise ValueError(label + "位置熟练度超出范围")
    if any(not 1 <= value <= 100 for value in attributes[POSITION_ATTRIBUTE_COUNT:]):
        raise ValueError(label + "属性超出范围")
    return attributes


def _player_profile(player: MutableMapping[str, Any], label: str) -> MutableMapping[str, Any] | None:
    profile = player.get("native_profile")
    if profile is None:
        return None
    if not isinstance(profile, MutableMapping):
        raise ValueError(label + "扩展输入格式无效")
    for key in PERSONALITY_KEYS:
        if key not in profile:
            continue
        value = profile[key]
        if type(value) is not int or not 1 <= value <= 20:
            raise ValueError("球员性格值无效")
    return profile


def _player_state(player: Any, *, label: str, require_uid: bool) -> _PlayerState:
    if not isinstance(player, MutableMapping):
        raise ValueError(label + "格式无效")
    uid = _player_uid(player, label) if require_uid else None
    return _PlayerState(
        player,
        uid,
        _player_attributes(player, label),
        _player_profile(player, label),
    )


def _player_states(players: Any, *, require_uid: bool) -> list[_PlayerState]:
    if isinstance(players, (str, bytes, bytearray)) or not isinstance(players, Sequence):
        raise ValueError("球员名单格式无效")
    states = [
        _player_state(player, label=f"第 {index + 1} 名球员", require_uid=require_uid)
        for index, player in enumerate(players)
    ]
    if require_uid:
        uids = [state.uid for state in states]
        if len(set(uids)) != len(uids):
            raise ValueError("球员 source_uid 重复")
    return states


def _selected_indices(groups: Any, *, allow_position: bool) -> list[int]:
    if isinstance(groups, (str, bytes, bytearray)) or not isinstance(groups, Sequence):
        raise ValueError("属性分组必须是名称序列")
    names: list[str] = []
    for group in groups:
        if not isinstance(group, str) or group not in _GROUP_INDICES:
            raise ValueError("未知属性分组")
        if group == "position" and not allow_position:
            raise ValueError("位置熟练度请使用位置批量接口")
        if group not in names:
            names.append(group)
    indices: set[int] = set()
    for name in names:
        indices |= _GROUP_INDICES[name]
    return sorted(indices)


def _display_value(value: Any) -> float:
    if type(value) not in (int, float):
        raise ValueError("属性显示值必须是 1–20 的数字")
    number = float(value)
    if not math.isfinite(number) or not 1 <= number <= 20:
        raise ValueError("属性显示值必须在 1–20 之间")
    return number


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def _internal_value(value: float) -> int:
    return max(1, min(100, _round_half_up(value * 5)))


def _position_value(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 20:
        raise ValueError("位置熟练度必须是 0–20 的整数")
    return value


def _personality_value(value: float) -> int:
    return max(1, min(20, _round_half_up(value)))


def _personality_state(profile: MutableMapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if profile is None:
        return {key: {"present": False, "value": None} for key in PERSONALITY_KEYS}
    return {key: {"present": key in profile, "value": profile.get(key)} for key in PERSONALITY_KEYS}


def _snapshot(
    indices: list[int],
    include_personality: bool,
    states: Sequence[_PlayerState],
) -> dict[str, Any]:
    return {
        "indices": list(indices),
        "include_personality": include_personality,
        "players": [
            {
                "source_uid": state.uid,
                "profile_present": state.profile is not None,
                "attributes": [state.attributes[index] for index in indices],
                "personality": _personality_state(state.profile) if include_personality else {},
            }
            for state in states
        ],
    }


def apply_bulk_attributes(
    players: Sequence[MutableMapping[str, Any]],
    *,
    value: float,
    groups: Sequence[str] = VISIBLE_GROUPS,
    include_personality: bool = False,
) -> dict[str, Any]:
    """Set every attribute index in the selected groups to one display value.

    Hidden attributes, personality and position familiarity stay untouched
    unless the hidden group is selected or the personality switch is enabled.
    """
    indices = _selected_indices(groups, allow_position=False)
    number = _display_value(value)
    with_personality = _boolean(include_personality, "性格开关必须为布尔值")
    states = _player_states(players, require_uid=True)
    snapshot = _snapshot(indices, with_personality, states)
    internal = _internal_value(number)
    personality = _personality_value(number)
    for state in states:
        for index in indices:
            state.attributes[index] = internal
        if with_personality:
            profile = state.profile
            if profile is None:
                profile = {}
                state.player["native_profile"] = profile
                state.profile = profile
            for key in PERSONALITY_KEYS:
                profile[key] = personality
    return snapshot


def _position_index(position: Any) -> int:
    if type(position) is int:
        if not 0 <= position < POSITION_ATTRIBUTE_COUNT:
            raise ValueError("位置索引必须在 0–14 之间")
        return position
    if isinstance(position, str):
        index = POSITION_INDEX.get(canonical_position(position))
        if index is None:
            raise ValueError("位置名称无效")
        return index
    raise ValueError("位置必须是 0–14 的索引或位置名称")


def apply_position_attributes(
    players: Sequence[MutableMapping[str, Any]],
    *,
    position: str | int,
    value: int,
) -> dict[str, Any]:
    """Set one position familiarity index for every player in the roster."""
    index = _position_index(position)
    number = _position_value(value)
    states = _player_states(players, require_uid=True)
    snapshot = _snapshot([index], False, states)
    for state in states:
        state.attributes[index] = number
    return snapshot


def apply_attribute_cells(
    players: Sequence[MutableMapping[str, Any]],
    *,
    values: Mapping[int, float],
) -> dict[str, Any]:
    """Set exact attribute cells from a mapping of index to display value.

    Position familiarity indices take the 0–20 integer that the position
    operation uses; every other index takes the 1–20 display value of bulk
    edits and is stored on the internal 5–100 scale.
    """
    if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Mapping):
        raise ValueError("属性值必须是索引到显示值的对象")
    if not values:
        raise ValueError("至少需要一个属性值")
    converted: dict[int, int] = {}
    for index, value in values.items():
        target = _index(index)
        if target < POSITION_ATTRIBUTE_COUNT:
            converted[target] = _position_value(value)
        else:
            converted[target] = _internal_value(_display_value(value))
    indices = sorted(converted)
    states = _player_states(players, require_uid=True)
    snapshot = _snapshot(indices, False, states)
    for state in states:
        for index in indices:
            state.attributes[index] = converted[index]
    return snapshot


def _snapshot_layout(snapshot: Mapping[str, Any]) -> tuple[list[int], list[Any]]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("撤销记录格式无效")
    indices = snapshot.get("indices")
    if not isinstance(indices, list) or len(set(indices)) != len(indices):
        raise ValueError("撤销记录格式无效")
    if any(type(index) is not int or not 0 <= index < ATTRIBUTE_COUNT for index in indices):
        raise ValueError("撤销记录格式无效")
    if type(snapshot.get("include_personality")) is not bool:
        raise ValueError("撤销记录格式无效")
    entries = snapshot.get("players")
    if not isinstance(entries, list):
        raise ValueError("撤销记录格式无效")
    return indices, entries


def _restored_personality(entry: Mapping[str, Any]) -> dict[str, tuple[bool, Any]]:
    personality = entry.get("personality", {})
    if not isinstance(personality, Mapping):
        raise ValueError("撤销记录格式无效")
    restored: dict[str, tuple[bool, Any]] = {}
    for key, saved in personality.items():
        if not isinstance(key, str) or key not in PERSONALITY_KEYS or not isinstance(saved, Mapping):
            raise ValueError("撤销记录格式无效")
        present = saved.get("present")
        if type(present) is not bool:
            raise ValueError("撤销记录格式无效")
        value = saved.get("value")
        if present and (type(value) is not int or not 1 <= value <= 20):
            raise ValueError("撤销记录格式无效")
        restored[key] = (present, value)
    return restored


def _old_attributes(indices: list[int], entry: Mapping[str, Any]) -> list[int]:
    old = entry.get("attributes")
    if not isinstance(old, list) or len(old) != len(indices) or any(type(item) is not int for item in old):
        raise ValueError("撤销记录格式无效")
    for index, value in zip(indices, old, strict=True):
        if index < POSITION_ATTRIBUTE_COUNT:
            valid = 0 <= value <= 20
        else:
            valid = 1 <= value <= 100
        if not valid:
            raise ValueError("撤销记录格式无效")
    return old


def undo_bulk(
    players: Sequence[MutableMapping[str, Any]],
    snapshot: Mapping[str, Any],
) -> None:
    """Restore attributes, personality and native_profile presence from a snapshot."""
    states = _player_states(players, require_uid=True)
    indices, entries = _snapshot_layout(snapshot)
    if len(entries) != len(states):
        raise ValueError("名单已变化，无法撤销")
    prepared: list[tuple[list[int], dict[str, tuple[bool, Any]], bool]] = []
    for state, entry in zip(states, entries, strict=True):
        if not isinstance(entry, Mapping):
            raise ValueError("撤销记录格式无效")
        if entry.get("source_uid") != state.uid:
            raise ValueError("名单已变化，无法撤销")
        profile_present = entry.get("profile_present")
        if type(profile_present) is not bool:
            raise ValueError("撤销记录格式无效")
        old = _old_attributes(indices, entry)
        personality = _restored_personality(entry)
        if not profile_present and any(present for present, _ in personality.values()):
            raise ValueError("撤销记录格式无效")
        prepared.append((old, personality, profile_present))
    for state, (old, personality, profile_present) in zip(states, prepared, strict=True):
        for index, previous in zip(indices, old, strict=True):
            state.attributes[index] = previous
        for key, (present, previous) in personality.items():
            if present:
                profile = state.profile
                if profile is None:
                    profile = {}
                    state.player["native_profile"] = profile
                    state.profile = profile
                profile[key] = previous
            elif state.profile is not None:
                state.profile.pop(key, None)
        if not profile_present:
            state.player.pop("native_profile", None)


def copy_player_profile(
    source: MutableMapping[str, Any],
    target: MutableMapping[str, Any],
    *,
    groups: Sequence[str] = ("technical", "mental", "physical", "goalkeeping", "hidden"),
    copy_personality: bool = True,
) -> dict[str, Any]:
    """Copy selected attribute groups and personality from a reference player.

    The source is never modified. The snapshot restores the target state.
    """
    indices = _selected_indices(groups, allow_position=True)
    with_personality = _boolean(copy_personality, "性格开关必须为布尔值")
    source_state = _player_state(source, label="参考球员", require_uid=False)
    target_state = _player_state(target, label="目标球员", require_uid=True)
    snapshot = _snapshot(indices, with_personality, [target_state])
    for index in indices:
        target_state.attributes[index] = source_state.attributes[index]
    if with_personality:
        source_profile = source_state.profile or {}
        target_profile = target_state.profile
        for key in PERSONALITY_KEYS:
            if key in source_profile:
                if target_profile is None:
                    target_profile = {}
                    target_state.player["native_profile"] = target_profile
                target_profile[key] = source_profile[key]
            elif target_profile is not None:
                target_profile.pop(key, None)
    return snapshot


def _foot_index(value: Any) -> int:
    if type(value) is not int or not POSITION_ATTRIBUTE_COUNT <= value < ATTRIBUTE_COUNT:
        raise ValueError("左右脚索引必须是 15–68 的整数")
    return value


def _foot_value(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 20:
        raise ValueError(label + "属性值必须是 1–20 的整数")
    return value


def pair_feet(
    target: MutableMapping[str, Any],
    *,
    left_index: int,
    right_index: int,
    preferred: str,
    preferred_value: int,
    weaker_value: int,
) -> None:
    """Write a preferred/weaker foot pair into hidden attribute indices.

    The foot indices come from the caller; nothing assumes a fixed slot.
    """
    left = _foot_index(left_index)
    right = _foot_index(right_index)
    if left == right:
        raise ValueError("左右脚索引不能相同")
    if not isinstance(preferred, str) or preferred not in ("left", "right"):
        raise ValueError("惯用脚必须是 left 或 right")
    strong = _foot_value(preferred_value, "惯用脚")
    weak = _foot_value(weaker_value, "逆足")
    if strong == weak or weak > strong:
        raise ValueError("左右脚配对值无效")
    state = _player_state(target, label="目标球员", require_uid=False)
    if preferred == "left":
        left_value, right_value = strong, weak
    else:
        left_value, right_value = weak, strong
    state.attributes[left] = left_value
    state.attributes[right] = right_value
