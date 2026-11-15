from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from fm27lab.domain.results import _number, _score, _teams

DEFAULT_REPS = 2000
DEFAULT_ALPHA = 0.05
DEFAULT_SEED = 20261108
MAX_REPS = 20000
ROUND_DIGITS = 4


def _validate_reps(reps: int) -> None:
    if type(reps) is not int or not 1 <= reps <= MAX_REPS:
        raise ValueError(f"reps 必须为 1–{MAX_REPS} 的整数")


def _validate_alpha(alpha: float) -> None:
    if type(alpha) not in (int, float) or not 0 < alpha < 1:
        raise ValueError("alpha 必须满足 0 < alpha < 1")


def _validate_values(values: Sequence[Any]) -> None:
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("values 必须全部为有限数值")


def bootstrap_ci(
    values: Sequence[float],
    *,
    reps: int = DEFAULT_REPS,
    alpha: float = DEFAULT_ALPHA,
    seed: int = DEFAULT_SEED,
) -> list[float] | None:
    _validate_reps(reps)
    _validate_alpha(alpha)
    samples = list(values)
    _validate_values(samples)
    if not samples:
        return None
    rng = random.Random(seed)
    size = len(samples)
    means = sorted(
        sum(samples[rng.randrange(size)] for _ in range(size)) / size for _ in range(reps)
    )
    return [means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps)]]


def _pool_signature(pool: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (pool.get("mode") or "random", pool.get("rounds") or 1, pool.get("players") or "uniform")


def pool_pairing(
    baseline: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    seeds: Sequence[int],
) -> tuple[bool, str | None, dict[str, Any]]:
    common = [seed for seed in seeds if type(seed) is int]
    info: dict[str, Any] = {
        "common_seeds": len(common),
        "draw_mismatches": None,
        "mismatched_seeds": [],
        "missing_seeds": [],
    }
    if baseline is None and candidate is None:
        return True, None, info
    if baseline is None:
        return False, "基线任务未使用客队战术池，候选任务使用了客队战术池", info
    if candidate is None:
        return False, "候选任务未使用客队战术池，基线任务使用了客队战术池", info
    if _pool_signature(baseline) != _pool_signature(candidate):
        return False, "两个任务的客队战术池模式不同，同种子分配无法对齐", info
    if list(baseline.get("entries") or []) != list(candidate.get("entries") or []):
        return False, "两个任务的客队战术池条目不同，同种子分配无法对齐", info
    if not common:
        return False, "没有同种子的已完成比赛，无法核对客队战术池分配", info
    baseline_draws = baseline.get("draws") or {}
    candidate_draws = candidate.get("draws") or {}
    missing = [
        seed for seed in common if seed not in baseline_draws or seed not in candidate_draws
    ]
    if missing:
        info["missing_seeds"] = missing[:20]
        return False, "缺少同种子的客队战术池分配记录，不能配对", info
    mismatched = [seed for seed in common if baseline_draws[seed] != candidate_draws[seed]]
    if mismatched:
        info["draw_mismatches"] = len(mismatched)
        info["mismatched_seeds"] = mismatched[:20]
        return (
            False,
            f"客队战术池分配不同：{len(mismatched)}/{len(common)} 个同种子场次使用了不同战术",
            info,
        )
    return True, None, info


def _oriented_score(score: tuple[int, int], side: int) -> tuple[int, int]:
    return score if side == 0 else (score[1], score[0])


def _win_value(goals_for: int, goals_against: int) -> float:
    if goals_for > goals_against:
        return 1.0
    if goals_for == goals_against:
        return 0.5
    return 0.0


def _points_value(goals_for: int, goals_against: int) -> float:
    if goals_for > goals_against:
        return 3.0
    if goals_for == goals_against:
        return 1.0
    return 0.0


def _xgd(run: Mapping[str, Any], side: int) -> float | None:
    teams = _teams(run, side)
    if teams is None:
        return None
    own, opponent = teams
    own_xg = _number(own.get("xg"))
    opponent_xg = _number(opponent.get("xg"))
    if own_xg is None or opponent_xg is None:
        return None
    return own_xg - opponent_xg


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), ROUND_DIGITS)


def _interval(values: Sequence[float], reps: int) -> list[float] | None:
    interval = bootstrap_ci(values, reps=reps)
    if interval is None:
        return None
    return [round(value, ROUND_DIGITS) for value in interval]


def paired_deltas(
    baseline_by_seed: Mapping[int, Mapping[str, Any]],
    candidate_by_seed: Mapping[int, Mapping[str, Any]],
    side: int,
    *,
    reps: int = DEFAULT_REPS,
) -> dict[str, Any]:
    if type(side) is not int or side not in (0, 1):
        raise ValueError("side 必须为 0 或 1")
    _validate_reps(reps)
    shared = sorted(
        seed
        for seed in set(baseline_by_seed) & set(candidate_by_seed)
        if type(seed) is int
    )
    win_values: list[float] = []
    points_values: list[float] = []
    goal_difference_values: list[float] = []
    xgd_values: list[float] = []
    for seed in shared:
        baseline_run = baseline_by_seed[seed]
        candidate_run = candidate_by_seed[seed]
        baseline_goals_for, baseline_goals_against = _oriented_score(
            _score(baseline_run), side
        )
        candidate_goals_for, candidate_goals_against = _oriented_score(
            _score(candidate_run), side
        )
        win_values.append(
            _win_value(candidate_goals_for, candidate_goals_against)
            - _win_value(baseline_goals_for, baseline_goals_against)
        )
        points_values.append(
            _points_value(candidate_goals_for, candidate_goals_against)
            - _points_value(baseline_goals_for, baseline_goals_against)
        )
        goal_difference_values.append(
            (candidate_goals_for - candidate_goals_against)
            - (baseline_goals_for - baseline_goals_against)
        )
        baseline_xgd = _xgd(baseline_run, side)
        candidate_xgd = _xgd(candidate_run, side)
        if baseline_xgd is not None and candidate_xgd is not None:
            xgd_values.append(candidate_xgd - baseline_xgd)
    return {
        "seeds": len(shared),
        "win_rate_delta": _mean(win_values),
        "win_rate_delta_ci": _interval(win_values, reps),
        "points_delta": _mean(points_values),
        "points_delta_ci": _interval(points_values, reps),
        "goal_difference_delta": _mean(goal_difference_values),
        "goal_difference_delta_ci": _interval(goal_difference_values, reps),
        "xgd_delta": _mean(xgd_values),
        "xgd_delta_ci": _interval(xgd_values, reps),
    }
