from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository


def repository(tmp_path: Path) -> JobRepository:
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    return JobRepository(database)


def job(job_id: str, name: str, status: str = "queued", created_at: str | None = None) -> dict:
    value = {"id": job_id, "kind": "experiment", "status": status, "name": name, "total": 4}
    if created_at is not None:
        value["created_at"] = created_at
    return value


def identifiers(repo: JobRepository, **filters) -> list[str]:
    return [item["id"] for item in repo.list(**filters)]


def test_query_matches_name_or_id_and_ignores_ascii_case(tmp_path: Path):
    repo = repository(tmp_path)
    repo.add(job("job-seeds", "种子扫描"))
    repo.add(job("job-cases", "Case Study"))
    repo.add(job("unrelated", "其他实验"))
    assert identifiers(repo, q="种子") == ["job-seeds"]
    assert identifiers(repo, q="种子扫描") == ["job-seeds"]
    assert identifiers(repo, q="case") == ["job-cases"]
    assert identifiers(repo, q="CASE") == ["job-cases"]
    assert identifiers(repo, q="job-cases") == ["job-cases"]
    assert identifiers(repo, q="missing") == []
    assert repo.count(q="种子") == 1
    assert repo.count(q="case") == 1
    assert repo.count(q="missing") == 0


def test_query_treats_like_wildcards_and_backslashes_as_literals(tmp_path: Path):
    repo = repository(tmp_path)
    repo.add(job("job-percent", "100% 覆盖"))
    repo.add(job("job-underscore", "a_b"))
    repo.add(job("job-wildcard", "axb"))
    repo.add(job("job-slash", "back\\slash"))
    assert identifiers(repo, q="100%") == ["job-percent"]
    assert identifiers(repo, q="%") == ["job-percent"]
    assert identifiers(repo, q="_") == ["job-underscore"]
    assert identifiers(repo, q="a_b") == ["job-underscore"]
    assert identifiers(repo, q="a%") == []
    assert identifiers(repo, q="\\") == ["job-slash"]
    assert identifiers(repo, q="back\\slash") == ["job-slash"]
    assert repo.count(q="%") == 1
    assert repo.count(q="a_b") == 1


def test_query_combines_with_status_and_pagination(tmp_path: Path):
    repo = repository(tmp_path)
    repo.add(job("job-alpha-1", "Alpha", "queued", "2000-01-01T00:00:00+00:00"))
    repo.add(job("job-alpha-2", "Alpha", "running", "2000-01-02T00:00:00+00:00"))
    repo.add(job("job-alpha-3", "Alpha", "running", "2000-01-03T00:00:00+00:00"))
    repo.add(job("job-beta", "Beta", "running", "2000-01-04T00:00:00+00:00"))
    assert identifiers(repo, q="alpha", status="running") == ["job-alpha-3", "job-alpha-2"]
    assert identifiers(repo, q="alpha") == ["job-alpha-3", "job-alpha-2", "job-alpha-1"]
    assert identifiers(repo, q="alpha", limit=1, offset=1) == ["job-alpha-2"]
    assert identifiers(repo, q="alpha", status="completed") == []
    assert repo.count(q="alpha", status="running") == 2
    assert repo.count(q="alpha") == 3
    assert repo.count(status="running") == 3


def test_query_normalizes_input_and_validates_length(tmp_path: Path):
    repo = repository(tmp_path)
    repo.add(job("job-seeds", "种子扫描"))
    assert identifiers(repo, q="  种子  ") == ["job-seeds"]
    assert repo.count(q="  种子  ") == 1
    assert identifiers(repo, q="") == ["job-seeds"]
    assert identifiers(repo, q=None) == ["job-seeds"]
    assert repo.count(q="   ") == 1
    assert identifiers(repo, q="x" * 100) == []
    for invalid in ("x" * 101, ["q"], 5):
        with pytest.raises(ValueError, match="关键字"):
            repo.list(q=invalid)
        with pytest.raises(ValueError, match="关键字"):
            repo.count(q=invalid)
