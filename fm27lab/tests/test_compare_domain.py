from __future__ import annotations

import math
import random

import pytest

from fm27lab.domain.compare import bootstrap_ci, paired_deltas, pool_pairing


def reference_ci(values: list[float], *, reps: int, alpha: float = 0.05, seed: int = 20261108) -> list[float]:
    rng = random.Random(seed)
    size = len(values)
    means = sorted(sum(values[rng.randrange(size)] for _ in range(size)) / size for _ in range(reps))
    return [means[int(alpha / 2 * reps)], means[int((1 - alpha / 2) * reps)]]


def test_bootstrap_ci_matches_legacy_sampling():
    values = [0.0, 0.5, 1.0, 0.25, -0.5]

    interval = bootstrap_ci(values, reps=200)

    assert interval == reference_ci(values, reps=200)
    assert interval is not None
    assert interval[0] <= interval[1]


def test_bootstrap_ci_alpha_controls_interval_boundaries():
    values = [0.0, 0.5, 1.0, 0.25, -0.5]

    narrow = bootstrap_ci(values, reps=200, alpha=0.2)
    wide = bootstrap_ci(values, reps=200, alpha=0.1)

    assert narrow == reference_ci(values, reps=200, alpha=0.2)
    assert wide == reference_ci(values, reps=200, alpha=0.1)
    assert narrow[0] > wide[0]
    assert narrow[1] < wide[1]


def test_bootstrap_ci_is_deterministic_and_seeded():
    values = [0.0, 0.5, 1.0, 0.25, -0.5]

    assert bootstrap_ci(values, reps=100) == bootstrap_ci(values, reps=100)
    assert bootstrap_ci(values, reps=100, seed=7) == reference_ci(values, reps=100, seed=7)


def test_bootstrap_ci_returns_none_for_empty_sequence():
    assert bootstrap_ci([]) is None


def test_bootstrap_ci_constant_values_collapse_to_point_interval():
    assert bootstrap_ci([2.0] * 5, reps=100) == [2.0, 2.0]


def test_bootstrap_ci_single_rep_is_a_point_interval():
    interval = bootstrap_ci([1.0, 2.0, 3.0], reps=1)

    assert interval is not None
    assert interval[0] == interval[1]


@pytest.mark.parametrize("reps", [0, -1, 20001, 2.5, "200", True])
def test_bootstrap_ci_rejects_invalid_reps(reps):
    with pytest.raises(ValueError):
        bootstrap_ci([1.0, 2.0], reps=reps)


@pytest.mark.parametrize("alpha", [0, 1, -0.1, 1.5])
def test_bootstrap_ci_rejects_invalid_alpha(alpha):
    with pytest.raises(ValueError):
        bootstrap_ci([1.0, 2.0], alpha=alpha)


@pytest.mark.parametrize("values", [[1.0, math.nan], [math.inf], [1.0, -math.inf]])
def test_bootstrap_ci_rejects_non_finite_values(values):
    with pytest.raises(ValueError):
        bootstrap_ci(values)


def test_bootstrap_ci_interval_is_ascending():
    interval = bootstrap_ci([0.0, 1.0] * 20, reps=500)

    assert interval is not None
    assert interval[0] <= interval[1]
    assert all(math.isfinite(item) for item in interval)


def entry(
    index: int,
    name: str | None = None,
    *,
    weight: int = 1,
    roster: bool = False,
) -> dict:
    return {
        "index": index,
        "name": name or f"客队战术 {index + 1}",
        "weight": weight,
        "roster": roster,
    }


def view(
    *,
    mode: str = "random",
    rounds: int = 1,
    players: str = "uniform",
    entries: list[dict] | None = None,
    draws: dict[int, int] | None = None,
) -> dict:
    return {
        "mode": mode,
        "rounds": rounds,
        "players": players,
        "entries": [entry(0), entry(1)] if entries is None else entries,
        "draws": {} if draws is None else draws,
    }


def test_pool_pairing_without_pools_is_comparable():
    comparable, reason, info = pool_pairing(None, None, [1, 2, 3])

    assert comparable is True
    assert reason is None
    assert info["common_seeds"] == 3
    assert info["draw_mismatches"] is None
    assert info["mismatched_seeds"] == []
    assert info["missing_seeds"] == []


def test_pool_pairing_rejects_pool_only_on_candidate():
    comparable, reason, info = pool_pairing(None, view(draws={1: 0}), [1])

    assert comparable is False
    assert reason == "基线任务未使用客队战术池，候选任务使用了客队战术池"
    assert info["common_seeds"] == 1


def test_pool_pairing_rejects_pool_only_on_baseline():
    comparable, reason, info = pool_pairing(view(draws={1: 0}), None, [1])

    assert comparable is False
    assert reason == "候选任务未使用客队战术池，基线任务使用了客队战术池"
    assert info["common_seeds"] == 1


@pytest.mark.parametrize(
    "changed",
    [{"mode": "rotation"}, {"rounds": 2}, {"players": "real"}],
)
def test_pool_pairing_rejects_mode_differences(changed):
    baseline = view(draws={1: 0})
    candidate = view(**changed, draws={1: 0})

    comparable, reason, info = pool_pairing(baseline, candidate, [1])

    assert comparable is False
    assert reason == "两个任务的客队战术池模式不同，同种子分配无法对齐"
    assert info["common_seeds"] == 1


def test_pool_pairing_rejects_entry_differences():
    baseline = view(entries=[entry(0, "甲")])
    candidate = view(entries=[entry(0, "乙")])

    comparable, reason, info = pool_pairing(baseline, candidate, [1])

    assert comparable is False
    assert reason == "两个任务的客队战术池条目不同，同种子分配无法对齐"


@pytest.mark.parametrize("changed", [{"weight": 2}, {"roster": True}])
def test_pool_pairing_rejects_entry_weight_or_roster_differences(changed):
    baseline = view(entries=[entry(0, "甲")])
    candidate = view(entries=[entry(0, "甲", **changed)])

    comparable, reason, info = pool_pairing(baseline, candidate, [1])

    assert comparable is False
    assert reason == "两个任务的客队战术池条目不同，同种子分配无法对齐"
    assert info["common_seeds"] == 1


def test_pool_pairing_without_common_seeds_cannot_compare():
    comparable, reason, info = pool_pairing(view(), view(), [])

    assert comparable is False
    assert reason == "没有同种子的已完成比赛，无法核对客队战术池分配"
    assert info["common_seeds"] == 0


def test_pool_pairing_reports_missing_draws():
    baseline = view(draws={1: 0, 2: 1})
    candidate = view(draws={1: 0, 2: 1, 3: 0})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2, 3])

    assert comparable is False
    assert reason == "缺少同种子的客队战术池分配记录，不能配对"
    assert info["missing_seeds"] == [3]
    assert info["mismatched_seeds"] == []


def test_pool_pairing_truncates_missing_seeds_to_twenty():
    seeds = list(range(1, 26))
    baseline = view(draws={seed: 0 for seed in seeds[:2]})
    candidate = view(draws={seed: 0 for seed in seeds})

    comparable, reason, info = pool_pairing(baseline, candidate, seeds)

    assert comparable is False
    assert reason == "缺少同种子的客队战术池分配记录，不能配对"
    assert info["missing_seeds"] == seeds[2:22]
    assert len(info["missing_seeds"]) == 20


def test_pool_pairing_reports_draw_mismatches():
    baseline = view(draws={1: 0, 2: 0})
    candidate = view(draws={1: 0, 2: 1})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2])

    assert comparable is False
    assert reason == "客队战术池分配不同：1/2 个同种子场次使用了不同战术"
    assert info["draw_mismatches"] == 1
    assert info["mismatched_seeds"] == [2]
    assert info["missing_seeds"] == []


def test_pool_pairing_truncates_mismatched_seeds_to_twenty():
    seeds = list(range(1, 26))
    baseline = view(draws={seed: 0 for seed in seeds})
    candidate = view(draws={seed: 1 for seed in seeds})

    comparable, reason, info = pool_pairing(baseline, candidate, seeds)

    assert comparable is False
    assert reason == "客队战术池分配不同：25/25 个同种子场次使用了不同战术"
    assert info["draw_mismatches"] == 25
    assert info["mismatched_seeds"] == seeds[:20]
    assert len(info["mismatched_seeds"]) == 20


def test_pool_pairing_accepts_matching_draws():
    baseline = view(draws={1: 0, 2: 1})
    candidate = view(draws={2: 1, 1: 0})

    assert pool_pairing(baseline, candidate, [1, 2]) == (
        True,
        None,
        {
            "common_seeds": 2,
            "draw_mismatches": None,
            "mismatched_seeds": [],
            "missing_seeds": [],
        },
    )


def test_pool_pairing_ignores_non_integer_seeds():
    baseline = view(draws={1: 0, 3: 1})
    candidate = view(draws={1: 0, 3: 1})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2.5, 3])

    assert comparable is True
    assert reason is None
    assert info["common_seeds"] == 2


def run(score: tuple[int, int], xg: tuple[float, float] | None = (1.0, 0.5)) -> dict:
    value: dict = {"score": list(score)}
    if xg is not None:
        value["statistics"] = {"teams": [{"xg": xg[0]}, {"xg": xg[1]}]}
    return value


def test_paired_deltas_orients_to_home_side():
    baseline = {
        1: run((1, 0), (1.5, 0.7)),
        2: run((0, 2), (0.9, 1.8)),
    }
    candidate = {
        1: run((2, 0), (1.2, 1.0)),
        2: run((2, 2), (1.6, 1.1)),
    }

    paired = paired_deltas(baseline, candidate, 0, reps=200)

    assert paired["seeds"] == 2
    assert paired["win_rate_delta"] == pytest.approx(0.25)
    assert paired["points_delta"] == pytest.approx(0.5)
    assert paired["goal_difference_delta"] == pytest.approx(1.5)
    assert paired["xgd_delta"] == pytest.approx(0.4)
    for key in (
        "win_rate_delta_ci",
        "points_delta_ci",
        "goal_difference_delta_ci",
        "xgd_delta_ci",
    ):
        interval = paired[key]
        assert isinstance(interval, list) and len(interval) == 2
        assert interval[0] <= interval[1]


def test_paired_deltas_orients_to_away_side():
    baseline = {
        1: run((1, 0), (1.5, 0.7)),
        2: run((0, 2), (0.9, 1.8)),
    }
    candidate = {
        1: run((2, 0), (1.2, 1.0)),
        2: run((2, 2), (1.6, 1.1)),
    }

    paired = paired_deltas(baseline, candidate, 1, reps=200)

    assert paired["win_rate_delta"] == pytest.approx(-0.25)
    assert paired["points_delta"] == pytest.approx(-1.0)
    assert paired["goal_difference_delta"] == pytest.approx(-1.5)
    assert paired["xgd_delta"] == pytest.approx(-0.4)


def test_paired_deltas_scores_wins_draws_and_losses():
    paired = paired_deltas({1: run((0, 0))}, {1: run((2, 0))}, 0, reps=50)

    assert paired["win_rate_delta"] == pytest.approx(0.5)
    assert paired["points_delta"] == pytest.approx(2.0)
    assert paired["goal_difference_delta"] == pytest.approx(2.0)
    assert paired["win_rate_delta_ci"] == pytest.approx([0.5, 0.5])

    draw = paired_deltas({1: run((0, 1))}, {1: run((1, 1))}, 0, reps=50)

    assert draw["win_rate_delta"] == pytest.approx(0.5)
    assert draw["points_delta"] == pytest.approx(1.0)
    assert draw["goal_difference_delta"] == pytest.approx(1.0)


def test_paired_deltas_skips_xgd_when_data_is_missing():
    baseline = {
        1: run((1, 0), None),
        2: run((0, 1), (1.2, 0.8)),
    }
    candidate = {
        1: run((1, 0), (0.5, 0.5)),
        2: run((0, 1), (0.4, 1.0)),
    }

    paired = paired_deltas(baseline, candidate, 0, reps=50)

    assert paired["seeds"] == 2
    assert paired["xgd_delta"] == pytest.approx((0.4 - 1.0) - (1.2 - 0.8))
    assert paired["xgd_delta_ci"] is not None


def test_paired_deltas_without_xgd_samples_reports_none():
    paired = paired_deltas({1: run((1, 0), None)}, {1: run((1, 0), None)}, 0, reps=50)

    assert paired["xgd_delta"] is None
    assert paired["xgd_delta_ci"] is None
    assert paired["win_rate_delta"] == pytest.approx(0.0)


def test_paired_deltas_without_shared_seeds_reports_none():
    paired = paired_deltas({1: run((1, 0))}, {2: run((1, 0))}, 0, reps=50)

    assert paired["seeds"] == 0
    for key in (
        "win_rate_delta",
        "win_rate_delta_ci",
        "points_delta",
        "points_delta_ci",
        "goal_difference_delta",
        "goal_difference_delta_ci",
        "xgd_delta",
        "xgd_delta_ci",
    ):
        assert paired[key] is None


def test_paired_deltas_rounds_deltas_and_intervals_to_four_decimals():
    baseline = {1: run((0, 0)), 2: run((0, 0)), 3: run((0, 0))}
    candidate = {1: run((1, 0)), 2: run((2, 0)), 3: run((0, 1))}

    paired = paired_deltas(baseline, candidate, 0, reps=300)

    assert paired["win_rate_delta"] == 0.1667
    assert paired["points_delta"] == 1.0
    assert paired["goal_difference_delta"] == 0.6667
    for key in (
        "win_rate_delta_ci",
        "points_delta_ci",
        "goal_difference_delta_ci",
        "xgd_delta_ci",
    ):
        interval = paired[key]
        if interval is not None:
            assert all(value == round(value, 4) for value in interval), key


def test_paired_deltas_rejects_invalid_scores():
    with pytest.raises(ValueError, match="比赛比分格式无效"):
        paired_deltas({1: {"score": None}}, {1: run((1, 0))}, 0)
    with pytest.raises(ValueError, match="比赛比分格式无效"):
        paired_deltas({1: run((1, 0))}, {1: {"score": [1]}}, 0)


@pytest.mark.parametrize("side", [2, -1, 0.5, "0", True])
def test_paired_deltas_rejects_invalid_side(side):
    with pytest.raises(ValueError, match="side 必须为 0 或 1"):
        paired_deltas({1: run((1, 0))}, {1: run((1, 0))}, side)


def test_paired_deltas_rejects_invalid_reps():
    with pytest.raises(ValueError):
        paired_deltas({1: run((1, 0))}, {1: run((1, 0))}, 0, reps=0)


def test_paired_deltas_bootstrap_is_deterministic():
    baseline = {seed: run((seed % 3, 0)) for seed in range(1, 6)}
    candidate = {seed: run((seed % 2, 1)) for seed in range(1, 6)}

    first = paired_deltas(baseline, candidate, 0, reps=300)
    second = paired_deltas(baseline, candidate, 0, reps=300)

    assert first == second
