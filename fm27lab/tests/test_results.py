from __future__ import annotations

import pytest

from fm27lab.domain.results import paired_goal_difference, summarize_runs


def run(
    score,
    xg=(1.2, 0.8),
    possession=(55, 45),
    shots=(10, 7),
    passes=(500, 400),
    completed=(440, 320),
    seed=1,
    variant="B",
):
    return {
        "seed": seed,
        "variant": variant,
        "result": {"score": list(score)},
        "statistics": {
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
        },
    }


def test_summary_counts_results_and_statistics():
    runs = [run((2, 1)), run((1, 1)), run((0, 2)), run((3, 0))]
    value = summarize_runs(runs)
    assert value["n"] == 4
    assert value["wins"] == 2
    assert value["draws"] == 1
    assert value["losses"] == 1
    assert value["win_rate"] == 0.5
    assert value["goals_for"] == pytest.approx(1.5)
    assert value["goals_against"] == pytest.approx(1.0)
    assert value["points"] == pytest.approx(1.75)
    assert value["xg"] == pytest.approx(1.2)
    assert value["xga"] == pytest.approx(0.8)
    assert value["possession"] == pytest.approx(55)
    assert value["shots"] == pytest.approx(10)
    assert value["pass_completion"] == pytest.approx(440 / 500)
    assert value["win_interval"][0] == pytest.approx(0.150039, abs=1e-6)
    assert value["win_interval"][1] == pytest.approx(0.849961, abs=1e-6)


def test_summary_orients_results_points_and_wilson_to_either_side():
    runs = [run((2, 1)), run((3, 0))]
    away = summarize_runs(runs, side=1)
    assert away["wins"] == 0
    assert away["draws"] == 0
    assert away["losses"] == 2
    assert away["points"] == 0.0
    assert away["win_rate"] == 0.0
    assert away["win_interval"][0] == 0.0
    assert away["win_interval"][1] == pytest.approx(0.657620, abs=1e-6)
    assert away["goals_for"] == pytest.approx(0.5)
    assert away["goals_against"] == pytest.approx(2.5)
    assert away["xg"] == pytest.approx(0.8)
    assert away["xga"] == pytest.approx(1.2)
    assert away["possession"] == pytest.approx(45)
    assert away["shots"] == pytest.approx(7)
    assert away["pass_completion"] == pytest.approx(320 / 400)


def test_summary_without_runs_is_none():
    assert summarize_runs([]) is None


def test_invalid_score_and_side_are_rejected():
    for score in ([1], [-1, 0], [True, 0], [1.5, 0], None):
        with pytest.raises(ValueError, match="比分"):
            summarize_runs([{"result": {"score": score}}])
    for side in (2, True, 1.5, "0"):
        with pytest.raises(ValueError, match="side"):
            summarize_runs([run((1, 0))], side=side)


def test_missing_statistics_are_reported_as_none_but_results_still_count():
    runs = [{"result": {"score": [1, 0]}}]
    value = summarize_runs(runs)
    assert value["n"] == 1
    assert value["xg"] is None
    assert value["pass_completion"] is None
    partial = {
        "result": {"score": [1, 0]},
        "statistics": {
            "teams": [
                {"xg": 1.0, "passes": 10},
                {"xg": 0.5, "completed_passes": 8},
            ]
        },
    }
    value = summarize_runs([partial])
    assert value["xg"] == 1.0
    assert value["pass_completion"] is None
    empty = {"result": {"score": [1, 0]}, "statistics": {"teams": [{}, {}]}}
    assert summarize_runs([empty])["pass_completion"] is None


def test_paired_goal_difference_uses_same_seed_ab_and_orients_side():
    runs = [
        run((3, 0), seed=7, variant="A"),
        run((1, 0), seed=7, variant="B"),
        run((0, 1), seed=8, variant="A"),
        run((2, 2), seed=8, variant="B"),
    ]
    value = paired_goal_difference(runs)
    assert value["n"] == 2
    assert value["goal_difference_delta"] == pytest.approx(-0.5)
    away = paired_goal_difference(runs, side=1)
    assert away["goal_difference_delta"] == pytest.approx(0.5)


def test_paired_goal_difference_requires_complete_pairs():
    value = paired_goal_difference([run((1, 0), seed=1, variant="A")])
    assert value["n"] == 0
    assert value["goal_difference_delta"] is None
    only_b = paired_goal_difference([run((1, 0), seed=1, variant="B")])
    assert only_b["n"] == 0
    assert paired_goal_difference([])["goal_difference_delta"] is None
    with pytest.raises(ValueError, match="重复"):
        paired_goal_difference(
            [
                run((1, 0), seed=1, variant="A"),
                run((2, 0), seed=1, variant="A"),
            ]
        )


def test_invalid_seed_variant_side_and_zero_passes():
    with pytest.raises(ValueError, match="种子"):
        paired_goal_difference([run((1, 0), seed=None, variant="A")])
    with pytest.raises(ValueError, match="A/B"):
        paired_goal_difference([run((1, 0), seed=1, variant="C")])
    with pytest.raises(ValueError, match="side"):
        paired_goal_difference([], side=True)
    value = summarize_runs([run((1, 0), passes=(0, 0), completed=(0, 0))])
    assert value["pass_completion"] == 0.0
