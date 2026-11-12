"""Away tactic pool selection and draw policy.

This module owns weighted draws, rotation order and completed-draw accounting.
It does not validate full tactics or apply tactics to engine scenarios.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any

MAX_WEIGHT = 1000
MAX_ENTRIES = 128
MAX_ROTATION_MATCHES = 10000
DEFAULT_ATTRIBUTE_VALUE = 15
PROFILE = "away-tactic-pool-v1"


def _integer(value: Any, low: int, high: int, label: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}必须为 {low}–{high} 的整数")
    return value


def probabilities(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, int | float]]:
    if not isinstance(entries, (list, tuple)) or not entries:
        raise ValueError("客队战术池没有可抽取的战术")
    if len(entries) > MAX_ENTRIES:
        raise ValueError("客队战术池最多允许 128 套战术")
    weights: list[int] = []
    for index, item in enumerate(entries, 1):
        if not isinstance(item, Mapping):
            raise ValueError(f"第 {index} 套客队战术格式无效")
        weights.append(_integer(item.get("weight", 1), 1, MAX_WEIGHT, f"第 {index} 套客队战术权重"))
    total = sum(weights)
    return [{"weight": weight, "probability": weight / total} for weight in weights]


def draw_index(entries: Sequence[Mapping[str, Any]], seed: int, salt: str) -> int:
    if type(seed) is not int:
        raise ValueError("随机种子必须为整数")
    rows = probabilities(entries)
    target = random.Random(f"{salt}:{seed}").random()
    cumulative = 0.0
    for index, row in enumerate(rows):
        cumulative += row["probability"]
        if target < cumulative:
            return index
    return len(rows) - 1


def rotation_matches(entry_count: int, rounds: int) -> int:
    count = _integer(entry_count, 0, MAX_ENTRIES, "客队战术数量")
    round_count = _integer(rounds, 1, 1000, "轮战轮数")
    total = count * round_count
    if total > MAX_ROTATION_MATCHES:
        raise ValueError(
            f"轮战每方案最多 {MAX_ROTATION_MATCHES} 场，当前 {count} 套 × {round_count} 轮 = {total} 场"
        )
    return total


def rotation_message(entry_count: int, rounds: int, count: int) -> str:
    return (
        f"轮战模式每方案需要 {entry_count} 套 × {rounds} 轮 = {entry_count * rounds} 场，当前种子数为 {count}"
    )


def draws(
    entries: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    salt: str,
    *,
    rotation_enabled: bool = False,
    rounds: int = 1,
) -> dict[int, int]:
    probabilities(entries)
    if not isinstance(seeds, (list, tuple)):
        raise ValueError("随机种子列表格式无效")
    if any(type(seed) is not int for seed in seeds):
        raise ValueError("随机种子必须为整数")
    if rotation_enabled:
        if len(set(seeds)) != len(seeds):
            raise ValueError("轮战模式的种子必须唯一")
        expected = rotation_matches(len(entries), rounds)
        if len(seeds) != expected:
            raise ValueError(rotation_message(len(entries), rounds, len(seeds)))
        return {seed: index % len(entries) for index, seed in enumerate(seeds)}
    return {seed: draw_index(entries, seed, salt) for seed in seeds}


def completed_draw_counts(runs: Sequence[Mapping[str, Any]], entry_count: int) -> dict[str, int]:
    entry_count = _integer(entry_count, 0, MAX_ENTRIES, "客队战术数量")
    counts = {str(index): 0 for index in range(entry_count)}
    by_seed: dict[int, int] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            raise ValueError("比赛记录格式无效")
        entry = run.get("tactic_pool_entry")
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise ValueError("客队战术记录格式无效")
        index = _integer(entry.get("index"), 0, entry_count - 1, "客队战术序号")
        seed = run.get("seed")
        if type(seed) is not int:
            raise ValueError("比赛记录缺少整数种子")
        if seed in by_seed and by_seed[seed] != index:
            raise ValueError("同种子对照的客队战术不一致")
        by_seed[seed] = index
    for index in by_seed.values():
        counts[str(index)] += 1
    return counts


def _flag(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(label + "必须为布尔值")
    return value


def _mode_value(value: bool | Mapping[str, Any], key: str, label: str) -> tuple[bool, Any]:
    if isinstance(value, Mapping):
        return _flag(value.get("enabled", False), label), value.get(key)
    return _flag(value, label), None


def summary(
    entries: Sequence[Mapping[str, Any]],
    *,
    rotation: bool | Mapping[str, Any] = False,
    rounds: int = 1,
    uniform: Mapping[str, Any] | None = None,
    real: bool | Mapping[str, Any] = False,
    salt: str | None = None,
    profile: str = PROFILE,
    enabled: bool = False,
) -> dict[str, Any]:
    if profile != PROFILE:
        raise ValueError("客队战术池版本无效")
    rows = probabilities(entries)
    rotation_enabled, rotation_rounds = _mode_value(rotation, "rounds", "轮战模式开关")
    real_enabled, _ = _mode_value(real, "enabled", "真实名单开关")
    if rotation_rounds is not None:
        rounds = rotation_rounds
    rounds = _integer(rounds, 1, 1000, "轮战轮数")
    if rotation_enabled:
        rotation_matches(len(entries), rounds)
    raw_uniform = dict(uniform or {})
    uniform_value = {
        "enabled": _flag(raw_uniform.get("enabled", True), "统一属性开关"),
        "attribute_value": _integer(
            raw_uniform.get("attribute_value", DEFAULT_ATTRIBUTE_VALUE),
            1,
            20,
            "统一属性值",
        ),
    }
    value = {
        "profile": str(profile),
        "enabled": _flag(enabled, "客队战术池开关"),
        "mode": "rotation" if rotation_enabled else "random",
        "rounds": rounds,
        "players": "real" if real_enabled else "uniform",
        "uniform": uniform_value,
        "entries": [
            {
                "index": index,
                "name": _entry_name(item, index),
                "weight": row["weight"],
                "probability": None if rotation_enabled else row["probability"],
                "roster": item.get("roster") is not None,
            }
            for index, (item, row) in enumerate(zip(entries, rows, strict=False))
        ],
    }
    if salt is not None:
        value["salt"] = str(salt)
    return value


def _entry_name(item: Mapping[str, Any], index: int) -> str:
    name = item.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(char) < 32 for char in name):
        raise ValueError(f"第 {index + 1} 套客队战术名称无效")
    return name.strip()
