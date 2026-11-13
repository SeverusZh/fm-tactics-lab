from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.catalog_native.catalog import CatalogRepository
from fm27lab.application.catalog import CatalogService

CATALOG_ERROR = "目录文件无效"
REQUIRED_SECTIONS = ("positions", "roles", "team_instructions", "mentalities")
OPTIONAL_SECTIONS = ("attributes", "player_instructions")
TRIMMED_SECTIONS = REQUIRED_SECTIONS + OPTIONAL_SECTIONS


def catalog_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 3,
        "positions": [{"id": "GK", "mask": 1, "x": 50, "y": 92}],
        "roles": [{"id": "GK_D", "label": "门将", "phase": 0, "flags": "0"}],
        "team_instructions": [{"id": 1, "label": "宽度", "options": [{"id": 1, "native_bit": 0}]}],
        "mentalities": [{"id": 1, "label": "极度防守"}],
        "attributes": [{"index": 0, "label": "速度"}],
        "player_instructions": [{"id": 1, "label": "贴身盯防"}],
        "policy_versions": ["1a080000"],
    }
    payload.update(overrides)
    return payload


def write_catalog(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def make_repository(tmp_path: Path) -> CatalogRepository:
    return CatalogRepository(tmp_path / "engine", tmp_path / "data")


def test_load_reads_native_engine_workspace(tmp_path: Path):
    write_catalog(tmp_path / "engine" / "fm27_native" / "catalog.json", catalog_payload())
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert loaded["positions"] == catalog_payload()["positions"]
    assert loaded["mentalities"] == catalog_payload()["mentalities"]


def test_load_reads_engine_root(tmp_path: Path):
    write_catalog(tmp_path / "engine" / "catalog.json", catalog_payload(positions=[{"id": "ENGINE"}]))
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert loaded["positions"] == [{"id": "ENGINE"}]


def test_load_reads_data_directory(tmp_path: Path):
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload(positions=[{"id": "DATA"}]))
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert loaded["positions"] == [{"id": "DATA"}]


def test_load_prefers_native_workspace_over_engine_root_and_data(tmp_path: Path):
    write_catalog(
        tmp_path / "engine" / "fm27_native" / "catalog.json", catalog_payload(positions=[{"id": "NATIVE"}])
    )
    write_catalog(tmp_path / "engine" / "catalog.json", catalog_payload(positions=[{"id": "ENGINE"}]))
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload(positions=[{"id": "DATA"}]))
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert loaded["positions"] == [{"id": "NATIVE"}]


def test_load_prefers_engine_root_over_data(tmp_path: Path):
    write_catalog(tmp_path / "engine" / "catalog.json", catalog_payload(positions=[{"id": "ENGINE"}]))
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload(positions=[{"id": "DATA"}]))
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert loaded["positions"] == [{"id": "ENGINE"}]


def test_load_without_engine_root_uses_data_directory(tmp_path: Path):
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload())
    loaded = CatalogRepository(None, tmp_path / "data").load()
    assert loaded is not None
    assert loaded["roles"] == catalog_payload()["roles"]


def test_load_trims_document_to_snapshot_sections(tmp_path: Path):
    payload = catalog_payload()
    write_catalog(tmp_path / "data" / "catalog.json", payload)
    loaded = make_repository(tmp_path).load()
    assert loaded == {section: payload[section] for section in TRIMMED_SECTIONS}


def test_load_omits_optional_sections_when_absent(tmp_path: Path):
    payload = catalog_payload()
    del payload["attributes"]
    del payload["player_instructions"]
    write_catalog(tmp_path / "data" / "catalog.json", payload)
    loaded = make_repository(tmp_path).load()
    assert loaded is not None
    assert set(loaded) == set(REQUIRED_SECTIONS)


def test_load_returns_none_when_no_catalog_exists(tmp_path: Path):
    assert make_repository(tmp_path).load() is None


@pytest.mark.parametrize("content", ["", "{", "[]", '"text"', "null"])
def test_load_rejects_invalid_documents(tmp_path: Path, content: str):
    path = tmp_path / "data" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=CATALOG_ERROR):
        make_repository(tmp_path).load()


def test_load_rejects_undecodable_file(tmp_path: Path):
    path = tmp_path / "data" / "catalog.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match=CATALOG_ERROR):
        make_repository(tmp_path).load()


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_load_rejects_missing_section(tmp_path: Path, section: str):
    payload = catalog_payload()
    del payload[section]
    write_catalog(tmp_path / "data" / "catalog.json", payload)
    with pytest.raises(ValueError, match=CATALOG_ERROR):
        make_repository(tmp_path).load()


@pytest.mark.parametrize("section", REQUIRED_SECTIONS)
def test_load_rejects_non_list_section(tmp_path: Path, section: str):
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload(**{section: {"id": 1}}))
    with pytest.raises(ValueError, match=CATALOG_ERROR):
        make_repository(tmp_path).load()


def test_load_reports_corrupt_preferred_file_without_falling_back(tmp_path: Path):
    broken = tmp_path / "engine" / "fm27_native" / "catalog.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload())
    with pytest.raises(ValueError, match=CATALOG_ERROR):
        make_repository(tmp_path).load()


class _StubRepository:
    def __init__(self, loaded: dict[str, Any] | None) -> None:
        self.loaded = loaded
        self.loads = 0

    def load(self) -> dict[str, Any] | None:
        self.loads += 1
        return self.loaded


def test_snapshot_reports_available_catalog(tmp_path: Path):
    write_catalog(tmp_path / "data" / "catalog.json", catalog_payload())
    service = CatalogService(make_repository(tmp_path))
    snapshot = service.snapshot()
    assert snapshot["available"] is True
    assert snapshot["catalog"] == {section: catalog_payload()[section] for section in TRIMMED_SECTIONS}


def test_snapshot_reports_unavailable_without_catalog(tmp_path: Path):
    snapshot = CatalogService(make_repository(tmp_path)).snapshot()
    assert snapshot == {"available": False, "catalog": None}


def test_snapshot_delegates_to_repository():
    loaded = {section: [] for section in REQUIRED_SECTIONS}
    repository = _StubRepository(loaded)
    snapshot = CatalogService(repository).snapshot()
    assert snapshot == {"available": True, "catalog": loaded}
    assert repository.loads == 1
