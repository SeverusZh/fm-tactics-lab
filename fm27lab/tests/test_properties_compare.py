"""对比与配对性质测试。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fm27lab.domain.compare import bootstrap_ci, paired_deltas, pool_pairing

FAST = dict(max_examples=25, deadline=None, derandomize=True)
VALUES = st.lists(
    st.one_of(st.integers(-10, 10), st.floats(-10, 10, allow_nan=False, allow_infinity=False)),
    min_size=1,
    max_size=12,
)
SCORES = st.tuples(st.integers(0, 4), st.integers(0, 4))


def entry(index, name=None, *, weight=1, roster=False):
    return {
        "index": index,
        "name": name or f"客队战术 {index + 1}",
        "weight": weight,
        "roster": roster,
    }


def view(*, mode="random", rounds=1, players="uniform", entries=None, draws=None):
    return {
        "mode": mode,
        "rounds": rounds,
        "players": players,
        "entries": [entry(0), entry(1)] if entries is None else entries,
        "draws": {} if draws is None else draws,
    }


def run(score, *, xg=None):
    value = {"result": {"score": list(score)}}
    if xg is not None:
        value["statistics"] = {"teams": [{"xg": xg[0]}, {"xg": xg[1]}]}
    return value


@settings(**FAST)
@given(VALUES)
def test_bootstrap_interval_stays_inside_value_range(values):
    interval = bootstrap_ci(values, reps=200)

    assert interval is not None
    assert interval[0] <= interval[1]
    assert min(values) - 1e-12 <= interval[0] <= interval[1] <= max(values) + 1e-12


@settings(**FAST)
@given(VALUES, st.integers(-5, 5))
def test_bootstrap_interval_translates_with_values(values, shift):
    base = bootstrap_ci(values, reps=200)
    shifted = bootstrap_ci([value + shift for value in values], reps=200)

    assert shifted == pytest.approx([base[0] + shift, base[1] + shift], abs=1e-9)


@settings(**FAST)
@given(st.lists(st.integers(-10, 10), min_size=1, max_size=12), st.integers(2, 4))
def test_bootstrap_interval_scales_with_positive_factor(values, factor):
    base = bootstrap_ci(values, reps=200)
    scaled = bootstrap_ci([value * factor for value in values], reps=200)

    assert scaled == pytest.approx([base[0] * factor, base[1] * factor], rel=1e-12)


@settings(**FAST)
@given(st.integers(-10, 10), st.integers(1, 5))
def test_bootstrap_interval_of_constants_is_a_point(value, count):
    assert bootstrap_ci([value] * count, reps=100) == [float(value), float(value)]


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES, SCORES, SCORES), min_size=1, max_size=10))
def test_paired_deltas_match_hand_computed_means(rows):
    baseline = {}
    candidate = {}
    expected = {"win_rate_delta": [], "points_delta": [], "goal_difference_delta": [], "xgd_delta": []}

    def win(goals_for, goals_against):
        return 1.0 if goals_for > goals_against else (0.5 if goals_for == goals_against else 0.0)

    def points(goals_for, goals_against):
        return 3.0 if goals_for > goals_against else (1.0 if goals_for == goals_against else 0.0)

    for seed, (home, away, xg_home, xg_away) in enumerate(rows):
        base_score, cand_score, base_xg, cand_xg = home, away, xg_home, xg_away
        baseline[seed] = run(base_score, xg=base_xg)
        candidate[seed] = run(cand_score, xg=cand_xg)
        expected["win_rate_delta"].append(
            win(*cand_score) - win(*base_score)
        )
        expected["points_delta"].append(
            points(*cand_score) - points(*base_score)
        )
        expected["goal_difference_delta"].append(
            (cand_score[0] - cand_score[1]) - (base_score[0] - base_score[1])
        )
        expected["xgd_delta"].append(
            (cand_xg[0] - cand_xg[1]) - (base_xg[0] - base_xg[1])
        )

    result = paired_deltas(baseline, candidate, 0, reps=200)

    assert result["seeds"] == len(rows)
    for key, values in expected.items():
        assert result[key] == pytest.approx(round(sum(values) / len(values), 4))


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=10), st.integers(1, 5))
def test_paired_deltas_ignore_equal_shift_on_both_sides(rows, shift):
    baseline = {}
    candidate = {}
    shifted_baseline = {}
    shifted_candidate = {}
    for seed, (base_score, cand_score) in enumerate(rows):
        baseline[seed] = run(base_score)
        candidate[seed] = run(cand_score)
        shifted_baseline[seed] = run((base_score[0] + shift, base_score[1] + shift))
        shifted_candidate[seed] = run((cand_score[0] + shift, cand_score[1] + shift))

    assert paired_deltas(shifted_baseline, shifted_candidate, 0, reps=200) == paired_deltas(
        baseline, candidate, 0, reps=200
    )


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=10))
def test_paired_deltas_negate_when_baseline_and_candidate_swap(rows):
    baseline = {}
    candidate = {}
    for seed, (base_score, cand_score) in enumerate(rows):
        xg = (1.0 + seed % 3, 0.5)
        baseline[seed] = run(base_score, xg=xg)
        candidate[seed] = run(cand_score, xg=xg)

    forward = paired_deltas(baseline, candidate, 0, reps=200)
    backward = paired_deltas(candidate, baseline, 0, reps=200)

    for key in ("win_rate_delta", "points_delta", "goal_difference_delta", "xgd_delta"):
        assert backward[key] == pytest.approx(-forward[key])


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=10))
def test_paired_deltas_orient_away_side_goal_difference(rows):
    baseline = {}
    candidate = {}
    for seed, (base_score, cand_score) in enumerate(rows):
        baseline[seed] = run(base_score)
        candidate[seed] = run(cand_score)

    home = paired_deltas(baseline, candidate, 0, reps=100)
    away = paired_deltas(baseline, candidate, 1, reps=100)

    assert away["win_rate_delta"] == pytest.approx(-home["win_rate_delta"])
    assert away["goal_difference_delta"] == pytest.approx(-home["goal_difference_delta"])


def test_paired_deltas_ignore_unshared_seeds():
    baseline = {1: run((1, 0)), 2: run((0, 2))}
    candidate = {1: run((2, 0)), 2: run((2, 2)), 3: run((5, 0)), 4: run((0, 5))}

    paired = paired_deltas(baseline, candidate, 0, reps=100)

    assert paired["seeds"] == 2
    assert paired["win_rate_delta"] == pytest.approx(0.25)
    assert paired["goal_difference_delta"] == pytest.approx(1.5)


def test_paired_deltas_without_shared_seeds_report_none():
    paired = paired_deltas({1: run((1, 0))}, {2: run((1, 0))}, 0, reps=50)

    assert paired["seeds"] == 0
    assert paired["win_rate_delta"] is None
    assert paired["goal_difference_delta"] is None


def test_pool_pairing_accepts_matching_draws():
    baseline = view(draws={1: 0, 2: 1})
    candidate = view(draws={2: 1, 1: 0})

    assert pool_pairing(baseline, candidate, [1, 2]) == (
        True,
        None,
        {"common_seeds": 2, "draw_mismatches": None, "mismatched_seeds": [], "missing_seeds": []},
    )


def test_pool_pairing_reports_single_mismatch():
    baseline = view(draws={1: 0, 2: 0})
    candidate = view(draws={1: 0, 2: 1})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2])

    assert comparable is False
    assert reason == "客队战术池分配不同：1/2 个同种子场次使用了不同战术"
    assert info["draw_mismatches"] == 1
    assert info["mismatched_seeds"] == [2]


def test_pool_pairing_reports_missing_draws():
    baseline = view(draws={1: 0, 2: 1})
    candidate = view(draws={1: 0})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2])

    assert comparable is False
    assert reason == "缺少同种子的客队战术池分配记录，不能配对"
    assert info["missing_seeds"] == [2]


def test_pool_pairing_rejects_pool_presence_differences():
    assert pool_pairing(None, None, [1])[0] is True
    assert pool_pairing(None, view(draws={1: 0}), [1])[1] == "基线任务未使用客队战术池，候选任务使用了客队战术池"
    assert pool_pairing(view(draws={1: 0}), None, [1])[1] == "候选任务未使用客队战术池，基线任务使用了客队战术池"


def test_pool_pairing_rejects_pool_shape_differences():
    for changed in ({"mode": "rotation"}, {"rounds": 2}, {"players": "real"}):
        baseline = view(draws={1: 0})
        candidate = view(draws={1: 0}, **changed)

        assert pool_pairing(baseline, candidate, [1])[1] == "两个任务的客队战术池模式不同，同种子分配无法对齐"

    baseline = view(entries=[entry(0, "甲")])
    candidate = view(entries=[entry(0, "乙")])

    assert pool_pairing(baseline, candidate, [1])[1] == "两个任务的客队战术池条目不同，同种子分配无法对齐"


def test_pool_pairing_ignores_non_integer_seeds():
    baseline = view(draws={1: 0})
    candidate = view(draws={1: 0})

    comparable, reason, info = pool_pairing(baseline, candidate, [1, 2.5])

    assert comparable is True
    assert reason is None
    assert info["common_seeds"] == 1
