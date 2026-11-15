"""存档战术库应用服务测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.engine_native.tactic_file import UNCONFIGURED_ERROR, TacticFileError, TacticPlan
from fm27lab.adapters.save_fmsave.tactics import StoredTactic
from fm27lab.application.save_tactics import (
    SAVE_MISSING_ERROR,
    SAVE_UNREADABLE_ERROR,
    TACTIC_MISSING_ERROR,
    TACTIC_STREAM_ERROR,
    TACTIC_TEAM_ERROR,
    SaveTacticsService,
)
from fm27lab.config import Settings

PLAN = TacticPlan(name="native", mentality=4, team_bits=0, mapping=tuple(range(11)), phases=((), ()))


def stored(index: int, name: str = "Tactic", team_slot: int | None = 0, has_stream: bool = True) -> StoredTactic:
    return StoredTactic(
        index=index,
        name=name,
        style="Control",
        mentality=5,
        club_uid=7,
        club_name="Sev",
        team_slot=team_slot,
        has_stream=has_stream,
    )


class FakeSaves:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})

    def get(self, save_id):
        return self.entries.get(save_id)


class FakeDrafts:
    def __init__(self):
        self.calls = []

    def create(self, name, scenario, source=None):
        self.calls.append({"name": name, "scenario": scenario, "source": source})
        return {
            "id": "draft-1",
            "name": name,
            "scenario": scenario,
            "source": source,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }


class FakeReader:
    def __init__(self, rows=(), error=None):
        self.rows = tuple(rows)
        self.error = error
        self.calls = []

    def __call__(self, path):
        self.calls.append(Path(path))
        if self.error is not None:
            raise self.error
        return self.rows


class FakeStreamReader:
    def __init__(self, payloads=None, error=None):
        self.payloads = dict(payloads or {})
        self.error = error
        self.calls = []

    def __call__(self, path, index):
        self.calls.append((Path(path), index))
        if self.error is not None:
            raise self.error
        return self.payloads.get(index)


class FakeParser:
    def __init__(self):
        self.calls = []

    def __call__(self, payload, *, name, engine_root, game_root):
        self.calls.append(
            {"payload": payload, "name": name, "engine_root": engine_root, "game_root": game_root}
        )
        return PLAN


class FakeBuilder:
    def __init__(self):
        self.calls = []

    def __call__(self, assets, plan, *, tactic_name=None):
        self.calls.append({"assets": assets, "plan": plan, "tactic_name": tactic_name})
        return {"teams": [{"name": "Home"}, {"name": "Away"}]}


class FakeAssets:
    def __init__(self):
        self.calls = []

    def __call__(self, engine_root):
        self.calls.append(engine_root)
        return "assets"


def make_service(
    tmp_path: Path,
    *,
    rows=(),
    payloads=None,
    engine: bool = True,
    reader_error=None,
    stream_error=None,
):
    source = tmp_path / "save.fm"
    source.write_bytes(b"save-bytes")
    saves = FakeSaves({"save-1": {"id": "save-1", "source_path": str(source)}})
    deps = {
        "source": source,
        "drafts": FakeDrafts(),
        "reader": FakeReader(rows, reader_error),
        "stream": FakeStreamReader(payloads, stream_error),
        "parser": FakeParser(),
        "builder": FakeBuilder(),
        "assets": FakeAssets(),
    }
    settings = Settings.create(
        data_dir=tmp_path / "data",
        token="c" * 64,
        engine_root=(tmp_path / "engine") if engine else None,
        game_root=(tmp_path / "game") if engine else None,
        dev=True,
    )
    deps["settings"] = settings
    service = SaveTacticsService(
        saves,
        deps["drafts"],
        settings,
        reader=deps["reader"],
        stream_reader=deps["stream"],
        parser=deps["parser"],
        assets_loader=deps["assets"],
        builder=deps["builder"],
    )
    return service, deps


def test_list_tactics_returns_none_for_unknown_save(tmp_path: Path):
    service, _ = make_service(tmp_path)

    assert service.list_tactics("missing") is None


def test_list_tactics_rejects_missing_source_file(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path / "data", token="c" * 64, dev=True)
    saves = FakeSaves(
        {
            "save-1": {"id": "save-1", "source_path": str(tmp_path / "gone.fm")},
            "save-2": {"id": "save-2", "source_path": None},
        }
    )
    service = SaveTacticsService(saves, FakeDrafts(), settings, reader=FakeReader(()))

    with pytest.raises(ValueError, match=SAVE_MISSING_ERROR):
        service.list_tactics("save-1")
    with pytest.raises(ValueError, match=SAVE_MISSING_ERROR):
        service.list_tactics("save-2")


def test_list_tactics_marks_importable_only_for_first_team_with_stream(tmp_path: Path):
    rows = (
        stored(0, "Direct", team_slot=0, has_stream=True),
        stored(1, "Reserve", team_slot=1, has_stream=True),
        stored(2, "Detached", team_slot=0, has_stream=False),
        stored(3, "Third", team_slot=3, has_stream=True),
    )
    service, _ = make_service(tmp_path, rows=rows)

    items = service.list_tactics("save-1")

    assert [item["importable"] for item in items] == [True, False, False, False]
    assert items[0] == {
        "index": 0,
        "name": "Direct",
        "style": "Control",
        "mentality": 5,
        "club_uid": 7,
        "club_name": "Sev",
        "team_slot": 0,
        "importable": True,
    }


def test_list_tactics_marks_nothing_importable_without_engine(tmp_path: Path):
    service, _ = make_service(tmp_path, rows=(stored(0),), engine=False)

    items = service.list_tactics("save-1")

    assert items[0]["importable"] is False


def test_list_tactics_caches_until_file_signature_changes(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0),))

    first = service.list_tactics("save-1")
    first[0]["name"] = "mutated"
    second = service.list_tactics("save-1")
    assert len(deps["reader"].calls) == 1
    assert second[0]["name"] == "Tactic"

    deps["source"].write_bytes(b"changed-save-bytes")
    service.list_tactics("save-1")
    assert len(deps["reader"].calls) == 2


def test_list_tactics_wraps_reader_runtime_error(tmp_path: Path):
    service, _ = make_service(
        tmp_path,
        reader_error=RuntimeError("未安装存档读取依赖 fmsave"),
    )

    with pytest.raises(ValueError) as info:
        service.list_tactics("save-1")

    assert str(info.value) == f"{SAVE_UNREADABLE_ERROR}：未安装存档读取依赖 fmsave"


def test_list_tactics_wraps_reader_os_error(tmp_path: Path):
    service, _ = make_service(tmp_path, reader_error=OSError("磁盘读取失败"))

    with pytest.raises(ValueError) as info:
        service.list_tactics("save-1")

    assert str(info.value) == f"{SAVE_UNREADABLE_ERROR}：磁盘读取失败"


def test_list_tactics_preserves_reader_value_error(tmp_path: Path):
    service, _ = make_service(tmp_path, reader_error=ValueError("存档结构损坏"))

    with pytest.raises(ValueError) as info:
        service.list_tactics("save-1")

    assert str(info.value) == "存档结构损坏"


def test_import_tactic_returns_none_for_unknown_save(tmp_path: Path):
    service, _ = make_service(tmp_path)

    assert service.import_tactic("missing", 0) is None


def test_import_tactic_rejects_missing_source_file(tmp_path: Path):
    settings = Settings.create(data_dir=tmp_path / "data", token="c" * 64, dev=True)
    saves = FakeSaves({"save-1": {"id": "save-1", "source_path": str(tmp_path / "gone.fm")}})
    service = SaveTacticsService(saves, FakeDrafts(), settings, reader=FakeReader(()))

    with pytest.raises(ValueError, match=SAVE_MISSING_ERROR):
        service.import_tactic("save-1", 0)


def test_import_tactic_rejects_unknown_tactic_index(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0),), payloads={0: b"raw"})

    with pytest.raises(ValueError, match=TACTIC_MISSING_ERROR):
        service.import_tactic("save-1", 4)

    assert deps["stream"].calls == []
    assert deps["parser"].calls == []


def test_import_tactic_rejects_non_first_team_tactic(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0, team_slot=2),), payloads={0: b"raw"})

    with pytest.raises(ValueError, match=TACTIC_TEAM_ERROR):
        service.import_tactic("save-1", 0)

    assert deps["stream"].calls == []
    assert deps["parser"].calls == []


def test_import_tactic_requires_engine_configuration(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0),), payloads={0: b"raw"}, engine=False)

    with pytest.raises(TacticFileError) as info:
        service.import_tactic("save-1", 0)

    assert str(info.value) == UNCONFIGURED_ERROR
    assert deps["stream"].calls == []
    assert deps["parser"].calls == []


def test_import_tactic_rejects_missing_stream(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0),), payloads={})

    with pytest.raises(ValueError, match=TACTIC_STREAM_ERROR):
        service.import_tactic("save-1", 0)

    assert deps["parser"].calls == []


def test_import_tactic_wraps_stream_reader_runtime_error(tmp_path: Path):
    service, _ = make_service(
        tmp_path,
        rows=(stored(0),),
        stream_error=RuntimeError("读取失败"),
    )

    with pytest.raises(ValueError) as info:
        service.import_tactic("save-1", 0)

    assert str(info.value) == f"{SAVE_UNREADABLE_ERROR}：读取失败"


def test_import_tactic_wraps_stream_reader_os_error(tmp_path: Path):
    service, _ = make_service(
        tmp_path,
        rows=(stored(0),),
        stream_error=OSError("句柄已关闭"),
    )

    with pytest.raises(ValueError) as info:
        service.import_tactic("save-1", 0)

    assert str(info.value) == f"{SAVE_UNREADABLE_ERROR}：句柄已关闭"


def test_import_tactic_preserves_stream_reader_value_error(tmp_path: Path):
    service, _ = make_service(
        tmp_path,
        rows=(stored(0),),
        stream_error=ValueError("战术流损坏"),
    )

    with pytest.raises(ValueError) as info:
        service.import_tactic("save-1", 0)

    assert str(info.value) == "战术流损坏"


def test_import_tactic_builds_draft_from_parsed_stream(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0, "Direct"),), payloads={0: b"raw-stream"})

    draft = service.import_tactic("save-1", 0)

    parser_call = deps["parser"].calls[0]
    assert parser_call["payload"] == b"raw-stream"
    assert parser_call["name"] == "Direct"
    assert parser_call["engine_root"] == deps["settings"].engine_root
    assert parser_call["game_root"] == deps["settings"].game_root
    assert deps["assets"].calls == [deps["settings"].engine_root]
    builder_call = deps["builder"].calls[0]
    assert builder_call["assets"] == "assets"
    assert builder_call["plan"] == PLAN
    assert builder_call["tactic_name"] == "Direct"
    assert deps["drafts"].calls[0]["name"] == "Direct"
    assert deps["drafts"].calls[0]["source"] == {
        "kind": "save_tactic",
        "save_id": "save-1",
        "tactic_index": 0,
    }
    assert draft["id"] == "draft-1"


def test_import_tactic_uses_requested_draft_name(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0, "Direct"),), payloads={0: b"raw"})

    service.import_tactic("save-1", 0, name="My Plan")

    assert deps["drafts"].calls[0]["name"] == "My Plan"


def test_import_tactic_falls_back_to_tactic_name_for_blank_name(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0, "Direct"),), payloads={0: b"raw"})

    service.import_tactic("save-1", 0, name="   ")

    assert deps["drafts"].calls[0]["name"] == "Direct"


def test_import_tactic_truncates_long_draft_name(tmp_path: Path):
    service, deps = make_service(tmp_path, rows=(stored(0, "Direct"),), payloads={0: b"raw"})

    service.import_tactic("save-1", 0, name="x" * 200)

    assert deps["drafts"].calls[0]["name"] == "x" * 80
