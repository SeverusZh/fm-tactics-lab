"""比赛结果统计性质测试。"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fm27lab.domain.results import paired_goal_difference, summarize_runs

SCORES = st.tuples(st.integers(0, 5), st.integers(0, 5))
FAST = dict(max_examples=25, deadline=None, derandomize=True)


def run(
    score,
    *,
    xg=(1.2, 0.8),
    possession=(55, 45),
    shots=(10, 7),
    passes=(500, 400),
    completed=(440, 320),
    seed=1,
    variant="B",
    statistics=True,
):
    value = {"seed": seed, "variant": variant, "result": {"score": list(score)}}
    if statistics:
        value["statistics"] = {
            "teams": [
                {
                    "xg": xg[0],
                    "possession": possession[0],
                    "shots": shots[0],
                    "passes": passes[0],
                    "completed_passes": completed[0],
                },
                {
                    "xg": xg[1],
                    "possession": possession[1],
                    "shots": shots[1],
                    "passes": passes[1],
                    "completed_passes": completed[1],
                },
            ]
        }
    return value


@settings(**FAST)
@given(st.lists(SCORES, min_size=1, max_size=25))
def test_summary_partitions_all_results(scores):
    summary = summarize_runs([run(score) for score in scores])
    n = len(scores)
    wins = sum(home > away for home, away in scores)
    draws = sum(home == away for home, away in scores)
    assert summary["n"] == n
    assert summary["wins"] + summary["draws"] + summary["losses"] == n
    assert summary["wins"] == wins
    assert summary["draws"] == draws
    assert summary["win_rate"] == wins / n
    assert summary["points"] == (3 * wins + draws) / n
    assert summary["goals_for"] == sum(home for home, _ in scores) / n
    assert summary["goals_against"] == sum(away for _, away in scores) / n
    lower, upper = summary["win_interval"]
    assert 0.0 <= lower <= summary["win_rate"] <= upper <= 1.0


@settings(**FAST)
@given(st.lists(SCORES, min_size=1, max_size=8))
def test_wilson_interval_narrows_when_every_result_repeats(scores):
    base = summarize_runs([run(score) for score in scores])
    repeated_scores = [score for score in scores for _ in range(4)]
    repeated = summarize_runs([run(score) for score in repeated_scores])
    assert repeated["win_rate"] == base["win_rate"]
    base_width = base["win_interval"][1] - base["win_interval"][0]
    repeated_width = repeated["win_interval"][1] - repeated["win_interval"][0]
    assert 0.0 < repeated_width < base_width


@settings(**FAST)
@given(st.lists(SCORES, min_size=1, max_size=20))
def test_away_summary_mirrors_home_summary(scores):
    runs = [run(score) for score in scores]
    home = summarize_runs(runs, 0)
    away = summarize_runs(runs, 1)
    draws = sum(home_goals == away_goals for home_goals, away_goals in scores)
    n = len(scores)
    assert away["wins"] == home["losses"]
    assert away["losses"] == home["wins"]
    assert away["draws"] == home["draws"]
    assert home["win_rate"] + away["win_rate"] == pytest.approx((n - draws) / n)
    assert home["points"] + away["points"] == pytest.approx(3 - draws / n)
    assert home["goals_for"] == away["goals_against"]
    assert home["xg"] == away["xga"]
    assert home["xga"] == away["xg"]
    assert home["possession"] + away["possession"] == pytest.approx(100.0)


@settings(**FAST)
@given(st.lists(st.tuples(
    st.floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
    st.floats(min_value=0, max_value=5, allow_nan=False, allow_infinity=False),
), min_size=1, max_size=20))
def test_xg_average_stays_inside_observed_range(pairs):
    runs = [run((1, 0), xg=pair) for pair in pairs]
    summary = summarize_runs(runs)
    own = [own for own, _ in pairs]
    assert summary["xg"] == pytest.approx(sum(own) / len(own))
    assert 0.0 <= summary["xg"] <= max(own)
    assert summary["xga"] == pytest.approx(sum(other for _, other in pairs) / len(pairs))


@settings(**FAST)
@given(st.lists(st.integers(1, 900), min_size=1, max_size=15))
def test_pass_completion_is_aggregate_ratio(passes):
    completed = [value // 3 for value in passes]
    runs = [run((1, 0), passes=(made, 400), completed=(done, 320)) for made, done in zip(passes, completed, strict=True)]
    summary = summarize_runs(runs)
    assert summary["pass_completion"] == sum(completed) / sum(passes)


def test_pass_completion_without_attempts_is_zero():
    summary = summarize_runs([run((1, 0), passes=(0, 0), completed=(0, 0))])

    assert summary["pass_completion"] == 0.0


def test_missing_statistics_report_none():
    summary = summarize_runs([run((1, 0), statistics=False)])

    assert summary["n"] == 1
    for key in ("xg", "xga", "possession", "shots", "pass_completion"):
        assert summary[key] is None


def test_empty_runs_have_no_summary():
    assert summarize_runs([]) is None


@pytest.mark.parametrize("side", [2, -1, 0.5, "0", True, None])
def test_summary_rejects_invalid_side(side):
    with pytest.raises(ValueError, match="side"):
        summarize_runs([run((1, 0))], side)


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=12))
def test_paired_goal_difference_is_per_seed_mean(pairs):
    runs = []
    for seed, (baseline, candidate) in enumerate(pairs):
        runs.append(run(baseline, seed=seed, variant="A"))
        runs.append(run(candidate, seed=seed, variant="B"))
    expected = [
        (candidate[0] - candidate[1]) - (baseline[0] - baseline[1])
        for baseline, candidate in pairs
    ]
    result = paired_goal_difference(runs)
    assert result["n"] == len(pairs)
    assert result["goal_difference_delta"] == pytest.approx(sum(expected) / len(expected))


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=12))
def test_paired_goal_difference_negates_for_away_side(pairs):
    runs = []
    for seed, (baseline, candidate) in enumerate(pairs):
        runs.append(run(baseline, seed=seed, variant="A"))
        runs.append(run(candidate, seed=seed, variant="B"))
    home = paired_goal_difference(runs, 0)
    away = paired_goal_difference(runs, 1)
    assert away["goal_difference_delta"] == pytest.approx(-home["goal_difference_delta"])


@settings(**FAST)
@given(st.lists(st.tuples(SCORES, SCORES), min_size=1, max_size=12))
def test_paired_goal_difference_negates_when_variants_swap(pairs):
    runs = []
    for seed, (baseline, candidate) in enumerate(pairs):
        runs.append(run(candidate, seed=seed, variant="A"))
        runs.append(run(baseline, seed=seed, variant="B"))
    result = paired_goal_difference(runs)
    expected = [
        (baseline[0] - baseline[1]) - (candidate[0] - candidate[1])
        for baseline, candidate in pairs
    ]
    assert result["goal_difference_delta"] == pytest.approx(sum(expected) / len(expected))


def test_paired_goal_difference_ignores_incomplete_pairs():
    runs = [
        run((1, 0), seed=1, variant="A"),
        run((2, 1), seed=1, variant="B"),
        run((0, 1), seed=2, variant="A"),
    ]

    result = paired_goal_difference(runs)

    assert result == {"n": 1, "goal_difference_delta": 0.0}


def test_paired_goal_difference_without_pairs_has_no_delta():
    assert paired_goal_difference([run((1, 0), seed=1, variant="A")]) == {
        "n": 0,
        "goal_difference_delta": None,
    }


def test_paired_goal_difference_rejects_duplicate_variants():
    runs = [run((1, 0), seed=1, variant="A"), run((0, 0), seed=1, variant="A")]

    with pytest.raises(ValueError, match="种子 1 的 A 变体重复"):
        paired_goal_difference(runs)


def test_paired_goal_difference_rejects_missing_seed_or_variant():
    with pytest.raises(ValueError, match="配对比赛缺少整数种子"):
        paired_goal_difference([{"result": {"score": [1, 0]}, "variant": "A"}])
    with pytest.raises(ValueError, match="A/B 变体"):
        paired_goal_difference([run((1, 0), seed=1, variant="C")])


@pytest.mark.parametrize("side", [2, -1, 0.5, "0", True, None])
def test_paired_goal_difference_rejects_invalid_side(side):
    with pytest.raises(ValueError, match="side"):
        paired_goal_difference([run((1, 0), seed=1, variant="A")], side)
