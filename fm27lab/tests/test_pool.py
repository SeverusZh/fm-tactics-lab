from __future__ import annotations

import pytest

from fm27lab.domain.pool import (
    completed_draw_counts,
    draw_index,
    draws,
    probabilities,
    rotation_matches,
    rotation_message,
    summary,
)


def entries(*weights):
    return [{"name": f"T{index}", "weight": weight, "tactic": {}} for index, weight in enumerate(weights, 1)]


def test_probabilities_are_normalized_and_validate_weights():
    rows = probabilities(entries(1, 3))
    assert [row["weight"] for row in rows] == [1, 3]
    assert [row["probability"] for row in rows] == [0.25, 0.75]
    with pytest.raises(ValueError, match="没有可抽取"):
        probabilities([])
    with pytest.raises(ValueError, match="权重"):
        probabilities(entries(0))


def test_draw_is_deterministic_for_seed_and_salt():
    pool = entries(1, 1, 1)
    assert draw_index(pool, 42, "job-a") == draw_index(pool, 42, "job-a")
    first = draws(pool, [1, 2, 3, 4], "job-a")
    second = draws(pool, [1, 2, 3, 4], "job-a")
    assert first == second
    assert set(first) == {1, 2, 3, 4}
    assert all(0 <= index < 3 for index in first.values())


def test_same_seed_ab_pair_uses_one_draw():
    pool = entries(1, 1)
    first = draw_index(pool, 7, "job-a")
    second = draw_index(pool, 7, "job-a")
    assert first == second
    assert draws(pool, [7], "job-a")[7] == first
    different = [draw_index(pool, 7, f"job-{salt}") for salt in range(20)]
    assert any(index != first for index in different)


def test_rotation_follows_entry_order_for_each_round():
    pool = entries(1, 1, 1)
    seeds = [11, 12, 13, 14, 15, 16]
    mapping = draws(pool, seeds, "job-a", rotation_enabled=True, rounds=2)
    assert [mapping[seed] for seed in seeds] == [0, 1, 2, 0, 1, 2]
    assert rotation_matches(3, 2) == 6
    with pytest.raises(ValueError, match="需要 3 套 × 2 轮 = 6 场"):
        draws(pool, seeds[:-1], "job-a", rotation_enabled=True, rounds=2)


def test_rotation_message_reports_current_seed_count():
    assert "当前种子数为 4" in rotation_message(3, 2, 4)


def test_rotation_rejects_duplicate_seeds():
    with pytest.raises(ValueError, match="种子必须唯一"):
        draws(entries(1, 1, 1), [1, 1, 2, 2, 3, 3], "job-a", rotation_enabled=True, rounds=2)


def test_rotation_matches_allows_empty_pool():
    assert rotation_matches(0, 1) == 0


def test_completed_draw_counts_once_per_seed_and_rejects_conflicts():
    runs = [
        {"seed": 7, "tactic_pool_entry": {"index": 1}},
        {"seed": 7, "tactic_pool_entry": {"index": 1}},
        {"seed": 8, "tactic_pool_entry": {"index": 0}},
    ]
    assert completed_draw_counts(runs, 2) == {"0": 1, "1": 1}
    with pytest.raises(ValueError, match="同种子对照"):
        completed_draw_counts(runs + [{"seed": 8, "tactic_pool_entry": {"index": 1}}], 2)


def test_completed_draw_counts_ignores_unpooled_runs():
    runs = [{"seed": 1, "tactic_pool_entry": None}, {"seed": 2}]
    assert completed_draw_counts(runs, 2) == {"0": 0, "1": 0}


def test_completed_draw_counts_requires_integer_seed():
    with pytest.raises(ValueError, match="整数种子"):
        completed_draw_counts([{"tactic_pool_entry": {"index": 0}}], 2)
    with pytest.raises(ValueError, match="整数种子"):
        completed_draw_counts([{"seed": 1.5, "tactic_pool_entry": {"index": 0}}], 2)
    with pytest.raises(ValueError, match="整数种子"):
        completed_draw_counts([{"seed": True, "tactic_pool_entry": {"index": 0}}], 2)


def test_summary_reports_random_and_rotation_modes():
    random_summary = summary(entries(1, 2), salt="job-a", enabled=True)
    assert random_summary["mode"] == "random"
    assert random_summary["profile"] == "away-tactic-pool-v1"
    assert random_summary["enabled"] is True
    assert summary(entries(1, 2))["enabled"] is False
    assert summary(entries(1, 2), rounds=4)["rounds"] == 4
    assert random_summary["rounds"] == 1
    assert random_summary["entries"][0]["probability"] == pytest.approx(1 / 3)
    rotation_summary = summary(entries(1, 2), rotation={"enabled": True, "rounds": 2})
    assert rotation_summary["mode"] == "rotation"
    assert rotation_summary["rounds"] == 2
    assert all(row["probability"] is None for row in rotation_summary["entries"])
    real_summary = summary(entries(1, 2), real={"enabled": True})
    assert real_summary["players"] == "real"
    no_real_summary = summary(entries(1, 2), real={"enabled": False})
    assert no_real_summary["players"] == "uniform"


def test_weighted_draws_match_declared_ratio():
    pool = entries(1, 3)
    indexes = [draw_index(pool, seed, "weighted") for seed in range(4000)]
    share = indexes.count(1) / len(indexes)
    assert 0.72 <= share <= 0.78


def test_draw_limits_match_legacy_pool_constraints():
    assert rotation_matches(128, 78) == 9984
    many = entries(*([1] * 129))
    with pytest.raises(ValueError, match="128"):
        draws(many, [1], "job-a")
    with pytest.raises(ValueError, match="10000"):
        draws(entries(*([1] * 11)), list(range(11_000)), "job-a", rotation_enabled=True, rounds=1000)
    with pytest.raises(ValueError, match="10000"):
        draws(entries(*([1] * 128)), list(range(10_112)), "job-a", rotation_enabled=True, rounds=79)


def test_summary_rejects_invalid_modes_names_profile_and_uniform():
    with pytest.raises(ValueError, match="布尔值"):
        summary(entries(1), rotation={"enabled": "yes"})
    with pytest.raises(ValueError, match="名称无效"):
        summary([{"weight": 1}])
    with pytest.raises(ValueError, match="名称无效"):
        summary([{"name": "a\nb", "weight": 1}])
    with pytest.raises(ValueError, match="版本无效"):
        summary(entries(1), profile="other")
    with pytest.raises(ValueError, match="统一属性"):
        summary(entries(1), uniform={"enabled": True, "attribute_value": 0})
    partial = summary(entries(1), uniform={"enabled": True})
    assert partial["uniform"] == {"enabled": True, "attribute_value": 15}


def test_invalid_seed_type_is_rejected():
    with pytest.raises(ValueError, match="随机种子"):
        draw_index(entries(1), True, "job-a")
