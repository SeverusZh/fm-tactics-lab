"""客队战术池性质测试。"""

from __future__ import annotations

from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fm27lab.domain.pool import (
    PROFILE,
    completed_draw_counts,
    draw_index,
    draws,
    probabilities,
    rotation_matches,
    summary,
)

FAST = dict(max_examples=25, deadline=None, derandomize=True)


def entries(*weights):
    return [{"name": f"T{index}", "weight": weight, "tactic": {}} for index, weight in enumerate(weights)]


@settings(**FAST)
@given(st.lists(st.integers(1, 1000), min_size=1, max_size=20))
def test_probabilities_are_weights_over_total(weights):
    rows = probabilities(entries(*weights))
    total = sum(weights)

    assert len(rows) == len(weights)
    assert sum(row["probability"] for row in rows) == pytest.approx(1.0)
    for row, weight in zip(rows, weights, strict=True):
        assert row["weight"] == weight
        assert row["probability"] == pytest.approx(weight / total)


@pytest.mark.parametrize("weight", [0, -1, 1001, 2.5, "3", None])
def test_probabilities_reject_invalid_weights(weight):
    with pytest.raises(ValueError, match="权重"):
        probabilities([{"weight": weight}])


def test_probabilities_reject_empty_and_oversized_pools():
    with pytest.raises(ValueError, match="没有可抽取"):
        probabilities([])
    with pytest.raises(ValueError, match="没有可抽取"):
        probabilities({"weight": 1})
    with pytest.raises(ValueError, match="128"):
        probabilities(entries(*([1] * 129)))


@settings(**FAST)
@given(st.data())
def test_draw_index_is_bounded_and_reproducible(data):
    count = data.draw(st.integers(1, 32))
    weights = [data.draw(st.integers(1, 10)) for _ in range(count)]
    pool = entries(*weights)
    seed = data.draw(st.integers(-(10**9), 10**9))
    salt = data.draw(st.text(max_size=8))

    index = draw_index(pool, seed, salt)

    assert 0 <= index < count
    assert draw_index(pool, seed, salt) == index


@settings(**FAST)
@given(st.data())
def test_random_draws_cover_requested_seeds(data):
    count = data.draw(st.integers(1, 16))
    pool = entries(*[data.draw(st.integers(1, 10)) for _ in range(count)])
    seeds = data.draw(st.lists(st.integers(0, 10**6), min_size=1, max_size=20))

    mapping = draws(pool, seeds, "salt")

    assert set(mapping) == set(seeds)
    assert all(0 <= index < count for index in mapping.values())
    assert draws(pool, seeds, "salt") == mapping


@settings(**FAST)
@given(st.integers(1, 12), st.integers(1, 4), st.data())
def test_rotation_assigns_every_entry_evenly(count, rounds, data):
    seeds = data.draw(
        st.lists(
            st.integers(0, 10**6),
            min_size=count * rounds,
            max_size=count * rounds,
            unique=True,
        )
    )
    pool = entries(*([1] * count))

    mapping = draws(pool, seeds, "salt", rotation_enabled=True, rounds=rounds)

    assert [mapping[seed] for seed in seeds] == [position % count for position in range(len(seeds))]
    assert set(Counter(mapping.values()).values()) == {rounds}


def test_rotation_single_round_uses_every_entry_once():
    pool = entries(*([1] * 8))
    seeds = list(range(101, 109))

    mapping = draws(pool, seeds, "salt", rotation_enabled=True)

    assert sorted(mapping.values()) == list(range(8))
    assert rotation_matches(8, 1) == 8


def test_rotation_rejects_invalid_seed_sets():
    pool = entries(*([1] * 3))

    with pytest.raises(ValueError, match="种子必须唯一"):
        draws(pool, [1, 1, 2], "salt", rotation_enabled=True)
    with pytest.raises(ValueError, match="轮战模式每方案需要"):
        draws(pool, [1, 2], "salt", rotation_enabled=True)
    with pytest.raises(ValueError, match="轮战每方案最多"):
        rotation_matches(128, 1000)


@settings(**FAST)
@given(st.data())
def test_completed_draw_counts_matches_runs(data):
    entry_count = data.draw(st.integers(1, 8))
    rows = data.draw(
        st.lists(
            st.tuples(st.integers(0, 1000), st.integers(0, 7)),
            min_size=0,
            max_size=15,
            unique_by=lambda row: row[0],
        )
    )
    runs = [{"seed": seed, "tactic_pool_entry": {"index": index % entry_count}} for seed, index in rows]

    counts = completed_draw_counts(runs, entry_count)

    assert set(counts) == {str(index) for index in range(entry_count)}
    assert sum(counts.values()) == len(runs)
    for index in range(entry_count):
        assert counts[str(index)] == sum(
            1 for run in runs if run["tactic_pool_entry"]["index"] == index
        )


def test_completed_draw_counts_ignores_unpooled_runs():
    counts = completed_draw_counts(
        [{"seed": 1, "tactic_pool_entry": None}, {"seed": 2}],
        3,
    )

    assert counts == {"0": 0, "1": 0, "2": 0}


def test_completed_draw_counts_rejects_conflicting_seeds():
    runs = [
        {"seed": 1, "tactic_pool_entry": {"index": 0}},
        {"seed": 1, "tactic_pool_entry": {"index": 1}},
    ]

    with pytest.raises(ValueError, match="同种子对照"):
        completed_draw_counts(runs, 2)


@settings(**FAST)
@given(st.lists(st.integers(1, 1000), min_size=1, max_size=15), st.text(max_size=6))
def test_summary_random_mode_exposes_weighted_probabilities(weights, salt):
    pool = entries(*weights)
    value = summary(pool, salt=salt)

    assert value["profile"] == PROFILE
    assert value["mode"] == "random"
    assert value["rounds"] == 1
    assert value["players"] == "uniform"
    assert value["enabled"] is False
    assert value["salt"] == salt
    rows = probabilities(pool)
    for emitted, row in zip(value["entries"], rows, strict=True):
        assert emitted["weight"] == row["weight"]
        assert emitted["probability"] == pytest.approx(row["probability"])


@settings(**FAST)
@given(st.lists(st.integers(1, 1000), min_size=1, max_size=10), st.integers(1, 5))
def test_summary_rotation_mode_hides_probabilities(weights, rounds):
    value = summary(entries(*weights), rotation={"enabled": True, "rounds": rounds})

    assert value["mode"] == "rotation"
    assert value["rounds"] == rounds
    assert all(row["probability"] is None for row in value["entries"])
    assert "salt" not in value


def test_summary_rejects_invalid_settings():
    with pytest.raises(ValueError, match="版本无效"):
        summary(entries(1), profile="other")
    with pytest.raises(ValueError, match="轮战轮数"):
        summary(entries(1), rotation={"enabled": True, "rounds": 0})
