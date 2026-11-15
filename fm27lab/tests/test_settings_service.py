from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.settings import SettingsService

SETTING_FIELDS = {"key", "value", "note", "updated_at"}


def database(tmp_path: Path) -> Database:
    value = Database(tmp_path / "fm27lab.db")
    value.initialize()
    return value


def service(tmp_path: Path) -> SettingsService:
    return SettingsService(SettingsRepository(database(tmp_path)))


def test_set_get_round_trip_with_metadata(tmp_path: Path):
    settings = service(tmp_path)
    created = settings.set("match.roster_size", {"size": 23, "labels": ["主", "客"]}, note="fixed")
    assert set(created) == SETTING_FIELDS
    assert created["key"] == "match.roster_size"
    assert created["value"] == {"size": 23, "labels": ["主", "客"]}
    assert created["note"] == "fixed"
    assert created["updated_at"].endswith("+00:00")
    datetime.fromisoformat(created["updated_at"])
    assert settings.get("match.roster_size") == created
    assert settings.get("missing") is None


@pytest.mark.parametrize("value", [None, True, 0, 1.5, "text", [], {}, [1, {"a": None}]])
def test_set_accepts_json_serializable_values(tmp_path: Path, value):
    settings = service(tmp_path)
    created = settings.set("value.key", value)
    assert created["value"] == value
    assert settings.get("value.key")["value"] == value


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {1, 2},
        b"bytes",
        object(),
        {"nested": [float("nan")]},
        datetime(2026, 1, 1),
    ],
)
def test_set_rejects_non_json_values(tmp_path: Path, value):
    settings = service(tmp_path)
    with pytest.raises(ValueError):
        settings.set("value.key", value)
    assert settings.all() == []


def test_set_validates_key(tmp_path: Path):
    settings = service(tmp_path)
    for key in (
        "",
        "A",
        "1starts_with_digit",
        "_leading_underscore",
        "contains space",
        "contains/slash",
        "设置",
        "a" * 65,
        None,
        1,
    ):
        with pytest.raises(ValueError, match="设置键"):
            settings.set(key, 1)


@pytest.mark.parametrize(
    "key",
    ["a", "a1", "match.roster_size", "a-b_c.d", "a" * 64],
)
def test_set_accepts_valid_keys(tmp_path: Path, key):
    settings = service(tmp_path)
    assert settings.set(key, 1)["key"] == key


def test_set_validates_note(tmp_path: Path):
    settings = service(tmp_path)
    for note in ("", "\nline", "tab\there", "\x7f", "n" * 201, 1, ["note"], "bad\ud800"):
        with pytest.raises(ValueError, match="备注"):
            settings.set("note.key", 1, note=note)
    assert settings.all() == []
    boundary = "n" * 200
    assert settings.set("note.key", 1, note=boundary)["note"] == boundary
    assert settings.set("note.key", 2, note=None)["note"] is None


def test_set_upserts_and_keeps_single_row(tmp_path: Path):
    settings = service(tmp_path)
    first = settings.set("match.workers", 4, note="first")
    second = settings.set("match.workers", 8, note="second")
    assert second["value"] == 8
    assert second["note"] == "second"
    assert settings.get("match.workers")["value"] == 8
    assert settings.all() == [second]
    assert second["updated_at"] >= first["updated_at"]
    without_note = settings.set("match.workers", 16)
    assert without_note["note"] is None
    assert settings.get("match.workers") == without_note


def test_all_orders_keys_and_includes_metadata(tmp_path: Path):
    settings = service(tmp_path)
    assert settings.all() == []
    third = settings.set("zzz.last", 3, note="z")
    first = settings.set("aaa.first", 1)
    second = settings.set("mmm.middle", [2])
    listed = settings.all()
    assert [item["key"] for item in listed] == ["aaa.first", "mmm.middle", "zzz.last"]
    assert listed == [first, second, third]
    for item in listed:
        assert set(item) == SETTING_FIELDS


def test_delete_reports_existence(tmp_path: Path):
    settings = service(tmp_path)
    settings.set("drop.me", 1, note="gone")
    assert settings.delete("drop.me") is True
    assert settings.get("drop.me") is None
    assert settings.delete("drop.me") is False
    assert settings.delete("never.existed") is False


def test_invalid_key_is_rejected_on_read_and_delete(tmp_path: Path):
    settings = service(tmp_path)
    for key in ("Bad-Key", "1bad", ""):
        with pytest.raises(ValueError, match="设置键"):
            settings.get(key)
        with pytest.raises(ValueError, match="设置键"):
            settings.delete(key)


def test_service_reads_rows_written_through_repository(tmp_path: Path):
    database_value = database(tmp_path)
    repository = SettingsRepository(database_value)
    repository.set("external.key", {"raw": 1}, note="external")
    settings = SettingsService(repository)
    fetched = settings.get("external.key")
    assert fetched["value"] == {"raw": 1}
    assert fetched["note"] == "external"
    datetime.fromisoformat(fetched["updated_at"])

    settings.set("service.key", [1, 2], note="service")
    assert repository.get("service.key") == [1, 2]
    with closing(database_value.connect()) as connection:
        row = connection.execute("SELECT note, updated_at FROM settings WHERE key='service.key'").fetchone()
    assert row["note"] == "service"
    assert settings.get("service.key")["updated_at"] == row["updated_at"]


def test_stored_value_is_json_normalized(tmp_path: Path):
    settings = service(tmp_path)
    stored = settings.set("tuple.key", (1, 2))
    assert stored["value"] == [1, 2]
    with closing(Database(tmp_path / "fm27lab.db").connect()) as connection:
        raw = connection.execute("SELECT value_json FROM settings WHERE key='tuple.key'").fetchone()[0]
    assert json.loads(raw) == [1, 2]


def nested_list(depth: int) -> Any:
    value: Any = 0
    for _ in range(depth):
        value = [value]
    return value


def test_set_accepts_maximum_nesting_depth(tmp_path: Path):
    settings = service(tmp_path)
    value = nested_list(64)
    created = settings.set("deep.key", value)
    assert created["value"] == value
    assert settings.get("deep.key")["value"] == value


@pytest.mark.parametrize("depth", [65, 256, 5000])
def test_set_rejects_too_deep_values(tmp_path: Path, depth):
    settings = service(tmp_path)
    with pytest.raises(ValueError, match="嵌套过深"):
        settings.set("deep.key", nested_list(depth))
    assert settings.all() == []


def test_set_rejects_too_deep_dict_values(tmp_path: Path):
    settings = service(tmp_path)
    value: Any = 0
    for _ in range(65):
        value = {"level": value}
    with pytest.raises(ValueError, match="嵌套过深"):
        settings.set("deep.key", value)
    assert settings.all() == []


def test_set_rejects_oversized_values(tmp_path: Path):
    settings = service(tmp_path)
    boundary = "x" * (65536 - 2)
    stored = settings.set("large.key", boundary)
    assert stored["value"] == boundary
    with pytest.raises(ValueError, match="设置值过大"):
        settings.set("large.other", "x" * (65536 - 1))
    with pytest.raises(ValueError, match="设置值过大"):
        settings.set("large.chinese", "设" * 30000)
    assert [item["key"] for item in settings.all()] == ["large.key"]


def test_set_rejects_circular_values(tmp_path: Path):
    settings = service(tmp_path)
    cyclic_list: list = []
    cyclic_list.append(cyclic_list)
    cyclic_dict: dict = {}
    cyclic_dict["self"] = cyclic_dict
    for value in (cyclic_list, cyclic_dict):
        with pytest.raises(ValueError):
            settings.set("cycle.key", value)
    assert settings.all() == []


def test_set_rejects_surrogate_and_keeps_previous_value(tmp_path: Path):
    settings = service(tmp_path)
    settings.set("keep.key", {"ok": True}, note="keep")
    with pytest.raises(ValueError, match="设置值"):
        settings.set("keep.key", "bad\ud800")
    entry = settings.get("keep.key")
    assert entry["value"] == {"ok": True}
    assert entry["note"] == "keep"
    with pytest.raises(ValueError, match="设置值过大"):
        settings.set("keep.key", "x" * 70000)
    assert settings.get("keep.key")["value"] == {"ok": True}
