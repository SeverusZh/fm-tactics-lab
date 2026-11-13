from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.artifacts import ArtifactRepository
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import JobRepository
from fm27lab.application.artifacts import ArtifactService

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CONTENT = b"hello world"
CONTENT_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def build(tmp_path: Path) -> tuple[ArtifactService, ArtifactRepository, Database]:
    db = database(tmp_path)
    repository = ArtifactRepository(db)
    return ArtifactService(repository, tmp_path / "artifacts"), repository, db


def job(**extra: object) -> dict:
    value = {"id": "job1", "kind": "experiment", "status": "queued", "config": {}}
    value.update(extra)
    return value


def assert_nothing_stored(tmp_path: Path, repository: ArtifactRepository) -> None:
    assert repository.list() == []
    assert not (tmp_path / "artifacts").exists()


def test_register_bytes_writes_file_and_record(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)

    record = artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)

    assert ID_PATTERN.fullmatch(record["id"])
    assert record["kind"] == "fmf"
    assert record["job_id"] is None
    assert record["sha256"] == CONTENT_SHA256
    assert record["bytes"] == len(CONTENT) == 11
    stored = Path(record["path"])
    assert stored.resolve() == (tmp_path / "artifacts" / "fmf" / "tactic.fmf").resolve()
    assert stored.read_bytes() == CONTENT
    datetime.fromisoformat(record["created_at"])
    assert artifacts.get(record["id"]) == record
    assert repository.list() == [record]
    assert sorted(path.name for path in stored.parent.iterdir()) == ["tactic.fmf"]


def test_register_bytes_accepts_empty_content(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)

    record = artifacts.register_bytes(kind="empty", filename="empty.bin", content=b"")

    assert record["bytes"] == 0
    assert record["sha256"] == hashlib.sha256(b"").hexdigest()
    assert Path(record["path"]).read_bytes() == b""


def test_register_text_writes_utf8_bytes(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)

    record = artifacts.register_text(kind="report", filename="note.txt", text="战术导出 α")

    stored = Path(record["path"]).read_bytes()
    assert stored == "战术导出 α".encode()
    assert record["bytes"] == len(stored)
    assert record["sha256"] == hashlib.sha256(stored).hexdigest()


def test_register_links_job_and_list_filters(tmp_path: Path):
    artifacts, repository, db = build(tmp_path)
    jobs = JobRepository(db)
    jobs.add(job())
    jobs.add(job(id="job2"))

    first = artifacts.register_bytes(kind="fmf", filename="a.fmf", content=b"a", job_id="job1")
    second = artifacts.register_text(kind="csv", filename="b.csv", text="x,y")
    third = artifacts.register_bytes(kind="fmf", filename="c.fmf", content=b"c", job_id="job2")

    assert first["job_id"] == "job1"
    assert second["job_id"] is None
    assert third["job_id"] == "job2"
    listed = artifacts.list()
    assert set(listed) == {"items", "total", "next_offset"}
    assert {item["id"] for item in listed["items"]} == {first["id"], second["id"], third["id"]}
    assert listed["total"] == 3
    assert listed["next_offset"] is None
    fmf = artifacts.list(kind="fmf")
    assert {item["id"] for item in fmf["items"]} == {first["id"], third["id"]}
    assert fmf["total"] == 2
    linked = artifacts.list(job_id="job1")
    assert [item["id"] for item in linked["items"]] == [first["id"]]
    assert linked["total"] == 1
    assert artifacts.list(kind="csv")["total"] == 1


def test_duplicate_filename_is_rejected_without_overwriting(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    first = artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)
    stored = Path(first["path"])

    with pytest.raises(ValueError, match="产物文件已存在"):
        artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=b"replacement")

    assert stored.read_bytes() == CONTENT
    assert artifacts.list()["total"] == 1
    other_kind = artifacts.register_bytes(kind="csv", filename="tactic.fmf", content=b"replacement")
    assert other_kind["kind"] == "csv"
    assert artifacts.list()["total"] == 2


def test_duplicate_filename_is_rejected_when_record_exists_but_file_is_missing(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)
    record = artifacts.register_bytes(kind="fmf", filename="gone.fmf", content=CONTENT)
    Path(record["path"]).unlink()

    with pytest.raises(ValueError, match="产物文件已存在"):
        artifacts.register_bytes(kind="fmf", filename="gone.fmf", content=CONTENT)

    assert artifacts.list()["total"] == 1


@pytest.mark.parametrize(
    "filename",
    [
        "",
        ".",
        "..",
        "../evil.txt",
        "a/b.txt",
        "/tmp/evil.txt",
        "a\\b.txt",
        ".hidden",
        "with space.txt",
        "键.txt",
        "x" * 129,
    ],
)
def test_register_rejects_unsafe_filenames(tmp_path: Path, filename: str):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="产物文件名无效"):
        artifacts.register_bytes(kind="fmf", filename=filename, content=CONTENT)

    assert_nothing_stored(tmp_path, repository)


def test_register_accepts_maximum_filename_length(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)

    record = artifacts.register_bytes(kind="fmf", filename="a" * 128, content=b"x")

    assert Path(record["path"]).name == "a" * 128


@pytest.mark.parametrize("kind", ["", ".", "..", "../escape", "a/b", "a\\b", "键", "x" * 65, None, 7])
def test_register_rejects_unsafe_kind(tmp_path: Path, kind: object):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="产物类型无效"):
        artifacts.register_bytes(kind=kind, filename="tactic.fmf", content=CONTENT)

    assert_nothing_stored(tmp_path, repository)


@pytest.mark.parametrize("content", ["text", bytearray(b"x"), None, 7, ["x"]])
def test_register_bytes_rejects_non_bytes_content(tmp_path: Path, content: object):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="产物内容必须为字节"):
        artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=content)

    assert_nothing_stored(tmp_path, repository)


def test_register_text_rejects_non_text_content(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="产物内容必须为文本"):
        artifacts.register_text(kind="report", filename="note.txt", text=b"bytes")

    assert_nothing_stored(tmp_path, repository)


def test_register_text_rejects_unencodable_text(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="UTF-8"):
        artifacts.register_text(kind="report", filename="note.txt", text="\ud800")

    assert_nothing_stored(tmp_path, repository)


def test_register_rejects_symlink_escape(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    directory = tmp_path / "artifacts" / "fmf"
    directory.mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")
    (directory / "link.fmf").symlink_to(outside)

    with pytest.raises(ValueError, match="产物路径无效"):
        artifacts.register_bytes(kind="fmf", filename="link.fmf", content=b"new")

    assert outside.read_bytes() == b"secret"
    assert repository.list() == []


def test_register_rejects_kind_directory_symlink_outside_root(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "fmf").symlink_to(outside)

    with pytest.raises(ValueError, match="产物路径无效"):
        artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)

    assert list(outside.iterdir()) == []
    assert repository.list() == []


def test_register_rejects_kind_directory_symlink_inside_root(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    root = tmp_path / "artifacts"
    real = root / "real"
    real.mkdir(parents=True)
    (root / "fmf").symlink_to(real)

    with pytest.raises(ValueError, match="产物路径无效"):
        artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)

    assert list(real.iterdir()) == []
    assert repository.list() == []

    record = artifacts.register_bytes(kind="csv", filename="ok.csv", content=CONTENT)
    assert Path(record["path"]).parent == (root / "csv").resolve()
    assert Path(record["path"]).read_bytes() == CONTENT


def test_register_rolls_back_file_when_repository_fails(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)

    with pytest.raises(ValueError, match="任务不存在"):
        artifacts.register_bytes(kind="fmf", filename="orphan.fmf", content=CONTENT, job_id="missingjob")

    directory = tmp_path / "artifacts" / "fmf"
    assert directory.is_dir()
    assert list(directory.iterdir()) == []
    assert repository.list() == []

    with pytest.raises(ValueError, match="任务标识无效"):
        artifacts.register_bytes(kind="fmf", filename="bad.fmf", content=CONTENT, job_id="a/b")
    assert list(directory.iterdir()) == []
    assert repository.list() == []


def test_delete_removes_record_and_file(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    record = artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)
    stored = Path(record["path"])

    assert artifacts.delete(record["id"]) is True

    assert artifacts.get(record["id"]) is None
    assert not stored.exists()
    assert repository.list() == []
    assert artifacts.delete(record["id"]) is False
    assert artifacts.delete("missing") is False


def test_delete_tolerates_missing_file(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)
    record = artifacts.register_bytes(kind="fmf", filename="tactic.fmf", content=CONTENT)
    Path(record["path"]).unlink()

    assert artifacts.delete(record["id"]) is True
    assert artifacts.get(record["id"]) is None


def test_delete_only_removes_files_inside_root(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    repository.add({"id": "outside", "kind": "fmf", "path": str(outside), "sha256": "a" * 64, "bytes": 4})
    tricky_path = tmp_path / "artifacts" / "fmf" / ".." / ".." / "outside.txt"
    repository.add({"id": "tricky", "kind": "fmf", "path": str(tricky_path), "sha256": "a" * 64, "bytes": 4})

    assert artifacts.delete("outside") is True
    assert artifacts.delete("tricky") is True

    assert outside.read_bytes() == b"keep"
    assert artifacts.get("outside") is None
    assert artifacts.get("tricky") is None


def test_delete_does_not_follow_symlinks_outside_root(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep")
    directory = tmp_path / "artifacts" / "fmf"
    directory.mkdir(parents=True)
    link = directory / "link.fmf"
    link.symlink_to(outside)
    repository.add({"id": "link", "kind": "fmf", "path": str(link), "sha256": "a" * 64, "bytes": 4})

    assert artifacts.delete("link") is True

    assert artifacts.get("link") is None
    assert outside.read_bytes() == b"keep"
    assert not link.is_symlink()


def test_delete_removes_root_symlink_itself_and_keeps_target(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    root = tmp_path / "artifacts"
    directory = root / "fmf"
    directory.mkdir(parents=True)
    target = root / "target.txt"
    target.write_bytes(b"target")
    link = directory / "link.txt"
    link.symlink_to(target)
    repository.add({"id": "link-inside", "kind": "fmf", "path": str(link), "sha256": "a" * 64, "bytes": 6})

    assert artifacts.delete("link-inside") is True

    assert artifacts.get("link-inside") is None
    assert not link.is_symlink()
    assert not link.exists()
    assert target.read_bytes() == b"target"


def test_list_computes_total_across_pages(tmp_path: Path):
    artifacts, repository, _ = build(tmp_path)
    for index in range(300):
        repository.add(
            {
                "id": f"a{index:04d}",
                "kind": "fmf",
                "path": f"p{index}",
                "sha256": "a" * 64,
                "bytes": 0,
            }
        )

    first = artifacts.list(limit=50)
    assert first["total"] == 300
    assert len(first["items"]) == 50
    assert first["next_offset"] == 50

    tail = artifacts.list(limit=50, offset=250)
    assert len(tail["items"]) == 50
    assert tail["total"] == 300
    assert tail["next_offset"] is None

    beyond = artifacts.list(limit=50, offset=350)
    assert beyond == {"items": [], "total": 300, "next_offset": None}
    assert artifacts.list(kind="csv") == {"items": [], "total": 0, "next_offset": None}


def test_list_validates_paging_bounds(tmp_path: Path):
    artifacts, _, _ = build(tmp_path)

    for limit in (0, 257, True, 1.0, "50"):
        with pytest.raises(ValueError, match="limit"):
            artifacts.list(limit=limit)
    for offset in (-1, True, 1.0, "0"):
        with pytest.raises(ValueError, match="offset"):
            artifacts.list(offset=offset)
