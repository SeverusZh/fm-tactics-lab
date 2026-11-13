from __future__ import annotations

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.results import ResultsService


def add_job(repository: JobRepository, job_id: str, *, config=None, name=None) -> None:
    value = {
        "id": job_id,
        "kind": "experiment",
        "status": "queued",
        "config": {} if config is None else config,
    }
    if name is not None:
        value["name"] = name
    repository.add(value)


def add_run(
    repository: JobRepository,
    job_id: str,
    variant: str,
    seed: int,
    home: int | None,
    away: int | None,
    *,
    stats=None,
) -> None:
    value = {"variant": variant, "seed": seed, "verified": True}
    if home is not None and away is not None:
        value["score_home"] = home
        value["score_away"] = away
    value["stats"] = {} if stats is None else stats
    repository.add_run(job_id, value)


def stats(xg=(1.2, 0.8)) -> dict:
    return {"teams": [{"xg": xg[0]}, {"xg": xg[1]}]}


def pool_config(entry_count: int = 2, **overrides) -> dict:
    config = {
        "enabled": True,
        "entries": [
            {"name": f"客队战术 {index + 1}", "weight": index + 1, "tactic": {}}
            for index in range(entry_count)
        ],
        "uniform": {"enabled": True, "attribute_value": 15},
        "rotation": {"enabled": False, "rounds": 1},
        "real": {"enabled": False},
    }
    config.update(overrides)
    return config


@pytest.fixture
def service(tmp_path):
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    repository = JobRepository(database)
    return ResultsService(repository), repository


def test_compare_returns_none_when_any_job_is_missing(service):
    results, repository = service
    add_job(repository, "base")

    assert results.compare("base", ["ghost"]) is None
    assert results.compare("ghost", ["base"]) is None


@pytest.mark.parametrize(
    "candidates, message",
    [
        ([], "候选任务不能为空"),
        (["cand", "cand"], "候选任务不能重复"),
        (["base"], "候选任务不能包含基线任务"),
        ([f"cand{index}" for index in range(33)], "候选任务最多 32 个"),
    ],
)
def test_compare_validates_candidate_ids(service, candidates, message):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")

    with pytest.raises(ValueError, match=message):
        results.compare("base", candidates)


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"variant": "C"}, "variant 必须为 A 或 B"),
        ({"side": 2}, "side 必须为 0 或 1"),
        ({"side": -1}, "side 必须为 0 或 1"),
        ({"reps": 0}, "reps 必须为 1–20000 的整数"),
        ({"reps": 20001}, "reps 必须为 1–20000 的整数"),
    ],
)
def test_compare_validates_options(service, arguments, message):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")

    with pytest.raises(ValueError, match=message):
        results.compare("base", ["cand"], **arguments)


def test_compare_filters_runs_by_variant_with_full_fallback(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "A", 1, 5, 0)
    add_run(repository, "base", "B", 1, 1, 0)
    add_run(repository, "cand", "B", 1, 2, 0)

    default = results.compare("base", ["cand"])
    assert default["baseline"]["metrics"]["n"] == 1
    assert default["baseline"]["metrics"]["goals_for"] == pytest.approx(1.0)

    variant_a = results.compare("base", ["cand"], variant="A")
    assert variant_a["variant"] == "A"
    assert variant_a["baseline"]["metrics"]["goals_for"] == pytest.approx(5.0)
    assert variant_a["candidates"][0]["paired"]["seeds"] == 1


def test_compare_ignores_incomplete_runs(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 1, 0)
    add_run(repository, "base", "B", 2, None, None)
    add_run(repository, "cand", "B", 1, 1, 0)
    add_run(repository, "cand", "B", 2, 3, 0)

    compared = results.compare("base", ["cand"])
    candidate = compared["candidates"][0]

    assert compared["baseline"]["metrics"]["n"] == 1
    assert candidate["metrics"]["n"] == 2
    assert candidate["paired"]["seeds"] == 1


def test_compare_keeps_last_run_for_duplicate_seeds(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 0, 0)
    add_run(repository, "base", "B", 1, 3, 0)
    add_run(repository, "cand", "B", 1, 1, 0)

    compared = results.compare("base", ["cand"])

    assert compared["baseline"]["metrics"]["n"] == 2
    assert compared["baseline"]["metrics"]["goals_for"] == pytest.approx(1.5)
    assert compared["candidates"][0]["paired"]["win_rate_delta"] == pytest.approx(0.0)
    assert compared["candidates"][0]["paired"]["goal_difference_delta"] == pytest.approx(-2.0)


def test_compare_without_pools_pairs_shared_seeds(service):
    results, repository = service
    add_job(repository, "base", name="Baseline")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 1, 0, stats=stats((1.5, 0.5)))
    add_run(repository, "base", "B", 2, 0, 1, stats=stats((0.4, 1.2)))
    add_run(repository, "cand", "B", 1, 2, 1, stats=stats((1.6, 0.6)))
    add_run(repository, "cand", "B", 2, 0, 0, stats=stats((0.5, 1.1)))

    compared = results.compare("base", ["cand"], reps=200)
    candidate = compared["candidates"][0]

    assert set(compared) == {"baseline", "variant", "side", "candidates"}
    assert set(compared["baseline"]) == {"job_id", "name", "metrics", "tactic_pool"}
    assert compared["baseline"]["job_id"] == "base"
    assert compared["baseline"]["name"] == "Baseline"
    assert compared["baseline"]["tactic_pool"]["enabled"] is False
    assert compared["variant"] == "B"
    assert compared["side"] == 0
    assert candidate["job_id"] == "cand"
    assert candidate["name"] is None
    assert candidate["comparable"] is True
    assert candidate["reason"] is None
    assert candidate["pairing"] is None
    paired = candidate["paired"]
    assert set(paired) == {
        "seeds",
        "win_rate_delta",
        "win_rate_delta_ci",
        "points_delta",
        "points_delta_ci",
        "goal_difference_delta",
        "goal_difference_delta_ci",
        "xgd_delta",
        "xgd_delta_ci",
    }
    assert paired["seeds"] == 2
    assert paired["win_rate_delta"] == pytest.approx(0.25)
    assert paired["points_delta"] == pytest.approx(0.5)
    assert paired["goal_difference_delta"] == pytest.approx(0.5)
    assert paired["xgd_delta"] == pytest.approx(0.1)
    for key in ("win_rate_delta_ci", "points_delta_ci", "goal_difference_delta_ci", "xgd_delta_ci"):
        assert isinstance(paired[key], list) and len(paired[key]) == 2


def test_compare_rounds_paired_deltas(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    for seed in (1, 2, 3):
        add_run(repository, "base", "B", seed, 0, 0)
    add_run(repository, "cand", "B", 1, 1, 0)
    add_run(repository, "cand", "B", 2, 2, 0)
    add_run(repository, "cand", "B", 3, 0, 1)

    paired = results.compare("base", ["cand"], reps=300)["candidates"][0]["paired"]

    assert paired["win_rate_delta"] == 0.1667
    assert paired["goal_difference_delta"] == 0.6667
    for key in ("win_rate_delta_ci", "points_delta_ci", "goal_difference_delta_ci"):
        assert all(value == round(value, 4) for value in paired[key]), key


def test_compare_marks_one_sided_pool_as_not_comparable(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand", config={"away_tactic_pool": pool_config(2)})
    add_run(repository, "base", "B", 1, 1, 0)
    add_run(repository, "base", "B", 2, 0, 0)
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "cand", "B", 2, 0, 0, stats={"tactic_pool_entry": 1})

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is False
    assert candidate["reason"] == "基线任务未使用客队战术池，候选任务使用了客队战术池"
    assert candidate["paired"] is None
    assert candidate["metrics"]["n"] == 2
    assert candidate["tactic_pool"]["enabled"] is True
    assert candidate["tactic_pool"]["entry_count"] == 2
    assert candidate["tactic_pool"]["draws"] == {"0": 1, "1": 1}


def test_compare_marks_draw_mismatch_as_not_comparable(service):
    results, repository = service
    pool = pool_config(2)
    add_job(repository, "base", config={"away_tactic_pool": pool})
    add_job(repository, "cand", config={"away_tactic_pool": pool_config(2)})
    add_run(repository, "base", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "base", "B", 2, 0, 0, stats={"tactic_pool_entry": 1})
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "cand", "B", 2, 0, 0, stats={"tactic_pool_entry": 0})

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is False
    assert candidate["reason"] == "客队战术池分配不同：1/2 个同种子场次使用了不同战术"
    assert candidate["pairing"] == {
        "common_seeds": 2,
        "draw_mismatches": 1,
        "mismatched_seeds": [2],
        "missing_seeds": [],
    }
    assert candidate["paired"] is None
    assert candidate["metrics"]["n"] == 2


def test_compare_rejects_pool_entry_differences(service):
    results, repository = service
    add_job(repository, "base", config={"away_tactic_pool": pool_config(2)})
    add_job(repository, "cand", config={"away_tactic_pool": pool_config(3)})
    add_run(repository, "base", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is False
    assert candidate["reason"] == "两个任务的客队战术池条目不同，同种子分配无法对齐"
    assert candidate["paired"] is None


def test_compare_rejects_pool_mode_differences(service):
    results, repository = service
    add_job(repository, "base", config={"away_tactic_pool": pool_config(2)})
    add_job(
        repository,
        "cand",
        config={"away_tactic_pool": pool_config(2, rotation={"enabled": True, "rounds": 1})},
    )
    add_run(repository, "base", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is False
    assert candidate["reason"] == "两个任务的客队战术池模式不同，同种子分配无法对齐"
    assert candidate["paired"] is None


def test_compare_without_shared_seeds_is_not_comparable(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 1, 0)
    add_run(repository, "cand", "B", 2, 1, 0)

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is False
    assert candidate["reason"] == "没有同种子的已完成比赛"
    assert candidate["pairing"] is None
    assert candidate["paired"] is None
    assert candidate["metrics"]["n"] == 1


def test_compare_accepts_matching_pool_draws_across_entry_shapes(service):
    results, repository = service
    add_job(repository, "base", config={"away_tactic_pool": pool_config(2)})
    add_job(repository, "cand", config={"away_tactic_pool": pool_config(2)})
    add_run(repository, "base", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": {"index": 0}})

    candidate = results.compare("base", ["cand"])["candidates"][0]

    assert candidate["comparable"] is True
    assert candidate["reason"] is None
    assert candidate["pairing"]["draw_mismatches"] is None
    assert candidate["pairing"]["mismatched_seeds"] == []
    assert candidate["paired"]["seeds"] == 1
    assert candidate["tactic_pool"]["draws"] == {"0": 1, "1": 0}
    assert results.compare("base", ["cand"])["baseline"]["tactic_pool"]["draws"] == {
        "0": 1,
        "1": 0,
    }


def test_compare_rejects_conflicting_pool_draws_within_a_job(service):
    results, repository = service
    add_job(repository, "base", config={"away_tactic_pool": pool_config(2)})
    add_job(repository, "cand", config={"away_tactic_pool": pool_config(2)})
    add_run(repository, "base", "A", 1, 1, 0, stats={"tactic_pool_entry": 0})
    add_run(repository, "base", "B", 1, 1, 0, stats={"tactic_pool_entry": 1})
    add_run(repository, "cand", "B", 1, 1, 0, stats={"tactic_pool_entry": 0})

    with pytest.raises(ValueError, match="同种子对照的客队战术不一致"):
        results.compare("base", ["cand"])


def test_compare_orients_xgd_to_away_side(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 1, 0, stats=stats((1.5, 0.5)))
    add_run(repository, "cand", "B", 1, 1, 0, stats=stats((0.8, 1.2)))

    home = results.compare("base", ["cand"], side=0)["candidates"][0]["paired"]
    away = results.compare("base", ["cand"], side=1)["candidates"][0]["paired"]

    assert home["xgd_delta"] == pytest.approx(-1.4)
    assert away["xgd_delta"] == pytest.approx(1.4)
    assert away["xgd_delta"] == pytest.approx(-home["xgd_delta"])


def test_compare_returns_disabled_pool_summary_when_job_has_no_pool(service):
    results, repository = service
    add_job(repository, "base")
    add_job(repository, "cand")
    add_run(repository, "base", "B", 1, 1, 0)
    add_run(repository, "cand", "B", 1, 1, 0)

    compared = results.compare("base", ["cand"])

    assert compared["baseline"]["tactic_pool"] == {
        "enabled": False,
        "entry_count": 0,
        "mode": None,
        "players": None,
        "draws": {},
    }
