"""FM27 27.1.1 build layout registration tests."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import ModuleType
from typing import Any

import pytest

from fm27lab.adapters.save_fmsave import builds, reader

BASE_BUILD = "27.1.0+2505117"
TARGET_BUILD = "27.1.1+2511875"
BORROWED_BUILD = "27.0.0+2486695"
GAME_DB_REGION = "game_db"
GAME_DB_SCHEMA = 4000


def _find_layout(layout_type: type[Any], build: str) -> Any:
    from fmsave._layouts import find_layout

    return find_layout(layout_type, GAME_DB_REGION, GAME_DB_SCHEMA, build)


def _target_entries() -> tuple[Any, ...]:
    from fmsave._layouts import registered_layouts

    return tuple(
        entry
        for entry in registered_layouts()
        if entry.build == TARGET_BUILD and entry.region == GAME_DB_REGION
    )


@pytest.fixture
def base_layouts() -> Iterator[ModuleType]:
    pytest.importorskip("fmsave._layouts")
    try:
        module = importlib.import_module("fmsave._layouts.fm27_27_1_0")
    except ImportError:
        pytest.skip("fmsave 未注册 FM27 27.1.0 布局")
    original = module.LAYOUTS
    module.LAYOUTS = tuple(entry for entry in original if entry.build != TARGET_BUILD)
    yield module
    module.LAYOUTS = original


def test_install_gives_27_1_1_the_exact_27_1_0_game_db_layouts(base_layouts: ModuleType) -> None:
    from fmsave._layouts import ClubTableLayout, SponsorChainLayout

    assert _find_layout(ClubTableLayout, TARGET_BUILD).exact is False
    assert builds.install() is True
    for layout_type in (ClubTableLayout, SponsorChainLayout):
        match = _find_layout(layout_type, TARGET_BUILD)
        assert match.exact is True
        assert match.source_build == TARGET_BUILD
        assert match.source_schema == GAME_DB_SCHEMA
        assert match.layout == _find_layout(layout_type, BASE_BUILD).layout


def test_club_and_finance_readers_select_the_27_1_0_layouts_for_27_1_1(
    base_layouts: ModuleType,
) -> None:
    from fmsave.readers.clubs import find_club_layouts
    from fmsave.readers.finances import find_finance_layouts

    before = find_club_layouts(GAME_DB_SCHEMA, TARGET_BUILD)
    assert before.table is not base_layouts.CLUB_TABLE
    assert before.fallback_table is base_layouts.CLUB_TABLE
    sponsored_before = find_finance_layouts(GAME_DB_SCHEMA, TARGET_BUILD).sponsors
    assert sponsored_before is not base_layouts.SPONSOR_CHAINS
    assert builds.install() is True
    after = find_club_layouts(GAME_DB_SCHEMA, TARGET_BUILD)
    assert after.table is base_layouts.CLUB_TABLE
    assert after.fallback_table is base_layouts.CLUB_TABLE
    sponsored_after = find_finance_layouts(GAME_DB_SCHEMA, TARGET_BUILD).sponsors
    assert sponsored_after is base_layouts.SPONSOR_CHAINS


def test_install_leaves_27_0_0_and_27_1_0_layouts_unchanged(base_layouts: ModuleType) -> None:
    from fmsave._layouts import ClubTableLayout

    before = {
        build: _find_layout(ClubTableLayout, build) for build in (BORROWED_BUILD, BASE_BUILD)
    }
    assert before[BORROWED_BUILD].exact is True
    assert before[BORROWED_BUILD].source_build == BORROWED_BUILD
    assert before[BASE_BUILD].exact is True
    assert before[BASE_BUILD].source_build == BASE_BUILD
    assert builds.install() is True
    after = {
        build: _find_layout(ClubTableLayout, build) for build in (BORROWED_BUILD, BASE_BUILD)
    }
    assert after == before


def test_install_is_idempotent_and_keeps_original_entries(base_layouts: ModuleType) -> None:
    from fmsave._layouts import registered_layouts

    originals = tuple(
        entry
        for entry in registered_layouts()
        if entry.build == BASE_BUILD and entry.region == GAME_DB_REGION
    )
    assert originals
    assert builds.install() is True
    installed = tuple(
        entry
        for entry in registered_layouts()
        if entry.build == TARGET_BUILD and entry.region == GAME_DB_REGION
    )
    assert len(installed) == len(originals)
    assert [(entry.schema, entry.layout) for entry in installed] == [
        (entry.schema, entry.layout) for entry in originals
    ]
    assert builds.install() is True
    repeated = tuple(
        entry
        for entry in registered_layouts()
        if entry.build == TARGET_BUILD and entry.region == GAME_DB_REGION
    )
    assert repeated == installed
    assert all(entry in registered_layouts() for entry in originals)


def test_install_keeps_target_layouts_registered_by_another_module(
    base_layouts: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fmsave._layouts import ClubTableLayout, SponsorChainLayout, fm27_27_0_0

    future_table = replace(
        base_layouts.CLUB_TABLE, header_bytes=base_layouts.CLUB_TABLE.header_bytes + 1
    )
    base_entry = next(
        entry for entry in base_layouts.LAYOUTS if isinstance(entry.layout, ClubTableLayout)
    )
    monkeypatch.setattr(
        fm27_27_0_0,
        "LAYOUTS",
        (*fm27_27_0_0.LAYOUTS, replace(base_entry, build=TARGET_BUILD, layout=future_table)),
    )
    assert builds.install() is True
    for layout_type in (ClubTableLayout, SponsorChainLayout):
        match = _find_layout(layout_type, TARGET_BUILD)
        assert match.exact is True
        assert match.source_build == TARGET_BUILD
    assert _find_layout(ClubTableLayout, TARGET_BUILD).layout is future_table
    target_entries = _target_entries()
    assert len(target_entries) == 2
    assert len({(entry.region, entry.schema, type(entry.layout)) for entry in target_entries}) == 2


def test_install_fills_only_the_missing_target_layouts(
    base_layouts: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fmsave._layouts import ClubTableLayout, SponsorChainLayout

    base_entry = next(
        entry for entry in base_layouts.LAYOUTS if isinstance(entry.layout, ClubTableLayout)
    )
    monkeypatch.setattr(
        base_layouts,
        "LAYOUTS",
        (*base_layouts.LAYOUTS, replace(base_entry, build=TARGET_BUILD)),
    )
    assert builds.install() is True
    for layout_type in (ClubTableLayout, SponsorChainLayout):
        match = _find_layout(layout_type, TARGET_BUILD)
        assert match.exact is True
        assert match.source_build == TARGET_BUILD
    target_entries = _target_entries()
    assert len(target_entries) == 2
    assert len({(entry.region, entry.schema, type(entry.layout)) for entry in target_entries}) == 2


def test_install_is_idempotent_under_concurrent_calls(base_layouts: ModuleType) -> None:
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = [pool.submit(builds.install) for _ in range(50)]
        assert all(result.result() for result in results)
    target_entries = _target_entries()
    assert len(target_entries) == 2
    assert len({(entry.region, entry.schema, type(entry.layout)) for entry in target_entries}) == 2


def test_install_returns_false_when_27_1_0_layout_module_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layouts = pytest.importorskip("fmsave._layouts")
    try:
        importlib.import_module("fmsave._layouts.fm27_27_1_0")
    except ImportError:
        assert builds.install() is False
        return
    monkeypatch.delattr(layouts, "fm27_27_1_0", raising=False)
    monkeypatch.setitem(sys.modules, "fmsave._layouts.fm27_27_1_0", None)
    assert builds.install() is False


def test_install_returns_false_when_layouts_package_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "fmsave._layouts", None)
    assert builds.install() is False


def test_install_returns_false_without_layout_table(
    base_layouts: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(base_layouts, "LAYOUTS")
    assert builds.install() is False


def test_install_returns_false_without_27_1_0_game_db_entries(
    base_layouts: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(base_layouts, "LAYOUTS", ())
    assert builds.install() is False


def test_loading_fmsave_installs_27_1_1_layouts(base_layouts: ModuleType) -> None:
    from fmsave._layouts import ClubTableLayout

    assert _find_layout(ClubTableLayout, TARGET_BUILD).exact is False
    reader._load_fmsave()
    match = _find_layout(ClubTableLayout, TARGET_BUILD)
    assert match.exact is True
    assert match.source_build == TARGET_BUILD


def test_install_does_not_declare_27_1_1_a_fully_known_build(base_layouts: ModuleType) -> None:
    from fmsave._layouts import known_builds

    assert builds.install() is True
    assert TARGET_BUILD not in known_builds()
