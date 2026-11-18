"""原装教练预设导出、偏好读回与匹配测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from fm27lab.adapters.engine_native import coach_presets
from fm27lab.adapters.engine_native.coach_presets import (
    EXPORT_COMPLETE_EVENT,
    FORMATION_EVENT,
    STAFF_EVENT,
    STYLE_EVENT,
    TEMPLATE_EVENT,
    CoachPresetError,
    decode_staff,
    export_catalog,
    variants,
)
from fm27lab.adapters.engine_native.tactic_file import HostRun


def cell(position: int, role: int = 1, pi: int = 0) -> dict:
    return {
        "position": position,
        "role_flags": str(role),
        "pi_flags": str(pi),
        "target_player": 255,
        "target_position": 0,
    }


PRIMARY = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)
SECONDARY = tuple(reversed(PRIMARY))


def phases(positions: tuple[int, ...]) -> list[list[dict]]:
    return [[cell(position) for position in positions], [cell(position) for position in positions]]


def template(index: int, style: int, name: str, positions: tuple[int, ...]) -> dict:
    return {
        "event": TEMPLATE_EVENT,
        "index": index,
        "style_code": style,
        "name_utf8_hex": name.encode("utf8").hex(),
        "mentality": 4,
        "team_bits": "1f" + "00" * 15,
        "mapping": list(range(11)),
        "phases": phases(positions),
    }


def catalog_events() -> list[dict]:
    return [
        {"event": STYLE_EVENT, "id": 0, "style_code": 100},
        {"event": STYLE_EVENT, "id": 1, "style_code": 200},
        {"event": FORMATION_EVENT, "code": 10, "positions": list(PRIMARY)},
        {"event": FORMATION_EVENT, "code": 20, "positions": list(SECONDARY)},
        template(0, 100, "控球甲", PRIMARY),
        template(1, 100, "控球乙", SECONDARY),
        template(2, 200, "防守甲", (1,) * 11),
        {"event": EXPORT_COMPLETE_EVENT, "styles": 2, "templates": 3, "formations": 2},
    ]


def staff_event(selector: int, style: int, primary: int, secondary: int) -> dict:
    raw = bytearray(33)
    raw[11] = primary
    raw[12] = secondary
    raw[20] = style
    return {
        "event": STAFF_EVENT,
        "selector": selector,
        "accepted": True,
        "error": 0,
        "profile_hex": "00" * 52,
        "native_d4_to_f4_hex": bytes(raw).hex(),
    }


def test_export_catalog_reads_styles_formations_and_templates(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        return HostRun(returncode=0, events=catalog_events(), text="")

    monkeypatch.setattr(coach_presets, "execute_host", runner)
    catalog = export_catalog(engine_root=Path("engine"), game_root=Path("game"))
    assert calls[0]["environment"] == {coach_presets.PRESET_EXPORT_ENVIRONMENT: "1"}
    assert catalog.styles == {0: 100, 1: 200}
    assert catalog.formations[10] == PRIMARY
    assert [item.name for item in catalog.templates] == ["控球甲", "控球乙", "防守甲"]
    assert catalog.templates[0].plan.mentality == 4
    assert catalog.templates[0].plan.team_bits == 0x1F


def test_export_catalog_rejects_incomplete_counts(monkeypatch: pytest.MonkeyPatch):
    events = catalog_events()
    events[-1] = {**events[-1], "templates": 4}

    monkeypatch.setattr(
        coach_presets,
        "execute_host",
        lambda **kwargs: HostRun(returncode=0, events=events, text=""),
    )
    with pytest.raises(CoachPresetError, match="模板目录"):
        export_catalog(engine_root=Path("engine"), game_root=Path("game"))


def test_decode_staff_reads_style_and_formation_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def runner(**kwargs):
        root = Path(kwargs["environment"][coach_presets.STAFF_FRAGMENT_ENVIRONMENT])
        assert (root / "5.bin").read_bytes() == b"fragment"
        return HostRun(returncode=0, events=[staff_event(5, 1, 29, 4)], text="")

    monkeypatch.setattr(coach_presets, "execute_host", runner)
    decoded = decode_staff(
        {5: b"fragment"},
        engine_root=Path("engine"),
        game_root=Path("game"),
    )
    assert decoded[5].style == 1
    assert decoded[5].primary == 29
    assert decoded[5].secondary == 4
    assert decoded[5].profile_hex == "00" * 52
    assert decoded[5].codes_hex == "1d04000000000000"


def test_decode_staff_rejects_native_readback_failure(monkeypatch: pytest.MonkeyPatch):
    failed = {**staff_event(5, 1, 29, 4), "accepted": False}
    monkeypatch.setattr(
        coach_presets,
        "execute_host",
        lambda **kwargs: HostRun(returncode=0, events=[failed], text=""),
    )
    with pytest.raises(CoachPresetError, match="原版读回"):
        decode_staff({5: b"fragment"}, engine_root=Path("engine"), game_root=Path("game"))


def test_variants_prefers_exact_primary_and_secondary_shape(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        coach_presets,
        "execute_host",
        lambda **kwargs: HostRun(returncode=0, events=catalog_events(), text=""),
    )
    catalog = export_catalog(engine_root=Path("engine"), game_root=Path("game"))
    options = variants(catalog, style=0, primary=10, secondary=20)
    assert [item.variant for item in options] == [1, 2]
    assert options[0].template.name == "控球甲"
    assert options[0].exact is True
    assert options[1].template.name == "控球乙"
    assert options[1].exact is True


def test_variants_rejects_unmapped_style():
    catalog = coach_presets.PresetCatalog(
        styles={0: 100},
        formations={10: PRIMARY},
        templates=(),
    )
    with pytest.raises(CoachPresetError, match="预设风格"):
        variants(catalog, style=9, primary=10, secondary=10)


def test_export_catalog_rejects_malformed_team_bits(monkeypatch: pytest.MonkeyPatch):
    events = catalog_events()
    events[4] = {**events[4], "team_bits": "1f"}
    monkeypatch.setattr(
        coach_presets,
        "execute_host",
        lambda **kwargs: HostRun(returncode=0, events=events, text=""),
    )
    with pytest.raises(CoachPresetError, match="球队指令位"):
        export_catalog(engine_root=Path("engine"), game_root=Path("game"))


def test_export_catalog_rejects_malformed_event_fields(monkeypatch: pytest.MonkeyPatch):
    events = catalog_events()
    events[0] = {"event": STYLE_EVENT, "style_code": 100}
    monkeypatch.setattr(
        coach_presets,
        "execute_host",
        lambda **kwargs: HostRun(returncode=0, events=events, text=""),
    )
    with pytest.raises(CoachPresetError, match="事件字段"):
        export_catalog(engine_root=Path("engine"), game_root=Path("game"))
