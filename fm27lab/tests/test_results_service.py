from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.results import ResultsService

CSV_COLUMNS = [
    "job_id",
    "sequence",
    "variant",
    "seed",
    "score_home",
    "score_away",
    "verified",
    "created_at",
    "stats_json",
    "events_json",
]


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def seeded(tmp_path: Path, config: dict | None = None) -> tuple[ResultsService, JobRepository]:
    repository = JobRepository(database(tmp_path))
    repository.add(
        {
            "id": "job1",
            "kind": "experiment",
            "status": "queued",
            "config": {} if config is None else config,
        }
    )
    return ResultsService(repository), repository


def append_run(
    repository: JobRepository,
    variant: str,
    seed: int,
    score_home: int | None,
    score_away: int | None,
    stats: dict | None = None,
    events: dict | None = None,
    verified: bool = True,
) -> dict:
    return repository.add_run(
        "job1",
        {
            "variant": variant,
            "seed": seed,
            "score_home": score_home,
            "score_away": score_away,
            "verified": verified,
            "stats": {} if stats is None else stats,
            "events": events,
        },
    )


def paired_samples(repository: JobRepository) -> None:
    append_run(repository, "A", 1, 3, 0)
    append_run(repository, "B", 1, 1, 0)
    append_run(repository, "A", 2, 0, 1)
    append_run(repository, "B", 2, 2, 2)


def stats_payload(
    xg: tuple[float, float] = (1.4, 0.9),
    possession: tuple[int, int] = (58, 42),
    shots: tuple[int, int] = (13, 8),
    passes: tuple[int, int] = (600, 400),
    completed: tuple[int, int] = (540, 320),
) -> dict:
    return {
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


def test_all_runs_collects_every_page_in_sequence_order(tmp_path: Path):
    results, repository = seeded(tmp_path)
    for index in range(450):
        append_run(repository, "A" if index % 2 == 0 else "B", index, index % 3, index % 2)

    runs = results.all_runs("job1")

    assert len(runs) == 450
    assert [item["sequence"] for item in runs] == list(range(1, 451))
    assert all(item["job_id"] == "job1" for item in runs)


def test_all_runs_returns_empty_for_missing_job(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.all_runs("missing") == []


@pytest.mark.parametrize("count", [200, 400])
def test_all_runs_handles_exact_page_multiples(tmp_path: Path, count: int):
    results, repository = seeded(tmp_path)
    for index in range(count):
        append_run(repository, "B", index, 0, 0)

    runs = results.all_runs("job1")

    assert len(runs) == count
    assert [item["sequence"] for item in runs] == list(range(1, count + 1))


def test_summary_reports_job_metrics_and_paired_difference(tmp_path: Path):
    results, repository = seeded(tmp_path)
    paired_samples(repository)

    summary = results.summary("job1")

    assert set(summary) == {"job", "metrics", "paired"}
    assert summary["job"] == repository.get("job1")
    metrics = summary["metrics"]
    assert metrics["n"] == 4
    assert metrics["wins"] == 2
    assert metrics["draws"] == 1
    assert metrics["losses"] == 1
    assert metrics["win_rate"] == pytest.approx(0.5)
    assert metrics["goals_for"] == pytest.approx(1.5)
    assert metrics["goals_against"] == pytest.approx(0.75)
    assert metrics["points"] == pytest.approx(1.75)
    assert summary["paired"]["n"] == 2
    assert summary["paired"]["goal_difference_delta"] == pytest.approx(-0.5)


def test_summary_orients_metrics_and_pairing_to_away_side(tmp_path: Path):
    results, repository = seeded(tmp_path)
    paired_samples(repository)

    summary = results.summary("job1", side=1)

    metrics = summary["metrics"]
    assert metrics["n"] == 4
    assert metrics["wins"] == 1
    assert metrics["draws"] == 1
    assert metrics["losses"] == 2
    assert metrics["win_rate"] == pytest.approx(0.25)
    assert metrics["goals_for"] == pytest.approx(0.75)
    assert metrics["goals_against"] == pytest.approx(1.5)
    assert metrics["points"] == pytest.approx(1.0)
    assert summary["paired"]["n"] == 2
    assert summary["paired"]["goal_difference_delta"] == pytest.approx(0.5)


def test_summary_without_runs_has_none_metrics_and_empty_pairing(tmp_path: Path):
    results, _ = seeded(tmp_path)

    summary = results.summary("job1")

    assert summary["job"]["id"] == "job1"
    assert summary["metrics"] is None
    assert summary["paired"] == {"n": 0, "goal_difference_delta": None}


def test_summary_reads_statistics_from_repository_stats(tmp_path: Path):
    results, repository = seeded(tmp_path)
    stats = stats_payload()
    append_run(repository, "B", 1, 2, 1, stats=stats)
    append_run(repository, "B", 2, 0, 0, stats=stats)

    metrics = results.summary("job1")["metrics"]

    assert metrics["n"] == 2
    assert metrics["xg"] == pytest.approx(1.4)
    assert metrics["xga"] == pytest.approx(0.9)
    assert metrics["possession"] == pytest.approx(58)
    assert metrics["shots"] == pytest.approx(13)
    assert metrics["pass_completion"] == pytest.approx(0.9)


def test_summary_orients_statistics_to_away_side(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(repository, "B", 1, 2, 1, stats=stats_payload())

    metrics = results.summary("job1", side=1)["metrics"]

    assert metrics["wins"] == 0
    assert metrics["losses"] == 1
    assert metrics["goals_for"] == pytest.approx(1.0)
    assert metrics["goals_against"] == pytest.approx(2.0)
    assert metrics["xg"] == pytest.approx(0.9)
    assert metrics["xga"] == pytest.approx(1.4)
    assert metrics["possession"] == pytest.approx(42)
    assert metrics["shots"] == pytest.approx(8)
    assert metrics["pass_completion"] == pytest.approx(0.8)


def test_summary_filters_incomplete_runs_while_matches_keeps_them(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(repository, "A", 1, 2, 0, stats=stats_payload())
    append_run(
        repository,
        "B",
        1,
        None,
        None,
        stats=stats_payload(
            xg=(9.0, 0.0),
            possession=(90, 10),
            shots=(30, 1),
            passes=(1000, 100),
            completed=(990, 10),
        ),
    )

    summary = results.summary("job1")

    assert summary["metrics"]["n"] == 1
    assert summary["metrics"]["xg"] == pytest.approx(1.4)
    assert summary["metrics"]["possession"] == pytest.approx(58)
    assert summary["paired"] == {"n": 0, "goal_difference_delta": None}
    matches = results.matches("job1")
    assert matches["total"] == 2
    assert [item["score"] for item in matches["items"]] == [[2, 0], None]


def test_summary_with_only_incomplete_runs_returns_none_metrics(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(repository, "A", 1, None, None)
    append_run(repository, "B", 1, None, None)

    summary = results.summary("job1")

    assert summary["metrics"] is None
    assert summary["paired"] == {"n": 0, "goal_difference_delta": None}
    assert results.matches("job1")["total"] == 2


def test_summary_requires_complete_pairs_for_paired_difference(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(repository, "A", 1, 2, 0)
    append_run(repository, "A", 2, 0, 0)

    summary = results.summary("job1")

    assert summary["metrics"]["n"] == 2
    assert summary["paired"] == {"n": 0, "goal_difference_delta": None}


def test_summary_returns_none_for_missing_job(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.summary("missing") is None
    assert results.summary("missing", side=1) is None


def test_summary_rejects_invalid_side(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(repository, "A", 1, 1, 0)

    for side in (2, -1, True, 1.5, "0"):
        with pytest.raises(ValueError, match="side"):
            results.summary("job1", side=side)


def test_matches_paginates_runs_and_reports_total(tmp_path: Path):
    results, repository = seeded(tmp_path)
    for seed in range(3):
        append_run(repository, "B", seed, seed, 0)

    first = results.matches("job1", limit=2)

    assert set(first) == {"items", "total", "next_offset"}
    assert [item["sequence"] for item in first["items"]] == [1, 2]
    assert first["total"] == 3
    assert first["next_offset"] == 2

    tail = results.matches("job1", limit=2, offset=2)
    assert [item["sequence"] for item in tail["items"]] == [3]
    assert tail["total"] == 3
    assert tail["next_offset"] is None

    beyond = results.matches("job1", limit=2, offset=5)
    assert beyond == {"items": [], "total": 3, "next_offset": None}


def test_matches_returns_none_for_missing_job_and_empty_envelope_for_empty_job(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.matches("missing") is None
    assert results.matches("job1") == {"items": [], "total": 0, "next_offset": None}


def test_matches_validates_paging_bounds(tmp_path: Path):
    results, _ = seeded(tmp_path)

    for limit in (0, 201, True, 1.0, "2"):
        with pytest.raises(ValueError, match="limit"):
            results.matches("job1", limit=limit)
    for offset in (-1, True, 1.0, "0"):
        with pytest.raises(ValueError, match="offset"):
            results.matches("job1", offset=offset)


def test_export_csv_writes_fixed_header_and_serializes_rows(tmp_path: Path):
    results, repository = seeded(tmp_path)
    append_run(
        repository,
        "A",
        5,
        2,
        1,
        stats={"teams": [{"xg": 1.5}, {"xg": 0.5}]},
        events={"goals": [{"side": 0, "clock": 12}]},
    )
    append_run(repository, "B", 6, None, None, stats={}, events=None, verified=False)

    text = results.export_csv("job1")

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == CSV_COLUMNS
    assert len(rows) == 3
    first = rows[1]
    assert first[0] == "job1"
    assert first[1:6] == ["1", "A", "5", "2", "1"]
    assert first[6] == "true"
    datetime.fromisoformat(first[7])
    assert json.loads(first[8]) == {"teams": [{"xg": 1.5}, {"xg": 0.5}]}
    assert json.loads(first[9]) == {"goals": [{"side": 0, "clock": 12}]}
    second = rows[2]
    assert second[1:6] == ["2", "B", "6", "", ""]
    assert second[6] == "false"
    assert second[8] == "{}"
    assert second[9] == ""


def test_export_csv_escapes_rfc4180_fields_and_is_deterministic(tmp_path: Path):
    results, repository = seeded(tmp_path)
    stats = {"note": 'a,b"c', "text": "中文"}
    events = {"detail": 'x,y"z'}
    append_run(repository, "A", 1, 1, 0, stats=stats, events=events)

    text = results.export_csv("job1")

    assert text == results.export_csv("job1")
    assert text.endswith("\r\n")
    assert text.count("\r\n") == 2
    assert '""' in text
    rows = list(csv.reader(io.StringIO(text)))
    assert json.loads(rows[1][8]) == stats
    assert json.loads(rows[1][9]) == events


def test_export_csv_writes_repository_stats_unchanged(tmp_path: Path):
    results, repository = seeded(tmp_path)
    stats = stats_payload()
    append_run(repository, "A", 1, 3, 2, stats=stats)

    rows = list(csv.reader(io.StringIO(results.export_csv("job1"))))

    assert json.loads(rows[1][8]) == stats
    assert rows[1][9] == ""


class StoredRunRepository:
    def __init__(self, job: dict, runs: list[dict]):
        self.job = job
        self.rows = runs

    def get(self, job_id: str) -> dict | None:
        return self.job if job_id == self.job["id"] else None

    def runs(self, job_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        return self.rows[offset : offset + limit]

    def run_count(self, job_id: str) -> int:
        return len(self.rows)


def test_export_csv_escapes_non_json_fields_with_commas_quotes_and_newlines():
    variant = 'A,"quoted"\nline'
    job = {"id": "job1"}
    run = {
        "job_id": "job1",
        "sequence": 1,
        "variant": variant,
        "seed": 7,
        "score": [2, 1],
        "verified": True,
        "stats": {},
        "events": None,
        "log_path": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    results = ResultsService(StoredRunRepository(job, [run]))

    text = results.export_csv("job1")

    assert text.count("\r\n") == 2
    rows = list(csv.reader(io.StringIO(text)))
    assert len(rows) == 2
    assert rows[1][2] == variant
    assert rows[1][4:6] == ["2", "1"]


def test_export_csv_orders_rows_by_sequence(tmp_path: Path):
    results, repository = seeded(tmp_path)
    repository.add_run(
        "job1",
        {"sequence": 3, "variant": "A", "seed": 9, "score_home": 0, "score_away": 0, "stats": {}},
    )
    repository.add_run(
        "job1",
        {"sequence": 1, "variant": "B", "seed": 8, "score_home": 0, "score_away": 0, "stats": {}},
    )

    rows = list(csv.reader(io.StringIO(results.export_csv("job1"))))

    assert [row[1] for row in rows[1:]] == ["1", "3"]


def test_export_csv_returns_none_for_missing_job(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.export_csv("missing") is None


def pool_config(entry_count: int = 2, **overrides) -> dict:
    value = {
        "enabled": True,
        "entries": [
            {"name": f"客队战术 {index + 1}", "weight": index + 1, "tactic": {}}
            for index in range(entry_count)
        ],
        "uniform": {"enabled": True, "attribute_value": 15},
        "rotation": {"enabled": False, "rounds": 1},
        "real": {"enabled": False},
    }
    value.update(overrides)
    return value


DISABLED_POOL = {
    "enabled": False,
    "entry_count": 0,
    "mode": None,
    "players": None,
    "draws": {},
}


def test_pool_summary_without_pool_config_is_disabled(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.pool_summary("job1") == DISABLED_POOL


@pytest.mark.parametrize("key", ["away_tactic_pool", "tactic_pool"])
def test_pool_summary_with_empty_entries_is_disabled(tmp_path: Path, key: str):
    results, _ = seeded(tmp_path, config={key: {"enabled": True, "entries": []}})

    assert results.pool_summary("job1") == DISABLED_POOL


def test_pool_summary_reports_random_mode_probabilities_and_uniform(tmp_path: Path):
    results, repository = seeded(tmp_path, config={"away_tactic_pool": pool_config()})
    append_run(repository, "A", 1, 1, 0, stats={})

    summary = results.pool_summary("job1")

    assert set(summary) == {
        "enabled",
        "entry_count",
        "mode",
        "rounds",
        "players",
        "uniform",
        "entries",
        "draws",
    }
    assert summary["enabled"] is True
    assert summary["entry_count"] == 2
    assert summary["mode"] == "random"
    assert summary["rounds"] == 1
    assert summary["players"] == "uniform"
    assert summary["uniform"] == {"enabled": True, "attribute_value": 15}
    assert [row["index"] for row in summary["entries"]] == [0, 1]
    assert [row["name"] for row in summary["entries"]] == ["客队战术 1", "客队战术 2"]
    assert [row["weight"] for row in summary["entries"]] == [1, 2]
    assert summary["entries"][0]["probability"] == pytest.approx(1 / 3)
    assert summary["entries"][1]["probability"] == pytest.approx(2 / 3)
    assert all(row["roster"] is False for row in summary["entries"])
    assert summary["draws"] == {"0": 0, "1": 0}


def test_pool_summary_reports_rotation_mode_and_rounds(tmp_path: Path):
    results, _ = seeded(
        tmp_path,
        config={"away_tactic_pool": pool_config(3, rotation={"enabled": True, "rounds": 2})},
    )

    summary = results.pool_summary("job1")

    assert summary["mode"] == "rotation"
    assert summary["rounds"] == 2
    assert summary["entry_count"] == 3
    assert all(row["probability"] is None for row in summary["entries"])
    assert summary["draws"] == {"0": 0, "1": 0, "2": 0}


def test_pool_summary_reports_top_level_rounds_for_random_mode(tmp_path: Path):
    results, _ = seeded(tmp_path, config={"tactic_pool": pool_config(rotation=False, rounds=3)})

    summary = results.pool_summary("job1")

    assert summary["mode"] == "random"
    assert summary["rounds"] == 3


def test_pool_summary_projects_real_roster_uniform_and_entry_flags(tmp_path: Path):
    config = pool_config(2, real={"enabled": True}, uniform={"enabled": True, "attribute_value": 18})
    config["entries"][1]["roster"] = {"players": []}
    results, _ = seeded(tmp_path, config={"away_tactic_pool": config})

    summary = results.pool_summary("job1")

    assert summary["players"] == "real"
    assert summary["uniform"] == {"enabled": True, "attribute_value": 18}
    assert [row["roster"] for row in summary["entries"]] == [False, True]


def test_pool_summary_accepts_squad_source_alias_for_real_roster(tmp_path: Path):
    config = pool_config(2)
    config.pop("real")
    config["squad_source"] = {"enabled": True}
    results, _ = seeded(tmp_path, config={"away_tactic_pool": config})

    assert results.pool_summary("job1")["players"] == "real"


def test_pool_summary_counts_completed_draws_from_run_stats(tmp_path: Path):
    results, repository = seeded(tmp_path, config={"away_tactic_pool": pool_config(2)})
    append_run(repository, "A", 11, 2, 0, stats={"tactic_pool_entry": 0})
    append_run(repository, "B", 11, 1, 0, stats={"tactic_pool_entry": 0})
    append_run(repository, "A", 12, 0, 1, stats={"tactic_pool_entry": {"index": 1}})
    append_run(repository, "B", 12, 2, 2, stats={"tactic_pool_entry": {"index": 1}})
    append_run(repository, "A", 13, 1, 1, stats={})

    assert results.pool_summary("job1")["draws"] == {"0": 1, "1": 1}


def test_pool_summary_ignores_runs_without_pool_entry(tmp_path: Path):
    results, repository = seeded(tmp_path, config={"away_tactic_pool": pool_config(2)})
    append_run(repository, "A", 1, 1, 0, stats={})
    append_run(repository, "B", 1, 0, 0, stats={"teams": []})

    assert results.pool_summary("job1")["draws"] == {"0": 0, "1": 0}


def test_pool_summary_defaults_enabled_to_true(tmp_path: Path):
    config = pool_config(2)
    config.pop("enabled")
    results, _ = seeded(tmp_path, config={"away_tactic_pool": config})

    summary = results.pool_summary("job1")

    assert summary["enabled"] is True
    assert summary["mode"] == "random"


def test_pool_summary_disabled_pool_keeps_entry_count(tmp_path: Path):
    results, _ = seeded(tmp_path, config={"away_tactic_pool": pool_config(2, enabled=False)})

    assert results.pool_summary("job1") == {
        "enabled": False,
        "entry_count": 2,
        "mode": None,
        "players": None,
        "draws": {},
    }


def test_pool_summary_prefers_away_tactic_pool_config(tmp_path: Path):
    config = {
        "away_tactic_pool": {"entries": [{"name": "优先池", "weight": 1}]},
        "tactic_pool": {"entries": [{"name": "旧池一", "weight": 1}, {"name": "旧池二", "weight": 1}]},
    }
    results, _ = seeded(tmp_path, config=config)

    summary = results.pool_summary("job1")

    assert summary["entry_count"] == 1
    assert [row["name"] for row in summary["entries"]] == ["优先池"]


def test_pool_summary_counts_rotation_draws_across_rounds(tmp_path: Path):
    results, repository = seeded(
        tmp_path,
        config={"away_tactic_pool": pool_config(3, rotation={"enabled": True, "rounds": 2})},
    )
    for seed in range(6):
        entry = seed % 3
        append_run(repository, "A", seed, 1, 0, stats={"tactic_pool_entry": entry})
        append_run(repository, "B", seed, 1, 0, stats={"tactic_pool_entry": {"index": entry}})

    assert results.pool_summary("job1")["draws"] == {"0": 2, "1": 2, "2": 2}


def test_pool_summary_returns_none_for_missing_job(tmp_path: Path):
    results, _ = seeded(tmp_path)

    assert results.pool_summary("missing") is None


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"away_tactic_pool": "bad"}, "客队战术池"),
        ({"tactic_pool": 1}, "客队战术池"),
        ({"away_tactic_pool": {}}, "条目"),
        ({"away_tactic_pool": {"entries": "bad"}}, "条目"),
        ({"away_tactic_pool": {"entries": [{"weight": 1}]}}, "名称"),
        ({"away_tactic_pool": {"entries": [{"name": "客队", "weight": 0}]}}, "权重"),
        ({"away_tactic_pool": {"entries": [{"name": "客队"}], "uniform": "bad"}}, "统一属性"),
        ({"away_tactic_pool": {"entries": [{"name": "客队"}], "rotation": {"enabled": "yes"}}}, "布尔值"),
        (
            {"away_tactic_pool": {"entries": [{"name": "客队"}], "rotation": {"enabled": True, "rounds": 0}}},
            "轮数",
        ),
    ],
)
def test_pool_summary_rejects_invalid_pool_config(tmp_path: Path, config: dict, message: str):
    results, _ = seeded(tmp_path, config=config)

    with pytest.raises(ValueError, match=message):
        results.pool_summary("job1")


@pytest.mark.parametrize("enabled", ["yes", 1, None])
def test_pool_summary_rejects_non_boolean_enabled(tmp_path: Path, enabled):
    config = pool_config(1)
    config["enabled"] = enabled
    results, _ = seeded(tmp_path, config={"away_tactic_pool": config})

    with pytest.raises(ValueError, match="开关"):
        results.pool_summary("job1")


def test_pool_summary_rejects_non_mapping_job_config():
    results = ResultsService(StoredRunRepository({"id": "job1", "config": "bad"}, []))

    with pytest.raises(ValueError, match="任务配置"):
        results.pool_summary("job1")
