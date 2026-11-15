from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.fmf import FmfCodec
from fm27lab.adapters.storage_sqlite.db import Database
from fm27lab.adapters.storage_sqlite.repositories import PoolRepository
from fm27lab.application.pools import FALLBACK_NAME, PoolService
from fm27lab.tests.test_http_drafts import scenario
from fm27lab.tests.test_pool_schema import entry, tactic


def service(tmp_path: Path) -> PoolService:
    database = Database(tmp_path / "fm27lab.db")
    database.initialize()
    return PoolService(PoolRepository(database))


def fmf_payload(*, tactic_name: str = "客队战术", with_tactic: bool = True) -> bytes:
    document = scenario(23)
    if with_tactic:
        document["teams"][0].update(tactic(tactic_name=tactic_name))
    return FmfCodec().encode(document)


def test_update_changes_name_and_weight_only(tmp_path: Path):
    pools = service(tmp_path)
    created = pools.create(entry("旧名", weight=2))
    updated = pools.update(created["id"], {"name": "新名", "weight": 7})
    assert updated is not None
    assert updated["name"] == "新名"
    assert updated["weight"] == 7
    assert updated["tactic"] == created["tactic"]
    assert updated["created_at"] == created["created_at"]
    assert pools.get(created["id"]) == updated


def test_update_applies_partial_changes(tmp_path: Path):
    pools = service(tmp_path)
    created = pools.create(entry("保留名", weight=2))
    renamed = pools.update(created["id"], {"name": "仅改名"})
    assert renamed is not None
    assert renamed["name"] == "仅改名"
    assert renamed["weight"] == 2
    reweighted = pools.update(created["id"], {"weight": 5})
    assert reweighted is not None
    assert reweighted["name"] == "仅改名"
    assert reweighted["weight"] == 5


def test_update_rejects_unknown_fields_and_empty_payloads(tmp_path: Path):
    pools = service(tmp_path)
    created = pools.create(entry())
    with pytest.raises(ValueError, match="仅支持更新"):
        pools.update(created["id"], {"tactic": {}})
    with pytest.raises(ValueError, match="至少需要提供一项更新字段"):
        pools.update(created["id"], {})
    with pytest.raises(ValueError, match="至少需要提供一项更新字段"):
        pools.update(created["id"], {"name": None})
    for value in ({"weight": 0}, {"weight": 1001}, {"weight": True}, {"name": ""}, {"name": "  "}):
        with pytest.raises(ValueError):
            pools.update(created["id"], value)


def test_update_reports_missing_entries(tmp_path: Path):
    pools = service(tmp_path)
    assert pools.update("missing", {"name": "x"}) is None


def test_import_fmf_creates_pool_entry(tmp_path: Path):
    pools = service(tmp_path)
    items = pools.import_fmf(fmf_payload(), "tactic.fmf")
    assert len(items) == 1
    item = items[0]
    assert item["name"] == "tactic"
    assert item["weight"] == 1
    assert item["roster"] is None
    assert item["tactic"]["tactic_name"] == "客队战术"
    assert item["tactic"]["mentality"] == 3
    assert item["tactic"]["instructions"] == {"1": 2}
    assert item["tactic"]["native_extra_team_bits"] == "0"
    assert len(item["tactic"]["phases"]) == 2
    assert pools.get(item["id"]) == item
    assert pools.list()["total"] == 1


def test_import_fmf_uses_filename_as_entry_name_and_suffixes_duplicates(tmp_path: Path):
    pools = service(tmp_path)
    first = pools.import_fmf(fmf_payload(), "高压逼抢.fmf")
    second = pools.import_fmf(fmf_payload(), "高压逼抢.FMF")
    third = pools.import_fmf(fmf_payload(), "")
    assert [items[0]["name"] for items in (first, second, third)] == [
        "高压逼抢",
        "高压逼抢 2",
        FALLBACK_NAME,
    ]
    assert pools.list()["total"] == 3


def test_import_fmf_keeps_names_within_the_limit(tmp_path: Path):
    pools = service(tmp_path)
    pools.import_fmf(fmf_payload(), "超长名称" * 20)
    items = pools.import_fmf(fmf_payload(), "超长名称" * 20)
    assert len(items[0]["name"]) <= 80
    assert items[0]["name"].endswith(" 2")


def test_import_fmf_rejects_invalid_payloads(tmp_path: Path):
    pools = service(tmp_path)
    with pytest.raises(ValueError, match="FMF 文件无效"):
        pools.import_fmf(b"not a fmf file", "x.fmf")
    with pytest.raises(ValueError, match="FMF 文件内容无效"):
        pools.import_fmf("text", "x.fmf")
    with pytest.raises(ValueError, match="不包含可用战术"):
        pools.import_fmf(fmf_payload(with_tactic=False), "x.fmf")
    assert pools.list()["total"] == 0
