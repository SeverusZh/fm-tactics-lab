"""定位球应用服务测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import SettingsRepository
from fm27lab.application.setpieces import (
    DOCUMENT_FIELDS_ERROR,
    DOCUMENT_FORMAT_ERROR,
    DOCUMENT_JSON_ERROR,
    DOCUMENT_SCHEMA,
    DOCUMENT_SCHEMA_ERROR,
    DOCUMENT_SIZE_ERROR,
    DOCUMENT_TARGET_ERROR,
    DOCUMENT_TEXT_ERROR,
    DOCUMENT_VALUE_ERROR,
    ENGINE_UNAVAILABLE_MESSAGE,
    MAX_DOCUMENT_BYTES,
    SetpiecesService,
    SetpiecesUnavailable,
    UnknownSetpiece,
    parse_document,
)
from fm27lab.application.settings import SettingsService
from fm27lab.config import Settings
from fm27lab.tests.test_scenario_assets import write_engine_root

TOKEN = "c" * 64


def make_service(tmp_path: Path, *, engine_root: Path | None = None, root: Path | None = None) -> SetpiecesService:
    base = root or tmp_path
    if engine_root is None:
        engine_root = base / "engine"
        if not engine_root.exists():
            engine_root = write_engine_root(base)
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token=TOKEN,
        engine_root=engine_root,
        dev=True,
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    return SetpiecesService(SettingsService(SettingsRepository(database)), settings)


def test_catalog_exposes_ten_types_and_frequencies(tmp_path):
    catalog = make_service(tmp_path).catalog()
    assert [entry["id"] for entry in catalog["types"]] == list(range(10))
    assert catalog["types"][0]["label"] == "防守角球"
    assert catalog["types"][5]["strategy_kind"] == "corner_target"
    assert [entry["id"] for entry in catalog["frequencies"]] == [0, 1, 2]


def test_list_reports_both_sides_as_unconfigured(tmp_path):
    listing = make_service(tmp_path).list()
    assert [item["setpiece_id"] for item in listing["setpieces"]] == ["home", "away"]
    assert [item["team"] for item in listing["setpieces"]] == ["主队", "客队"]
    assert [item["side"] for item in listing["setpieces"]] == [0, 1]
    assert all(item["configured"] is False for item in listing["setpieces"])
    assert all(item["updated_at"] is None for item in listing["setpieces"])
    assert len(listing["catalog"]["types"]) == 10


def test_get_returns_default_value_and_roster(tmp_path):
    detail = make_service(tmp_path).get("home")
    assert detail["setpiece_id"] == "home"
    assert detail["configured"] is False
    assert detail["roster_size"] == 23
    assert len(detail["players"]) == 23
    assert detail["players"][0] == {"index": 0, "name": "主队球员 01"}
    assert detail["value"]["throw_styles"] == [0, 1, 0]
    assert detail["value"]["routines"]["0"][0]["name"] == "防守角球 1"
    assert detail["default"] == detail["value"]
    assert detail["value"] is not detail["default"]


def test_away_default_throw_styles_differ(tmp_path):
    service = make_service(tmp_path)
    assert service.get("away")["value"]["throw_styles"] == [1, 0, 0]


def test_get_rejects_unknown_setpiece(tmp_path):
    with pytest.raises(UnknownSetpiece):
        make_service(tmp_path).get("neutral")


def test_save_normalizes_and_persists(tmp_path):
    service = make_service(tmp_path)
    value = service.get("away")["value"]
    value["throw_styles"] = [0, 0, 1]
    value["routines"]["0"][0]["name"] = "改过的防守角球"
    saved = service.save("away", value)
    assert saved["configured"] is True
    assert saved["updated_at"] is not None
    assert saved["value"]["throw_styles"] == [0, 0, 1]
    assert saved["value"]["routines"]["0"][0]["name"] == "改过的防守角球"

    reopened = make_service(tmp_path)
    reloaded = reopened.get("away")
    assert reloaded["configured"] is True
    assert reloaded["value"]["throw_styles"] == [0, 0, 1]
    assert reopened.get("home")["configured"] is False


def test_save_rejects_non_mapping_value(tmp_path):
    service = make_service(tmp_path)
    with pytest.raises(ValueError) as caught:
        service.save("home", [])
    assert str(caught.value) == "定位球设置格式错误"


def test_save_rejects_invalid_throw_styles(tmp_path):
    service = make_service(tmp_path)
    value = service.get("home")["value"]
    value["throw_styles"] = [0, 1]
    with pytest.raises(ValueError) as caught:
        service.save("home", value)
    assert str(caught.value) == "界外球必须包含后场、中场和前场三种策略"


def test_save_rejects_routine_count_overflow(tmp_path):
    service = make_service(tmp_path)
    value = service.get("home")["value"]
    value["routines"]["0"].append(dict(value["routines"]["0"][0]))
    value["routines"]["0"].append(dict(value["routines"]["0"][0]))
    value["routines"]["0"].append(dict(value["routines"]["0"][0]))
    with pytest.raises(ValueError) as caught:
        service.save("home", value)
    assert str(caught.value) == "每种定位球保留1–3套套路"


def test_save_rejects_unknown_setpiece(tmp_path):
    with pytest.raises(UnknownSetpiece):
        make_service(tmp_path).save("neutral", {})


def test_export_document_contains_schema_and_value(tmp_path):
    service = make_service(tmp_path)
    payload, filename = service.export_document("home")
    assert filename == "setpieces-home.json"
    document = json.loads(payload)
    assert document["schema"] == DOCUMENT_SCHEMA
    assert document["setpiece_id"] == "home"
    assert document["value"]["throw_styles"] == [0, 1, 0]
    assert payload.endswith(b"\n")


def test_import_document_round_trip(tmp_path):
    service = make_service(tmp_path)
    value = service.get("home")["value"]
    value["throw_styles"] = [1, 1, 0]
    service.save("home", value)
    payload, _ = service.export_document("home")

    target = make_service(tmp_path / "imported", root=tmp_path / "imported")
    imported = target.import_document("home", payload)
    assert imported["configured"] is True
    assert imported["value"] == value


def test_import_document_rejects_target_mismatch(tmp_path):
    service = make_service(tmp_path)
    payload, _ = service.export_document("home")
    with pytest.raises(ValueError) as caught:
        service.import_document("away", payload)
    assert str(caught.value) == DOCUMENT_TARGET_ERROR


def test_import_document_accepts_document_without_target(tmp_path):
    service = make_service(tmp_path)
    document = {"value": service.get("away")["value"]}
    payload = json.dumps(document).encode("utf-8")
    imported = service.import_document("away", payload)
    assert imported["configured"] is True


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"\xff", DOCUMENT_TEXT_ERROR),
        (b"{", DOCUMENT_JSON_ERROR),
        (b"[]", DOCUMENT_FORMAT_ERROR),
        (b'{"value": {}, "extra": 1}', f"{DOCUMENT_FIELDS_ERROR}：extra"),
        (b'{"schema": "other", "value": {}}', DOCUMENT_SCHEMA_ERROR),
        (b'{"setpiece_id": 7, "value": {}}', DOCUMENT_FORMAT_ERROR),
        (b'{"schema": "fm27-setpiece-document-v1"}', DOCUMENT_VALUE_ERROR),
    ],
)
def test_parse_document_rejects_invalid_payloads(payload, message):
    with pytest.raises(ValueError) as caught:
        parse_document(payload)
    assert str(caught.value) == message


def test_parse_document_rejects_oversized_payload():
    with pytest.raises(ValueError) as caught:
        parse_document(b" " * (MAX_DOCUMENT_BYTES + 1))
    assert str(caught.value) == DOCUMENT_SIZE_ERROR


def test_engine_root_missing_raises_unavailable(tmp_path):
    settings = Settings.create(data_dir=tmp_path / "data", token=TOKEN, dev=True)
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    service = SetpiecesService(SettingsService(SettingsRepository(database)), settings)
    with pytest.raises(SetpiecesUnavailable) as caught:
        service.list()
    assert str(caught.value) == ENGINE_UNAVAILABLE_MESSAGE


def test_assets_loader_failure_is_cached(tmp_path):
    calls: list[Path] = []

    def loader(root: Path):
        calls.append(root)
        raise OSError("引擎目录不可读")

    settings = Settings.create(
        data_dir=tmp_path / "data", token=TOKEN, engine_root=tmp_path / "engine", dev=True
    )
    settings.ensure_dirs()
    database = Database(settings.database_path)
    database.initialize()
    service = SetpiecesService(
        SettingsService(SettingsRepository(database)), settings, assets_loader=loader
    )
    for _ in range(2):
        with pytest.raises(SetpiecesUnavailable):
            service.catalog()
    assert len(calls) == 1
