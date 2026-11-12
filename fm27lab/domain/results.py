"""Pure result metrics for completed match runs."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

Z_95 = 1.959963984540054


def _score(run: Mapping[str, Any]) -> tuple[int, int]:
    value: Any = None
    result = run.get("result")
    if isinstance(result, Mapping):
        value = result.get("score")
    if value is None:
        value = run.get("score")
    if value is None and "home_goals" in run and "away_goals" in run:
        value = [run.get("home_goals"), run.get("away_goals")]
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 2
        or any(type(item) is not int or item < 0 for item in value)
    ):
        raise ValueError("比赛比分格式无效")
    return int(value[0]), int(value[1])


def _teams(run: Mapping[str, Any], side: int) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    statistics = run.get("statistics")
    if not isinstance(statistics, Mapping):
        return None
    teams = statistics.get("teams")
    if not isinstance(teams, (list, tuple)) or len(teams) != 2:
        return None
    if not isinstance(teams[side], Mapping) or not isinstance(teams[1 - side], Mapping):
        return None
    return teams[side], teams[1 - side]


def _number(value: Any) -> float | None:
    if type(value) is int or type(value) is float:
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_runs(runs: Sequence[Mapping[str, Any]], side: int = 0) -> dict[str, Any] | None:
    if type(side) is not int or side not in (0, 1):
        raise ValueError("side 必须为 0 或 1")
    if not runs:
        return None
    raw_scores = [_score(run) for run in runs]
    scores = [(first, second) if side == 0 else (second, first) for first, second in raw_scores]
    n = len(scores)
    wins = sum(first > second for first, second in scores)
    draws = sum(first == second for first, second in scores)
    goals_for = sum(first for first, second in scores)
    goals_against = sum(second for first, second in scores)
    win_rate = wins / n
    denominator = 1 + Z_95 * Z_95 / n
    center = (win_rate + Z_95 * Z_95 / (2 * n)) / denominator
    half = Z_95 * math.sqrt(win_rate * (1 - win_rate) / n + Z_95 * Z_95 / (4 * n * n)) / denominator
    xg: list[float] = []
    xga: list[float] = []
    possession: list[float] = []
    shots: list[float] = []
    passes = 0.0
    completed = 0.0
    has_pass_stats = False
    for run in runs:
        pair = _teams(run, side)
        if pair is None:
            continue
        own, opponent = pair
        own_xg = _number(own.get("xg"))
        opponent_xg = _number(opponent.get("xg"))
        if own_xg is not None:
            xg.append(own_xg)
        if opponent_xg is not None:
            xga.append(opponent_xg)
        for bucket, key in ((possession, "possession"), (shots, "shots")):
            value = _number(own.get(key))
            if value is not None:
                bucket.append(value)
        own_passes = _number(own.get("passes"))
        own_completed = _number(own.get("completed_passes"))
        if own_passes is not None and own_completed is not None:
            has_pass_stats = True
            passes += own_passes
            completed += own_completed
    return {
        "n": n,
        "wins": wins,
        "draws": draws,
        "losses": n - wins - draws,
        "win_rate": win_rate,
        "win_interval": [max(0.0, center - half), min(1.0, center + half)],
        "goals_for": goals_for / n,
        "goals_against": goals_against / n,
        "points": (3 * wins + draws) / n,
        "xg": _average(xg),
        "xga": _average(xga),
        "possession": _average(possession),
        "shots": _average(shots),
        "pass_completion": completed / passes if passes > 0 else (0.0 if has_pass_stats else None),
    }


def paired_goal_difference(runs: Sequence[Mapping[str, Any]], side: int = 0) -> dict[str, Any]:
    if type(side) is not int or side not in (0, 1):
        raise ValueError("side 必须为 0 或 1")
    pairs: dict[int, dict[str, tuple[int, int]]] = {}
    for run in runs:
        seed = run.get("seed")
        if type(seed) is not int:
            raise ValueError("配对比赛缺少整数种子")
        variant = run.get("variant")
        if variant not in ("A", "B"):
            raise ValueError("配对比赛必须包含 A/B 变体")
        group = pairs.setdefault(seed, {})
        if variant in group:
            raise ValueError(f"种子 {seed} 的 {variant} 变体重复")
        score = _score(run)
        group[variant] = score if side == 0 else (score[1], score[0])
    complete = [(value["A"], value["B"]) for value in pairs.values() if "A" in value and "B" in value]
    deltas = [(second[0] - second[1]) - (first[0] - first[1]) for first, second in complete]
    return {
        "n": len(deltas),
        "goal_difference_delta": sum(deltas) / len(deltas) if deltas else None,
    }
